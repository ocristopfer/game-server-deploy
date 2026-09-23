"""Servidores HTTP falsos de Proxmox e OPNsense, para testar os backends reais sem rede.

Nao sao mocks "de mentira": reproduzem as REGRAS que o spike descobriu nos servidores
verdadeiros (tag na criacao e keyctl sao 403, `WARNINGS` e sucesso, alias de porta so
aparece no resumo em HTML). Se um backend voltar a mandar `tags` na criacao, o falso
responde 403 como o Proxmox real - e o teste quebra.
"""
from __future__ import annotations

import base64
import json
import re
import threading
import uuid as uuidlib
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

Handler = Callable[[str, str, dict, dict, dict], tuple]


class FakeServer:
    """Sobe em 127.0.0.1:<porta livre>. `tratador(metodo, caminho, query, corpo, cabecalhos)`
    devolve `(status, corpo, motivo)`; corpo dict/list vira JSON, texto vai como esta."""

    def __init__(self, handler: Handler):
        self.requests_seen: list[tuple[str, str, dict]] = []
        server = self
        self.last_body: dict = {}

        class RequestHandler(BaseHTTPRequestHandler):
            def _handle(self) -> None:
                parts = urlsplit(self.path)
                size = int(self.headers.get("Content-Length") or 0)
                raw_text = self.rfile.read(size).decode() if size else ""
                kind = self.headers.get("Content-Type", "")
                if "json" in kind and raw_text:
                    body = json.loads(raw_text)
                else:
                    body = {k: v[0] for k, v in parse_qs(raw_text).items()}
                headers = {k.lower(): v for k, v in self.headers.items()}
                server.requests_seen.append((self.command, unquote(parts.path), body))
                server.last_body = body
                query = {k: v[0] for k, v in parse_qs(parts.query).items()}
                status, response, *rest = handler(self.command, unquote(parts.path), query, body, headers)
                reason = rest[0] if rest else None
                data = response if isinstance(response, str) else json.dumps(response)
                self.send_response(status, reason)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data.encode())))
                self.end_headers()
                self.wfile.write(data.encode())

            do_GET = do_POST = do_PUT = do_DELETE = _handle

            def log_message(self, *_args) -> None:
                pass

        class Quiet(ThreadingHTTPServer):
            def handle_error(self, request, client_address) -> None:
                # O cliente fecha a conexao no meio de uma resposta de proposito em alguns
                # testes (resposta gigante); o traceback do servidor so confundiria o log.
                return None

        self._http = Quiet(("127.0.0.1", 0), RequestHandler)
        self._thread = threading.Thread(target=self._http.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._http.server_address[1]}"

    def stop(self) -> None:
        self._http.shutdown()
        self._http.server_close()


# ---------------------------------------------------------------------------------
# Proxmox
# ---------------------------------------------------------------------------------

NOT_FOUND = "Not Found"
TOKEN_PVE = "broker@pve!broker=00000000-0000-0000-0000-000000000000"


class FakePve:
    def __init__(self, node: str = "pve", pool: str = "games"):
        self.node = node
        self.pool = pool
        self.cts: dict[int, dict] = {}
        self.tasks: dict[str, dict] = {}
        self.rounds_until_stop = 0
        self.creation_output = "WARNINGS: 1"
        self.fail_on_tag = False
        self.authenticate = True

    def external(self, vmid: int, net0: str = "", name: str = "de-fora") -> None:
        """CT que existe no Proxmox mas NAO esta no pool do broker."""
        self.cts[vmid] = {"hostname": name, "net0": net0, "features": "", "tags": "",
                          "status": "stopped", "pool": None}

    def _upid(self, kind: str, vmid: int, output: str = "OK", log: tuple[str, ...] = ()) -> str:
        upid = f"UPID:{self.node}:{len(self.tasks):08X}:0001:ABCD:{kind}:{vmid}:broker@pve!broker:"
        self.tasks[upid] = {"saida": output, "rodadas": self.rounds_until_stop, "log": list(log)}
        return upid

    def handle(self, method: str, path: str, _query: dict, body: dict, headers: dict) -> tuple:  # NOSONAR - contrato do Handler: (status, corpo[, motivo])
        if self.authenticate and headers.get("authorization") != f"PVEAPIToken={TOKEN_PVE}":
            return 401, "", "No ticket"
        route = path.removeprefix("/api2/json")
        node = f"/nodes/{self.node}"
        if route == "/version":
            return 200, {"data": {"version": "9.2.20"}}
        if route == "/cluster/resources":
            return 200, {"data": [{"vmid": v, "type": "lxc", "status": c["status"], "name": c["hostname"]}
                                  for v, c in self.cts.items() if c["pool"] == self.pool]}
        if route == f"/pools/{self.pool}":
            return 200, {"data": {"members": [{"vmid": v, "type": "lxc", "id": f"lxc/{v}"}
                                              for v, c in self.cts.items() if c["pool"] == self.pool]}}
        if route == f"{node}/lxc" and method == "POST":
            return self._create(body)
        if route.startswith(f"{node}/tasks/"):
            return self._task(route.removeprefix(f"{node}/tasks/"))
        found = re.fullmatch(rf"{re.escape(node)}/lxc/(\d+)(/.*)?", route)
        if found:
            return self._ct(method, int(found.group(1)), found.group(2) or "", body)
        return 404, "", NOT_FOUND

    def _create(self, body: dict) -> tuple:  # NOSONAR - contrato do Handler: (status, corpo[, motivo])
        vmid = int(body["vmid"])
        if "tags" in body:
            return 403, "", f"Permission check failed (/vms/{vmid}, VM.Config.Options)"
        resources = [p.split("=")[0] for p in body.get("features", "").split(",") if p]
        if any(r != "nesting" for r in resources):
            return 403, "", "Permission check failed (changing feature flags (except nesting) is only allowed for root@pam)"
        if vmid in self.cts:
            return 500, "", f"CT {vmid} already exists"
        if body.get("pool") != self.pool:
            return 403, "", "Permission check failed (/vms/%d, VM.Allocate)" % vmid
        self.cts[vmid] = {"hostname": body["hostname"], "net0": body["net0"],
                          "features": body.get("features", ""), "tags": "", "status": "stopped",
                          "pool": self.pool, "keys": body.get("ssh-public-keys", ""),
                          "rootfs": body["rootfs"], "memory": body["memory"], "cores": body["cores"],
                          "unprivileged": body["unprivileged"], "ostemplate": body["ostemplate"]}
        return 200, {"data": self._upid("vzcreate", vmid, self.creation_output,
                                        ("Creating SSH host key", "WARN: Systemd 257 detected"))}

    def _task(self, rest: str) -> tuple:  # NOSONAR - contrato do Handler: (status, corpo[, motivo])
        upid, _, action = rest.rpartition("/")
        task = self.tasks.get(upid)
        if task is None:
            return 500, "", "no such task"
        if action == "log":
            return 200, {"data": [{"n": i, "t": t} for i, t in enumerate(task["log"])]}
        if task["rodadas"] > 0:
            task["rodadas"] -= 1
            return 200, {"data": {"status": "running"}}
        return 200, {"data": {"status": "stopped", "exitstatus": task["saida"]}}

    def _ct(self, method: str, vmid: int, suffix: str, body: dict) -> tuple:  # NOSONAR - contrato do Handler: (status, corpo[, motivo])
        ct = self.cts.get(vmid)
        if ct is None:
            return 500, "", f"Configuration file 'nodes/{self.node}/lxc/{vmid}.conf' does not exist"
        if suffix == "/config" and method == "GET":
            return 200, {"data": {"hostname": ct["hostname"], "net0": ct["net0"],
                                  "features": ct["features"], "tags": ct["tags"]}}
        if suffix == "/config" and method == "PUT":
            if self.fail_on_tag:
                return 403, "", f"Permission check failed (/vms/{vmid}, VM.Config.Options)"
            ct["tags"] = body.get("tags", "")
            return 200, {"data": None}
        if suffix == "/status/current":
            return 200, {"data": {"status": ct["status"]}}
        if suffix == "/status/start":
            ct["status"] = "running"
            return 200, {"data": self._upid("vzstart", vmid)}
        if suffix == "/status/shutdown":
            ct["status"] = "stopped"
            return 200, {"data": self._upid("vzshutdown", vmid)}
        if suffix == "" and method == "DELETE":
            if ct["status"] == "running":
                return 500, "", "CT is running - destroy failed"
            del self.cts[vmid]
            return 200, {"data": self._upid("vzdestroy", vmid)}
        return 404, "", NOT_FOUND


# ---------------------------------------------------------------------------------
# OPNsense
# ---------------------------------------------------------------------------------

KEY_OPN = "chave-de-teste"
SECRET_OPN = "segredo-de-teste"


def alias_summary(descricao: str, ports: list[str]) -> str:
    """O texto HTML que o d_nat/search_rule real devolve em alias_meta_destination.port."""
    return f"<strong>{descricao}</strong><br/>" + "<br/>".join(ports)


class FakeOpnsenseHttp:
    def __init__(self):
        self.rules: dict[str, dict] = {}
        self.applies = 0
        self.apply_permitido = True
        self.fail_on_add_number: int | None = None
        self._adds = 0

    def existing_rule(self, descr: str, port: str, protocol: str = "udp", interface: str = "wan",
                        target: str = "192.168.2.21",  # NOSONAR - IP de fixture
                        disabled: bool = False,
                        alias: list[str] | None = None, summary_text: str | None = None) -> str:
        """Regra que o usuario ja tinha. `alias` = portas do alias quando `porta` e um nome."""
        uuid = str(uuidlib.uuid4())
        line = {"uuid": uuid, "descr": descr, "interface": interface, "protocol": protocol,
                 "destination.port": port, "target": target, "local-port": port,
                 "disabled": "1" if disabled else "0", "pass": "pass", "associated-rule-id": ""}
        if alias is not None or summary_text is not None:
            line["alias_meta_destination.port"] = [{
                "value": port, "isAlias": True,
                "summary": summary_text if summary_text is not None
                           else alias_summary(f"UDP -> {target}", alias or [])}]
        self.rules[uuid] = line
        return uuid

    def handle(self, _method: str, path: str, _query: dict, body: dict, headers: dict) -> tuple:  # NOSONAR - contrato do Handler: (status, corpo[, motivo])
        expected = "Basic " + base64.b64encode(f"{KEY_OPN}:{SECRET_OPN}".encode()).decode()
        if headers.get("authorization") != expected:
            return 401, {"status": 401, "message": "Authentication Failed"}, "Unauthorized"
        route = path.removeprefix("/api/firewall")
        if route == "/d_nat/search_rule":
            lines = list(self.rules.values())
            return 200, {"total": len(lines), "rowCount": len(lines), "current": 1, "rows": lines}
        if route == "/d_nat/add_rule":
            return self._add(body)
        if route.startswith("/d_nat/del_rule/"):
            uuid = route.rsplit("/", 1)[1]
            if uuid not in self.rules:
                return 200, {"result": "not found"}
            del self.rules[uuid]
            return 200, {"result": "deleted"}
        if route == "/filter/apply":
            if not self.apply_permitido:
                return 403, {"status": 403, "message": "Forbidden"}, "Forbidden"
            self.applies += 1
            return 200, {"status": "OK\n\n"}
        return 404, {"status": 404, "message": NOT_FOUND}, NOT_FOUND

    def _add(self, body: dict) -> tuple:  # NOSONAR - contrato do Handler: (status, corpo[, motivo])
        self._adds += 1
        if self.fail_on_add_number == self._adds:
            return 200, {"result": "failed", "validations": {"rule.target": "Invalid target"}}
        rule = body.get("rule", {})
        uuid = str(uuidlib.uuid4())
        self.rules[uuid] = {
            "uuid": uuid, "descr": rule.get("descr", ""), "interface": rule.get("interface", ""),
            "protocol": rule.get("protocol", ""), "destination.port": rule.get("destination", {}).get("port", ""),
            "target": rule.get("target", ""), "local-port": rule.get("local-port", ""),
            "disabled": rule.get("disabled", "0"), "pass": rule.get("pass", ""), "associated-rule-id": ""}
        return 200, {"result": "saved", "uuid": uuid}
