"""Backend OPNsense: abre e fecha redirects de porta (d_nat) do WAN.

Fatos validados num OPNsense 26.7.4 real (spike da Fase 0):

- As regras de jogo que ja existem usam ALIASES de porta (`JOGO_PALWORLD`...), nao numeros.
  `search_rule` traz o conteudo do alias em `alias_meta_destination.port`, num texto HTML
  (`<strong>descricao</strong><br/>8211<br/>27015`). E daqui que o broker descobre quais
  portas ja estao ocupadas - `alias/search_item` da 403 para a chave do broker.
- Se uma regra do WAN usa um formato que nao entendemos, o broker RECUSA abrir porta nova
  (`ErroDeLeitura`) em vez de supor que a porta esta livre: errar para o lado de nao abrir.
- Regra desativada continua contando como ocupada (o usuario liga e desliga as dele).
- `filter/apply` so e autorizado pelo privilegio "Firewall: Rules [new]".
- `pass=pass` grava e `associated-rule-id` fica vazio, igual as regras existentes.
"""
from __future__ import annotations

import ipaddress
import re
from collections.abc import Sequence

from .alocador import PortaAlocada
from .conexao import Cliente, Resposta

PREFIXO_DA_DESCRICAO = "gamepanel:"
LIMITE_DE_FAIXA = 5000
_UUID_RE = re.compile(r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}")
_PORTA_RE = re.compile(r"\d{1,5}")
_FAIXA_RE = re.compile(r"(\d{1,5})[-:](\d{1,5})")
_QUEBRA_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_BUSCA = {"current": 1, "rowCount": -1}


class ErroDoOpnsense(RuntimeError):
    """Falha ao falar com o OPNsense. A mensagem nao carrega chave nem segredo."""


class ErroDeLeitura(ErroDoOpnsense):
    """Regra existente que o broker nao soube interpretar: nao abre porta nova."""


def descricao_da_instancia(ctid: int) -> str:
    return f"{PREFIXO_DA_DESCRICAO}{int(ctid)}"


# --- leitura das portas ocupadas ---------------------------------------------------

def _numero(texto: str) -> int:
    valor = int(texto)
    if not 1 <= valor <= 65535:
        raise ValueError
    return valor


def _expandir(item: str, regra: str) -> set[int]:
    """`7660` ou `8000-8010` (ou `8000:8010`) -> conjunto de portas."""
    item = item.strip()
    try:
        if _PORTA_RE.fullmatch(item):
            return {_numero(item)}
        faixa = _FAIXA_RE.fullmatch(item)
        if faixa:
            inicio, fim = _numero(faixa.group(1)), _numero(faixa.group(2))
            if inicio <= fim and fim - inicio < LIMITE_DE_FAIXA:
                return set(range(inicio, fim + 1))
    except ValueError:
        pass
    raise ErroDeLeitura(f"regra '{regra}': nao entendi a porta {item!r}")


def _portas_do_alias(meta: object, regra: str) -> set[int]:
    if not isinstance(meta, list) or not meta:
        raise ErroDeLeitura(f"regra '{regra}': o alias de porta nao veio no resultado")
    portas: set[int] = set()
    for alias in meta:
        summary = alias.get("summary") if isinstance(alias, dict) else None
        if not isinstance(summary, str):
            raise ErroDeLeitura(f"regra '{regra}': alias sem conteudo legivel")
        lidas = 0
        for pedaco in _QUEBRA_RE.split(summary):
            pedaco = pedaco.strip()
            # O primeiro pedaco costuma ser a descricao do alias, em HTML: nao e porta.
            if not pedaco or "<" in pedaco or ">" in pedaco:
                continue
            portas |= _expandir(pedaco, regra)
            lidas += 1
        if lidas == 0:
            raise ErroDeLeitura(f"regra '{regra}': o alias nao lista nenhuma porta que eu entenda")
    return portas


def _protocolos(protocolo: str) -> tuple[str, ...]:
    # tcp/udp (ou qualquer coisa que nao seja so tcp ou so udp) ocupa os dois: errar por excesso.
    protocolo = protocolo.strip().lower()
    return (protocolo,) if protocolo in ("tcp", "udp") else ("tcp", "udp")


def portas_ocupadas(linhas: object, interface: str) -> set[tuple[int, str]]:
    ocupadas: set[tuple[int, str]] = set()
    if not isinstance(linhas, list):
        raise ErroDeLeitura("resposta de search_rule sem a lista de regras")
    for regra in linhas:
        if not isinstance(regra, dict) or str(regra.get("interface", "")).lower() != interface.lower():
            continue
        destino = str(regra.get("destination.port", "")).strip()
        if not destino:
            continue
        nome = str(regra.get("descr", "")) or str(regra.get("uuid", "?"))
        if _PORTA_RE.fullmatch(destino) or _FAIXA_RE.fullmatch(destino):
            portas = _expandir(destino, nome)
        else:
            portas = _portas_do_alias(regra.get("alias_meta_destination.port"), nome)
        for proto in _protocolos(str(regra.get("protocol", ""))):
            ocupadas |= {(p, proto) for p in portas}
    return ocupadas


# --- backend ----------------------------------------------------------------------------

class Opnsense:
    def __init__(self, cliente: Cliente, interface: str = "wan"):
        if not re.fullmatch(r"[A-Za-z0-9_]{1,32}", interface):
            raise ValueError("nome de interface invalido")
        self._c = cliente
        self._interface = interface

    def _api(self, metodo: str, caminho: str, acao: str, corpo: object = None) -> Resposta:
        resposta = self._c.requisitar(metodo, "/api/firewall" + caminho, json_corpo=corpo)
        if not resposta.ok:
            raise ErroDoOpnsense(f"{acao}: HTTP {resposta.status}")
        return resposta

    def _regras(self) -> list:
        resposta = self._api("POST", "/d_nat/search_rule", "ler regras", _BUSCA)
        linhas = resposta.json.get("rows") if isinstance(resposta.json, dict) else None
        if not isinstance(linhas, list):
            raise ErroDeLeitura("resposta de search_rule sem a lista de regras")
        return linhas

    def portas_externas(self) -> set[tuple[int, str]]:
        return portas_ocupadas(self._regras(), self._interface)

    def _uuids_da_instancia(self, ctid: int) -> list[str]:
        descricao = descricao_da_instancia(ctid)
        achados = []
        for regra in self._regras():
            if isinstance(regra, dict) and regra.get("descr") == descricao:
                uuid = str(regra.get("uuid", ""))
                if _UUID_RE.fullmatch(uuid):
                    achados.append(uuid)
        return achados

    def abrir(self, ctid: int, ip: str, portas: Sequence[PortaAlocada]) -> None:
        alvo = str(ipaddress.IPv4Address(ip))
        self.fechar(ctid)  # idempotente: recomecar nao deixa regra duplicada
        criadas: list[str] = []
        try:
            for porta in portas:
                criadas.append(self._criar_regra(ctid, alvo, porta))
            self._aplicar()
        except Exception:
            self._apagar(criadas)
            raise

    def _criar_regra(self, ctid: int, alvo: str, porta: PortaAlocada) -> str:
        if porta.proto not in ("tcp", "udp") or not 1 <= porta.numero <= 65535:
            raise ErroDoOpnsense(f"porta invalida: {porta}")
        regra = {"rule": {
            "disabled": "0", "interface": self._interface, "protocol": porta.proto,
            "ipprotocol": "inet", "destination": {"network": "wanip", "port": str(porta.numero)},
            "target": alvo, "local-port": str(porta.numero),
            "descr": descricao_da_instancia(ctid), "pass": "pass",
        }}
        resposta = self._api("POST", "/d_nat/add_rule", f"criar regra {porta}", regra)
        dados = resposta.json if isinstance(resposta.json, dict) else {}
        uuid = str(dados.get("uuid", ""))
        if dados.get("result") != "saved" or not _UUID_RE.fullmatch(uuid):
            raise ErroDoOpnsense(f"criar regra {porta}: o OPNsense recusou ({_validacoes(dados)})")
        return uuid

    def fechar(self, ctid: int) -> None:
        uuids = self._uuids_da_instancia(ctid)
        if not uuids:
            return
        self._apagar(uuids)
        self._aplicar()

    def _apagar(self, uuids: Sequence[str]) -> None:
        erros = 0
        for uuid in uuids:
            try:
                self._api("POST", f"/d_nat/del_rule/{uuid}", "apagar regra", {})
            except ErroDoOpnsense:
                erros += 1
        if erros:
            raise ErroDoOpnsense(f"nao consegui apagar {erros} regra(s); confira no OPNsense")

    def _aplicar(self) -> None:
        resposta = self._api("POST", "/filter/apply", "aplicar", {})
        estado = resposta.json.get("status", "") if isinstance(resposta.json, dict) else ""
        if not str(estado).strip().upper().startswith("OK"):
            raise ErroDoOpnsense("aplicar: o OPNsense nao confirmou")

    def acessivel(self) -> bool:
        try:
            return self._c.requisitar("POST", "/api/firewall/d_nat/search_rule",
                                      json_corpo={"current": 1, "rowCount": 1}).ok
        except Exception:  # noqa: BLE001
            return False


def _validacoes(dados: dict) -> str:
    validacoes = dados.get("validations")
    if isinstance(validacoes, dict) and validacoes:
        return "; ".join(f"{campo}: {texto}" for campo, texto in list(validacoes.items())[:3])
    return str(dados.get("result", "sem detalhe"))[:100]
