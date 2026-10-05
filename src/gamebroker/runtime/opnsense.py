"""OPNsense backend: opens and closes WAN port forwards (d_nat).

Facts validated against a real OPNsense 26.7.4 (Phase 0 spike):

- The existing game rules use port ALIASES (`JOGO_PALWORLD`...), not numbers.
  `search_rule` returns the alias content in `alias_meta_destination.port`, as HTML text
  (`<strong>descricao</strong><br/>8211<br/>27015`). That is where the broker finds out which
  ports are already taken - `alias/search_item` returns 403 for the broker's key.
- If a WAN rule uses a format we do not understand, the broker REFUSES to open a new port
  (`ErroDeLeitura`) instead of assuming the port is free: err on the side of not opening.
- A disabled rule still counts as taken (users turn their own rules on and off).
- `filter/apply` is only authorized by the "Firewall: Rules [new]" privilege.
- `pass=pass` saves and `associated-rule-id` stays empty, just like the existing rules.
"""
from __future__ import annotations

import ipaddress
import re
from collections.abc import Sequence

from gamebroker.integrations.http_client import Client, Response
from gamebroker.services.allocator import AllocatedPort
from gamebroker.services.catalog import MAX_PORT

DESCRIPTION_PREFIX = "gamepanel:"
RANGE_LIMIT = 5000
# Health probe: a service that does not answer within a few seconds is already the answer.
SONDA_TIMEOUT = 5.0
_UUID_RE = re.compile(r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}")
_PORT_RE = re.compile(r"\d{1,5}")
_RANGE_RE = re.compile(r"(\d{1,5})[-:](\d{1,5})")
_LINE_BREAK_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_SEARCH_ARGS = {"current": 1, "rowCount": -1}


class OpnsenseError(RuntimeError):
    """Failure talking to OPNsense. The message carries no key or secret."""


class ReadError(OpnsenseError):
    """An existing rule the broker could not interpret: no new port is opened."""


# The handle used to come in through `int()`, and THAT was what rejected `"300; drop"`. With the
# opaque (text) handle the `int()` went away and the rejection would have gone with it - the
# description test caught it. The description goes into the OPNsense rule's `descr` field, and
# `close_ports` matches it by EQUALITY: a handle with an odd character would not become shell
# injection, but it would break the match and leave an orphan rule in the firewall, which is the
# silent way for a port to stay open for a container that no longer exists.
HANDLE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,62}", re.ASCII)


def instance_description(handle: str) -> str:
    """`gamepanel:<handle>`, rejecting a handle that is not a simple token.

    `re.ASCII` on purpose: without the flag, the "word" shorthand matches accented letters and
    some 900 other Unicode characters, and what is wanted here is the narrow set that survives
    the round trip through the OPNsense API.
    """
    if not HANDLE_RE.fullmatch(handle):
        raise ValueError("handle invalido para descricao de regra")
    return f"{DESCRIPTION_PREFIX}{handle}"


# --- reading the taken ports ------------------------------------------------------

def _number_of(text: str) -> int:
    value = int(text)
    if not 1 <= value <= MAX_PORT:
        raise ValueError
    return value


def _expand_ports(item: str, rule: str) -> set[int]:
    """`7660` or `8000-8010` (or `8000:8010`) -> set of ports."""
    item = item.strip()
    try:
        if _PORT_RE.fullmatch(item):
            return {_number_of(item)}
        span_range = _RANGE_RE.fullmatch(item)
        if span_range:
            start_at, end_at = _number_of(span_range.group(1)), _number_of(span_range.group(2))
            if start_at <= end_at and end_at - start_at < RANGE_LIMIT:
                return set(range(start_at, end_at + 1))
    except ValueError:
        pass
    raise ReadError(f"regra '{rule}': nao entendi a porta {item!r}")


def _ports_of_alias(meta: object, rule: str) -> set[int]:
    if not isinstance(meta, list) or not meta:
        raise ReadError(f"regra '{rule}': o alias de porta nao veio no resultado")
    ports: set[int] = set()
    for alias in meta:
        summary = alias.get("summary") if isinstance(alias, dict) else None
        if not isinstance(summary, str):
            raise ReadError(f"regra '{rule}': alias sem conteudo legivel")
        read_lines = 0
        for chunk_of in _LINE_BREAK_RE.split(summary):
            chunk_of = chunk_of.strip()
            # The first piece is usually the alias description, in HTML: not a port.
            if not chunk_of or "<" in chunk_of or ">" in chunk_of:
                continue
            ports |= _expand_ports(chunk_of, rule)
            read_lines += 1
        if read_lines == 0:
            raise ReadError(f"regra '{rule}': o alias nao lista nenhuma porta que eu entenda")
    return ports


def _protocols_of(protocol: str) -> tuple[str, ...]:
    # tcp/udp (or anything that is not only tcp or only udp) takes both: err on the side of excess.
    protocol = protocol.strip().lower()
    return (protocol,) if protocol in ("tcp", "udp") else ("tcp", "udp")


def busy_ports(rows: object, interface: str) -> set[tuple[int, str]]:
    taken: set[tuple[int, str]] = set()
    if not isinstance(rows, list):
        raise ReadError("resposta de search_rule sem a lista de regras")
    for rule in rows:
        if not isinstance(rule, dict) or str(rule.get("interface", "")).lower() != interface.lower():
            continue
        target = str(rule.get("destination.port", "")).strip()
        if not target:
            continue
        name = str(rule.get("descr", "")) or str(rule.get("uuid", "?"))
        if _PORT_RE.fullmatch(target) or _RANGE_RE.fullmatch(target):
            ports = _expand_ports(target, name)
        else:
            ports = _ports_of_alias(rule.get("alias_meta_destination.port"), name)
        for proto in _protocols_of(str(rule.get("protocol", ""))):
            taken |= {(p, proto) for p in ports}
    return taken


# --- backend ----------------------------------------------------------------------------

class Opnsense:
    def __init__(self, cliente: Client, interface: str = "wan"):
        if not re.fullmatch(r"[A-Za-z0-9_]{1,32}", interface):
            raise ValueError("nome de interface invalido")
        self._c = cliente
        self._interface = interface

    def _api(self, method: str, path: str, action: str, body: object = None) -> Response:
        response = self._c.request(method, "/api/firewall" + path, json_body=body)
        if not response.ok:
            raise OpnsenseError(f"{action}: HTTP {response.status}")
        return response

    def _rules(self) -> list:
        response = self._api("POST", "/d_nat/search_rule", "ler regras", _SEARCH_ARGS)
        lines = response.json.get("rows") if isinstance(response.json, dict) else None
        if not isinstance(lines, list):
            raise ReadError("resposta de search_rule sem a lista de regras")
        return lines

    def external_ports(self) -> set[tuple[int, str]]:
        return busy_ports(self._rules(), self._interface)

    def _uuids_of_instance(self, handle: str) -> list[str]:
        description = instance_description(handle)
        found = []
        for rule in self._rules():
            if isinstance(rule, dict) and rule.get("descr") == description:
                uuid = str(rule.get("uuid", ""))
                if _UUID_RE.fullmatch(uuid):
                    found.append(uuid)
        return found

    def open_ports(self, handle: str, ip: str, ports: Sequence[AllocatedPort]) -> None:
        target = str(ipaddress.IPv4Address(ip))
        self.close_ports(handle)  # idempotent: starting over does not leave a duplicate rule
        created_ones: list[str] = []
        try:
            for port in ports:
                created_ones.append(self._create_rule(handle, target, port))
            self._apply()
        except Exception:
            self._delete(created_ones)
            raise

    def _create_rule(self, handle: str, target: str, port: AllocatedPort) -> str:
        if port.proto not in ("tcp", "udp") or not 1 <= port.number <= MAX_PORT:
            raise OpnsenseError(f"porta invalida: {port}")
        rule = {"rule": {
            "disabled": "0", "interface": self._interface, "protocol": port.proto,
            "ipprotocol": "inet", "destination": {"network": "wanip", "port": str(port.number)},
            "target": target, "local-port": str(port.number),
            "descr": instance_description(handle), "pass": "pass",
        }}
        response = self._api("POST", "/d_nat/add_rule", f"criar regra {port}", rule)
        data = response.json if isinstance(response.json, dict) else {}
        uuid = str(data.get("uuid", ""))
        if data.get("result") != "saved" or not _UUID_RE.fullmatch(uuid):
            raise OpnsenseError(f"criar regra {port}: o OPNsense recusou ({_validations(data)})")
        return uuid

    def close_ports(self, handle: str) -> None:
        uuids = self._uuids_of_instance(handle)
        if not uuids:
            return
        self._delete(uuids)
        self._apply()

    def _delete(self, uuids: Sequence[str]) -> None:
        errors = 0
        for uuid in uuids:
            try:
                self._api("POST", f"/d_nat/del_rule/{uuid}", "apagar regra", {})
            except OpnsenseError:
                errors += 1
        if errors:
            raise OpnsenseError(f"nao consegui apagar {errors} regra(s); confira no OPNsense")

    def _apply(self) -> None:
        response = self._api("POST", "/filter/apply", "aplicar", {})
        state_dir = response.json.get("status", "") if isinstance(response.json, dict) else ""
        if not str(state_dir).strip().upper().startswith("OK"):
            raise OpnsenseError("aplicar: o OPNsense nao confirmou")

    def reachable(self) -> bool:
        try:
            return self._c.request("POST", "/api/firewall/d_nat/search_rule",
                                      json_body={"current": 1, "rowCount": 1},
                                      timeout=SONDA_TIMEOUT).ok
        except Exception:  # noqa: BLE001
            return False


def _validations(data: dict) -> str:
    checks = data.get("validations")
    if isinstance(checks, dict) and checks:
        return "; ".join(f"{field}: {text}" for field, text in list(checks.items())[:3])
    return str(data.get("result", "sem detalhe"))[:100]
