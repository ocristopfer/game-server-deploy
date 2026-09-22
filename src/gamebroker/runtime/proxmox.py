"""Backend Proxmox: cria, liga, para e destroi CTs do pool do broker pela API REST.

Tudo aqui foi validado contra um Proxmox VE 9.2 real (spike da Fase 0). Os fatos que
moldam o codigo:

- `tags` NA CRIACAO exige VM.Config.Options em /vms/<id>, que ainda nao existe e nao herda
  do pool: a tag e gravada DEPOIS, com o CT ja no pool. E se nem isso der certo nao e
  fatal - a identidade do CT do broker e o pool (`pertence_ao_broker`), nao a tag.
- `keyctl=1` so o root@pam pode. So `nesting=1` e enviado.
- Tarefa que termina em `WARNINGS: n` e sucesso (ex.: "Systemd 257: pode precisar de nesting").
- O motivo de um 403 vem na linha de status HTTP (o `conexao.Cliente` ja o devolve).
"""
from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote

from gamebroker.integrations.http_client import Cliente, Resposta
from gamebroker.runtime.base import EspecificacaoDeCt

TAG_DO_BROKER = "gamepanel-broker"
_NOME_RE = re.compile(r"[A-Za-z0-9._-]{1,64}", re.ASCII)
_VOLID_RE = re.compile(r"[A-Za-z0-9._-]+:vztmpl/[A-Za-z0-9._+-]+", re.ASCII)
_IP_DE_REDE_RE = re.compile(r"ip=(\d{1,3}(?:\.\d{1,3}){3})")
ERRO_MAX = 200
# Sonda de saude: um servico que nao responde em poucos segundos ja e a resposta.
SONDA_TIMEOUT = 5.0


class ErroDoProxmox(RuntimeError):
    """Falha ao falar com o Proxmox. A mensagem nao carrega token nem cabecalho."""


@dataclass(frozen=True)
class ConfigProxmox:
    node: str
    pool: str
    storage: str
    template: str
    bridge: str
    gateway: str
    chaves_ssh: tuple[str, ...]
    prefixo: int = 24
    intervalo: float = 2.0
    tentativas: int = 150

    def __post_init__(self) -> None:
        for campo in (self.node, self.pool, self.storage, self.bridge):
            if not _NOME_RE.fullmatch(campo):
                raise ValueError(f"nome invalido na config do Proxmox: {campo!r}")
        if not _VOLID_RE.fullmatch(self.template):
            raise ValueError("template deve ser <storage>:vztmpl/<arquivo>")
        if not self.chaves_ssh or not all(k.startswith("ssh-") and "\n" not in k for k in self.chaves_ssh):
            raise ValueError("chaves_ssh: informe ao menos uma chave publica (uma por item, sem quebra de linha)")


class Proxmox:
    def __init__(self, cliente: Cliente, config: ConfigProxmox,
                 dormir: Callable[[float], None] = time.sleep):
        self._c = cliente
        self._cfg = config
        self._dormir = dormir

    # --- chamadas -----------------------------------------------------------

    def _api(self, metodo: str, caminho: str, acao: str, *, form: dict | None = None) -> Resposta:
        resposta = self._c.requisitar(metodo, "/api2/json" + caminho, form=form)
        if not resposta.ok:
            raise ErroDoProxmox(f"{acao}: HTTP {resposta.status} {_curto(resposta.texto)}")
        return resposta

    @staticmethod
    def _dados(resposta: Resposta) -> object:
        return resposta.json.get("data") if isinstance(resposta.json, dict) else None

    def _tarefa(self, resposta: Resposta, acao: str) -> None:
        upid = self._dados(resposta)
        if not isinstance(upid, str):
            raise ErroDoProxmox(f"{acao}: o Proxmox nao devolveu o identificador da tarefa")
        codificado = quote(upid, safe="")
        for _ in range(self._cfg.tentativas):
            estado = self._dados(self._api("GET", f"/nodes/{self._cfg.node}/tasks/{codificado}/status",
                                           f"{acao} (estado da tarefa)"))
            if isinstance(estado, dict) and estado.get("status") == "stopped":
                saida = str(estado.get("exitstatus", ""))
                if saida == "OK" or saida.startswith("WARNINGS"):
                    return
                raise ErroDoProxmox(f"{acao}: a tarefa terminou com '{_curto(saida)}'{self._fim_do_log(codificado)}")
            self._dormir(self._cfg.intervalo)
        raise ErroDoProxmox(f"{acao}: a tarefa excedeu o tempo")

    def _fim_do_log(self, upid_codificado: str) -> str:
        resposta = self._c.requisitar(
            "GET", f"/api2/json/nodes/{self._cfg.node}/tasks/{upid_codificado}/log?limit=20")
        linhas = self._dados(resposta) if resposta.ok else None
        if not isinstance(linhas, list) or not linhas:
            return ""
        ultimas = " | ".join(str(item.get("t", "")) for item in linhas[-3:] if isinstance(item, dict))
        return f" ({_curto(ultimas)})"

    # --- leitura ---------------------------------------------------------------

    def ctids_e_ips(self) -> tuple[set[int], set[str]]:
        """CTIDs e IPs que o token enxerga. Com a role so no pool isso e SO o pool; para
        ver os CTs de fora, o token precisa de VM.Audit em /vms (opcional)."""
        itens = self._dados(self._api("GET", "/cluster/resources?type=vm", "listar CTs"))
        ctids: set[int] = set()
        ips: set[str] = set()
        for item in itens if isinstance(itens, list) else []:
            if not isinstance(item, dict) or not isinstance(item.get("vmid"), int):
                continue
            ctids.add(item["vmid"])
            if item.get("type") == "lxc":
                ips |= self._ips_do_ct(item["vmid"])
        return ctids, ips

    def _ips_do_ct(self, ctid: int) -> set[str]:
        resposta = self._c.requisitar("GET", f"/api2/json/nodes/{self._cfg.node}/lxc/{ctid}/config")
        config = self._dados(resposta) if resposta.ok else None
        if not isinstance(config, dict):
            return set()
        achados: set[str] = set()
        for chave, valor in config.items():
            if re.fullmatch(r"net\d+", str(chave)) and isinstance(valor, str):
                achados.update(_IP_DE_REDE_RE.findall(valor))
        return achados

    def pertence_ao_broker(self, ctid: int) -> bool:
        """Identidade = ser membro do pool do broker. Nao depende da tag."""
        dados = self._dados(self._c.requisitar("GET", f"/api2/json/pools/{self._cfg.pool}"))
        membros = dados.get("members", []) if isinstance(dados, dict) else []
        return any(isinstance(m, dict) and m.get("vmid") == ctid and m.get("type") == "lxc" for m in membros)

    def acessivel(self) -> bool:
        try:
            return self._c.requisitar("GET", "/api2/json/version", timeout=SONDA_TIMEOUT).ok
        except Exception:  # noqa: BLE001
            return False

    # --- escrita ------------------------------------------------------------------

    def criar_ct(self, especificacao: EspecificacaoDeCt) -> None:
        cfg = self._cfg
        corpo = {
            "vmid": especificacao.ctid, "hostname": especificacao.hostname,
            "ostemplate": cfg.template, "rootfs": f"{cfg.storage}:{especificacao.disco_gb}",
            "memory": especificacao.memoria_mb, "swap": 0, "cores": especificacao.cores,
            "unprivileged": 1, "features": "nesting=1", "pool": cfg.pool, "start": 0, "onboot": 1,
            "net0": (f"name=eth0,bridge={cfg.bridge},ip={especificacao.ip}/{cfg.prefixo},"
                     f"gw={cfg.gateway},type=veth"),
            "ssh-public-keys": "\n".join(cfg.chaves_ssh),
        }
        self._tarefa(self._api("POST", f"/nodes/{cfg.node}/lxc", "criar CT", form=corpo), "criar CT")
        try:
            self._api("PUT", f"/nodes/{cfg.node}/lxc/{especificacao.ctid}/config", "gravar a tag",
                      form={"tags": TAG_DO_BROKER})
        except ErroDoProxmox:
            # Tag e conforto (aparece na tela do Proxmox); a identidade e o pool.
            pass

    def iniciar(self, ctid: int) -> None:
        self._tarefa(self._api("POST", f"/nodes/{self._cfg.node}/lxc/{ctid}/status/start",
                               "iniciar CT"), "iniciar CT")

    def parar(self, ctid: int) -> None:
        self._exigir_no_pool(ctid)
        self._tarefa(self._api("POST", f"/nodes/{self._cfg.node}/lxc/{ctid}/status/shutdown",
                               "parar CT", form={"forceStop": 1, "timeout": 30}), "parar CT")

    def destruir(self, ctid: int) -> None:
        self._exigir_no_pool(ctid)
        estado = self._dados(self._api("GET", f"/nodes/{self._cfg.node}/lxc/{ctid}/status/current",
                                       "ler estado do CT"))
        if isinstance(estado, dict) and estado.get("status") == "running":
            self.parar(ctid)
        self._tarefa(self._api(
            "DELETE", f"/nodes/{self._cfg.node}/lxc/{ctid}?purge=1&destroy-unreferenced-disks=1",
            "destruir CT"), "destruir CT")

    def _exigir_no_pool(self, ctid: int) -> None:
        # O token so tem permissao no pool, mas a checagem aqui vale por conta propria: se
        # alguem alargar a role um dia, o broker continua so mexendo no que e dele.
        if not self.pertence_ao_broker(ctid):
            raise ErroDoProxmox(f"o CT {ctid} nao esta no pool '{self._cfg.pool}'; nada foi alterado")


def _curto(texto: str) -> str:
    limpo = " ".join(str(texto).split())
    return limpo if len(limpo) <= ERRO_MAX else limpo[:ERRO_MAX] + "..."
