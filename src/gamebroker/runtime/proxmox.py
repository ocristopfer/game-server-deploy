"""Proxmox backend: creates, starts, stops and destroys CTs of the broker pool via the REST API.

Everything here was validated against a real Proxmox VE 9.2 (Phase 0 spike). The facts that
shape the code:

- `tags` AT CREATION requires VM.Config.Options on /vms/<id>, which does not exist yet and does
  not inherit from the pool: the tag is written AFTERWARDS, with the CT already in the pool. And
  if even that fails it is not fatal - the identity of a broker CT is the pool
  (`pertence_ao_broker`), not the tag.
- `keyctl=1` is allowed only for root@pam. Only `nesting=1` is sent.
- A task ending in `WARNINGS: n` is a success (e.g. "Systemd 257: pode precisar de nesting").
- The reason for a 403 comes in the HTTP status line (`conexao.Cliente` already returns it).
"""
from __future__ import annotations

import contextlib
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote

from gamebroker.integrations.http_client import Client, Response
from gamebroker.runtime.base import InstanceSpec

BROKER_TAG = "gamepanel-broker"
_NAME_RE = re.compile(r"[A-Za-z0-9._-]{1,64}", re.ASCII)
_VOLID_RE = re.compile(r"[A-Za-z0-9._-]+:vztmpl/[A-Za-z0-9._+-]+", re.ASCII)
_NETWORK_IP_RE = re.compile(r"ip=(\d{1,3}(?:\.\d{1,3}){3})")
MAX_ERRORS = 200
# Health probe: a service that does not answer within a few seconds is already the answer.
SONDA_TIMEOUT = 5.0


class ProxmoxError(RuntimeError):
    """Failure talking to Proxmox. The message carries no token or header."""


@dataclass(frozen=True)
class ConfigProxmox:
    node: str
    pool: str
    storage: str
    template: str
    bridge: str
    gateway: str
    ssh_keys: tuple[str, ...]
    prefix: int = 24
    interval: float = 2.0
    attempts: int = 150

    def __post_init__(self) -> None:
        for field in (self.node, self.pool, self.storage, self.bridge):
            if not _NAME_RE.fullmatch(field):
                raise ValueError(f"nome invalido na config do Proxmox: {field!r}")
        if not _VOLID_RE.fullmatch(self.template):
            raise ValueError("template deve ser <storage>:vztmpl/<arquivo>")
        if not self.ssh_keys or not all(k.startswith("ssh-") and "\n" not in k for k in self.ssh_keys):
            raise ValueError("ssh_keys: informe ao menos uma chave publica (uma por item, sem quebra de linha)")


class Proxmox:
    def __init__(self, cliente: Client, config: ConfigProxmox,
                 sleep: Callable[[float], None] = time.sleep):
        self._c = cliente
        self._cfg = config
        self._sleep = sleep

    # --- calls --------------------------------------------------------------

    def _api(self, method: str, path: str, action: str, *, form: dict | None = None) -> Response:
        response = self._c.request(method, "/api2/json" + path, form=form)
        if not response.ok:
            raise ProxmoxError(f"{action}: HTTP {response.status} {_short(response.text)}")
        return response

    @staticmethod
    def _payload(resposta: Response) -> object:
        return resposta.json.get("data") if isinstance(resposta.json, dict) else None

    def _task(self, resposta: Response, action: str) -> None:
        upid = self._payload(resposta)
        if not isinstance(upid, str):
            raise ProxmoxError(f"{action}: o Proxmox nao devolveu o identificador da tarefa")
        encoded = quote(upid, safe="")
        for _ in range(self._cfg.attempts):
            state_dir = self._payload(self._api("GET", f"/nodes/{self._cfg.node}/tasks/{encoded}/status",
                                           f"{action} (estado da tarefa)"))
            if isinstance(state_dir, dict) and state_dir.get("status") == "stopped":
                output = str(state_dir.get("exitstatus", ""))
                if output == "OK" or output.startswith("WARNINGS"):
                    return
                raise ProxmoxError(f"{action}: a tarefa terminou com '{_short(output)}'{self._log_tail(encoded)}")
            self._sleep(self._cfg.interval)
        raise ProxmoxError(f"{action}: a tarefa excedeu o tempo")

    def _log_tail(self, upid_codificado: str) -> str:
        response = self._c.request(
            "GET", f"/api2/json/nodes/{self._cfg.node}/tasks/{upid_codificado}/log?limit=20")
        lines = self._payload(response) if response.ok else None
        if not isinstance(lines, list) or not lines:
            return ""
        last_ones = " | ".join(str(item.get("t", "")) for item in lines[-3:] if isinstance(item, dict))
        return f" ({_short(last_ones)})"

    # --- reading ---------------------------------------------------------------

    def handles_and_ips(self) -> tuple[set[str], set[str]]:
        """CTIDs and IPs the token sees. With the role only on the pool this is ONLY the pool; to
        see CTs outside it, the token needs VM.Audit on /vms (optional)."""
        entries = self._payload(self._api("GET", "/cluster/resources?type=vm", "listar CTs"))
        ctids: set[int] = set()
        ips: set[str] = set()
        for item in entries if isinstance(entries, list) else []:
            if not isinstance(item, dict) or not isinstance(item.get("vmid"), int):
                continue
            ctids.add(item["vmid"])
            if item.get("type") == "lxc":
                ips |= self._ct_ips(item["vmid"])
        # The Proxmox handle is the CTID as TEXT: the conversion lives here, at the boundary,
        # and not in the service - this is the only thing that knows this backend numbers instances.
        return {str(c) for c in ctids}, ips

    def _ct_ips(self, ctid: int) -> set[str]:
        response = self._c.request("GET", f"/api2/json/nodes/{self._cfg.node}/lxc/{ctid}/config")
        config = self._payload(response) if response.ok else None
        if not isinstance(config, dict):
            return set()
        found: set[str] = set()
        for key, value in config.items():
            if re.fullmatch(r"net\d+", str(key)) and isinstance(value, str):
                found.update(_NETWORK_IP_RE.findall(value))
        return found

    def belongs_to_broker(self, handle: str) -> bool:
        """Identity = being a member of the broker pool. Does not depend on the tag."""
        ctid = int(handle)
        data = self._payload(self._c.request("GET", f"/api2/json/pools/{self._cfg.pool}"))
        members = data.get("members", []) if isinstance(data, dict) else []
        return any(isinstance(m, dict) and m.get("vmid") == ctid and m.get("type") == "lxc" for m in members)

    def reachable(self) -> bool:
        try:
            return self._c.request("GET", "/api2/json/version", timeout=SONDA_TIMEOUT).ok
        except Exception:  # noqa: BLE001
            return False

    # --- writing ------------------------------------------------------------------

    def create(self, spec: InstanceSpec) -> None:
        cfg = self._cfg
        body = {
            "vmid": int(spec.handle), "hostname": spec.hostname,
            "ostemplate": cfg.template, "rootfs": f"{cfg.storage}:{spec.disk_gb}",
            "memory": spec.memory_mb, "swap": 0, "cores": spec.cores,
            "unprivileged": 1, "features": "nesting=1", "pool": cfg.pool, "start": 0, "onboot": 1,
            "net0": (f"name=eth0,bridge={cfg.bridge},ip={spec.ip}/{cfg.prefix},"
                     f"gw={cfg.gateway},type=veth"),
            "ssh-public-keys": "\n".join(cfg.ssh_keys),
        }
        self._task(self._api("POST", f"/nodes/{cfg.node}/lxc", "criar CT", form=body), "criar CT")
        # The tag is a convenience (it shows up on the Proxmox screen); the identity is the pool,
        # and the token cannot always write it. `suppress` and not `try/except/pass`: with a
        # single error type it says the same thing in one line.
        with contextlib.suppress(ProxmoxError):
            self._api("PUT", f"/nodes/{cfg.node}/lxc/{int(spec.handle)}/config", "gravar a tag",
                      form={"tags": BROKER_TAG})

    def start(self, handle: str) -> None:
        ctid = int(handle)
        self._task(self._api("POST", f"/nodes/{self._cfg.node}/lxc/{ctid}/status/start",
                               "iniciar CT"), "iniciar CT")

    def stop(self, handle: str) -> None:
        ctid = int(handle)
        self._require_in_pool(ctid)
        self._task(self._api("POST", f"/nodes/{self._cfg.node}/lxc/{ctid}/status/shutdown",
                               "parar CT", form={"forceStop": 1, "timeout": 30}), "parar CT")

    def destroy(self, handle: str) -> None:
        ctid = int(handle)
        self._require_in_pool(ctid)
        state_dir = self._payload(self._api("GET", f"/nodes/{self._cfg.node}/lxc/{ctid}/status/current",
                                       "ler estado do CT"))
        if isinstance(state_dir, dict) and state_dir.get("status") == "running":
            self.stop(handle)
        self._task(self._api(
            "DELETE", f"/nodes/{self._cfg.node}/lxc/{ctid}?purge=1&destroy-unreferenced-disks=1",
            "destruir CT"), "destruir CT")

    def _require_in_pool(self, ctid: int) -> None:
        # The token only has permission on the pool, but this check stands on its own: if
        # someone widens the role one day, the broker still only touches what is its own.
        if not self.belongs_to_broker(str(ctid)):
            raise ProxmoxError(f"o CT {ctid} nao esta no pool '{self._cfg.pool}'; nada foi alterado")


def _short(text: str) -> str:
    clean = " ".join(str(text).split())
    return clean if len(clean) <= MAX_ERRORS else clean[:MAX_ERRORS] + "..."
