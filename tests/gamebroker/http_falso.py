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

Tratador = Callable[[str, str, dict, dict, dict], tuple]


class ServidorFalso:
    """Sobe em 127.0.0.1:<porta livre>. `tratador(metodo, caminho, query, corpo, cabecalhos)`
    devolve `(status, corpo, motivo)`; corpo dict/list vira JSON, texto vai como esta."""

    def __init__(self, tratador: Tratador):
        self.requisicoes: list[tuple[str, str, dict]] = []
        servidor = self
        self.ultimo_corpo: dict = {}

        class Manipulador(BaseHTTPRequestHandler):
            def _tratar(self) -> None:
                partes = urlsplit(self.path)
                tamanho = int(self.headers.get("Content-Length") or 0)
                bruto = self.rfile.read(tamanho).decode() if tamanho else ""
                tipo = self.headers.get("Content-Type", "")
                if "json" in tipo and bruto:
                    corpo = json.loads(bruto)
                else:
                    corpo = {k: v[0] for k, v in parse_qs(bruto).items()}
                cabecalhos = {k.lower(): v for k, v in self.headers.items()}
                servidor.requisicoes.append((self.command, unquote(partes.path), corpo))
                servidor.ultimo_corpo = corpo
                query = {k: v[0] for k, v in parse_qs(partes.query).items()}
                status, resposta, *resto = tratador(self.command, unquote(partes.path), query, corpo, cabecalhos)
                reason = resto[0] if resto else None
                dados = resposta if isinstance(resposta, str) else json.dumps(resposta)
                self.send_response(status, reason)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(dados.encode())))
                self.end_headers()
                self.wfile.write(dados.encode())

            do_GET = do_POST = do_PUT = do_DELETE = _tratar

            def log_message(self, *_args) -> None:
                pass

        class Silencioso(ThreadingHTTPServer):
            def handle_error(self, request, client_address) -> None:
                # O cliente fecha a conexao no meio de uma resposta de proposito em alguns
                # testes (resposta gigante); o traceback do servidor so confundiria o log.
                return None

        self._http = Silencioso(("127.0.0.1", 0), Manipulador)
        self._fio = threading.Thread(target=self._http.serve_forever, daemon=True)
        self._fio.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._http.server_address[1]}"

    def parar(self) -> None:
        self._http.shutdown()
        self._http.server_close()


# ---------------------------------------------------------------------------------
# Proxmox
# ---------------------------------------------------------------------------------

NAO_ENCONTRADO = "Not Found"
TOKEN_PVE = "broker@pve!broker=00000000-0000-0000-0000-000000000000"


class PveFalso:
    def __init__(self, node: str = "pve", pool: str = "games"):
        self.node = node
        self.pool = pool
        self.cts: dict[int, dict] = {}
        self.tarefas: dict[str, dict] = {}
        self.rodadas_ate_parar = 0
        self.saida_da_criacao = "WARNINGS: 1"
        self.falha_na_tag = False
        self.autenticar = True

    def externo(self, vmid: int, net0: str = "", name: str = "de-fora") -> None:
        """CT que existe no Proxmox mas NAO esta no pool do broker."""
        self.cts[vmid] = {"hostname": name, "net0": net0, "features": "", "tags": "",
                          "status": "stopped", "pool": None}

    def _upid(self, tipo: str, vmid: int, saida: str = "OK", log: tuple[str, ...] = ()) -> str:
        upid = f"UPID:{self.node}:{len(self.tarefas):08X}:0001:ABCD:{tipo}:{vmid}:broker@pve!broker:"
        self.tarefas[upid] = {"saida": saida, "rodadas": self.rodadas_ate_parar, "log": list(log)}
        return upid

    def tratar(self, metodo: str, caminho: str, _query: dict, corpo: dict, cabecalhos: dict) -> tuple:  # NOSONAR - contrato do Tratador: (status, corpo[, motivo])
        if self.autenticar and cabecalhos.get("authorization") != f"PVEAPIToken={TOKEN_PVE}":
            return 401, "", "No ticket"
        rota = caminho.removeprefix("/api2/json")
        node = f"/nodes/{self.node}"
        if rota == "/version":
            return 200, {"data": {"version": "9.2.20"}}
        if rota == "/cluster/resources":
            return 200, {"data": [{"vmid": v, "type": "lxc", "status": c["status"], "name": c["hostname"]}
                                  for v, c in self.cts.items() if c["pool"] == self.pool]}
        if rota == f"/pools/{self.pool}":
            return 200, {"data": {"members": [{"vmid": v, "type": "lxc", "id": f"lxc/{v}"}
                                              for v, c in self.cts.items() if c["pool"] == self.pool]}}
        if rota == f"{node}/lxc" and metodo == "POST":
            return self._criar(corpo)
        if rota.startswith(f"{node}/tasks/"):
            return self._tarefa(rota.removeprefix(f"{node}/tasks/"))
        achado = re.fullmatch(rf"{re.escape(node)}/lxc/(\d+)(/.*)?", rota)
        if achado:
            return self._ct(metodo, int(achado.group(1)), achado.group(2) or "", corpo)
        return 404, "", NAO_ENCONTRADO

    def _criar(self, corpo: dict) -> tuple:  # NOSONAR - contrato do Tratador: (status, corpo[, motivo])
        vmid = int(corpo["vmid"])
        if "tags" in corpo:
            return 403, "", f"Permission check failed (/vms/{vmid}, VM.Config.Options)"
        recursos = [p.split("=")[0] for p in corpo.get("features", "").split(",") if p]
        if any(r != "nesting" for r in recursos):
            return 403, "", "Permission check failed (changing feature flags (except nesting) is only allowed for root@pam)"
        if vmid in self.cts:
            return 500, "", f"CT {vmid} already exists"
        if corpo.get("pool") != self.pool:
            return 403, "", "Permission check failed (/vms/%d, VM.Allocate)" % vmid
        self.cts[vmid] = {"hostname": corpo["hostname"], "net0": corpo["net0"],
                          "features": corpo.get("features", ""), "tags": "", "status": "stopped",
                          "pool": self.pool, "chaves": corpo.get("ssh-public-keys", ""),
                          "rootfs": corpo["rootfs"], "memory": corpo["memory"], "cores": corpo["cores"],
                          "unprivileged": corpo["unprivileged"], "ostemplate": corpo["ostemplate"]}
        return 200, {"data": self._upid("vzcreate", vmid, self.saida_da_criacao,
                                        ("Creating SSH host key", "WARN: Systemd 257 detected"))}

    def _tarefa(self, resto: str) -> tuple:  # NOSONAR - contrato do Tratador: (status, corpo[, motivo])
        upid, _, acao = resto.rpartition("/")
        tarefa = self.tarefas.get(upid)
        if tarefa is None:
            return 500, "", "no such task"
        if acao == "log":
            return 200, {"data": [{"n": i, "t": t} for i, t in enumerate(tarefa["log"])]}
        if tarefa["rodadas"] > 0:
            tarefa["rodadas"] -= 1
            return 200, {"data": {"status": "running"}}
        return 200, {"data": {"status": "stopped", "exitstatus": tarefa["saida"]}}

    def _ct(self, metodo: str, vmid: int, sufixo: str, corpo: dict) -> tuple:  # NOSONAR - contrato do Tratador: (status, corpo[, motivo])
        ct = self.cts.get(vmid)
        if ct is None:
            return 500, "", f"Configuration file 'nodes/{self.node}/lxc/{vmid}.conf' does not exist"
        if sufixo == "/config" and metodo == "GET":
            return 200, {"data": {"hostname": ct["hostname"], "net0": ct["net0"],
                                  "features": ct["features"], "tags": ct["tags"]}}
        if sufixo == "/config" and metodo == "PUT":
            if self.falha_na_tag:
                return 403, "", f"Permission check failed (/vms/{vmid}, VM.Config.Options)"
            ct["tags"] = corpo.get("tags", "")
            return 200, {"data": None}
        if sufixo == "/status/current":
            return 200, {"data": {"status": ct["status"]}}
        if sufixo == "/status/start":
            ct["status"] = "running"
            return 200, {"data": self._upid("vzstart", vmid)}
        if sufixo == "/status/shutdown":
            ct["status"] = "stopped"
            return 200, {"data": self._upid("vzshutdown", vmid)}
        if sufixo == "" and metodo == "DELETE":
            if ct["status"] == "running":
                return 500, "", "CT is running - destroy failed"
            del self.cts[vmid]
            return 200, {"data": self._upid("vzdestroy", vmid)}
        return 404, "", NAO_ENCONTRADO


# ---------------------------------------------------------------------------------
# OPNsense
# ---------------------------------------------------------------------------------

KEY_OPN = "chave-de-teste"
SECRET_OPN = "segredo-de-teste"


def resumo_de_alias(descricao: str, ports: list[str]) -> str:
    """O texto HTML que o d_nat/search_rule real devolve em alias_meta_destination.port."""
    return f"<strong>{descricao}</strong><br/>" + "<br/>".join(ports)


class OpnsenseHttpFalso:
    def __init__(self):
        self.regras: dict[str, dict] = {}
        self.aplicacoes = 0
        self.apply_permitido = True
        self.falhar_no_add_numero: int | None = None
        self._adds = 0

    def regra_existente(self, descr: str, porta: str, protocolo: str = "udp", interface: str = "wan",
                        alvo: str = "192.168.2.21",  # NOSONAR - IP de fixture
                        desativada: bool = False,
                        alias: list[str] | None = None, resumo: str | None = None) -> str:
        """Regra que o usuario ja tinha. `alias` = portas do alias quando `porta` e um nome."""
        uuid = str(uuidlib.uuid4())
        linha = {"uuid": uuid, "descr": descr, "interface": interface, "protocol": protocolo,
                 "destination.port": porta, "target": alvo, "local-port": porta,
                 "disabled": "1" if desativada else "0", "pass": "pass", "associated-rule-id": ""}
        if alias is not None or resumo is not None:
            linha["alias_meta_destination.port"] = [{
                "value": porta, "isAlias": True,
                "summary": resumo if resumo is not None else resumo_de_alias(f"UDP -> {alvo}", alias or [])}]
        self.regras[uuid] = linha
        return uuid

    def tratar(self, _metodo: str, caminho: str, _query: dict, corpo: dict, cabecalhos: dict) -> tuple:  # NOSONAR - contrato do Tratador: (status, corpo[, motivo])
        esperado = "Basic " + base64.b64encode(f"{KEY_OPN}:{SECRET_OPN}".encode()).decode()
        if cabecalhos.get("authorization") != esperado:
            return 401, {"status": 401, "message": "Authentication Failed"}, "Unauthorized"
        rota = caminho.removeprefix("/api/firewall")
        if rota == "/d_nat/search_rule":
            linhas = list(self.regras.values())
            return 200, {"total": len(linhas), "rowCount": len(linhas), "current": 1, "rows": linhas}
        if rota == "/d_nat/add_rule":
            return self._adicionar(corpo)
        if rota.startswith("/d_nat/del_rule/"):
            uuid = rota.rsplit("/", 1)[1]
            if uuid not in self.regras:
                return 200, {"result": "not found"}
            del self.regras[uuid]
            return 200, {"result": "deleted"}
        if rota == "/filter/apply":
            if not self.apply_permitido:
                return 403, {"status": 403, "message": "Forbidden"}, "Forbidden"
            self.aplicacoes += 1
            return 200, {"status": "OK\n\n"}
        return 404, {"status": 404, "message": NAO_ENCONTRADO}, NAO_ENCONTRADO

    def _adicionar(self, corpo: dict) -> tuple:  # NOSONAR - contrato do Tratador: (status, corpo[, motivo])
        self._adds += 1
        if self.falhar_no_add_numero == self._adds:
            return 200, {"result": "failed", "validations": {"rule.target": "Invalid target"}}
        regra = corpo.get("rule", {})
        uuid = str(uuidlib.uuid4())
        self.regras[uuid] = {
            "uuid": uuid, "descr": regra.get("descr", ""), "interface": regra.get("interface", ""),
            "protocol": regra.get("protocol", ""), "destination.port": regra.get("destination", {}).get("port", ""),
            "target": regra.get("target", ""), "local-port": regra.get("local-port", ""),
            "disabled": regra.get("disabled", "0"), "pass": regra.get("pass", ""), "associated-rule-id": ""}
        return 200, {"result": "saved", "uuid": uuid}
