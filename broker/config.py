"""Configuracao do broker em producao, lida do ambiente (systemd EnvironmentFile).

Tudo que o broker precisa para falar com o Proxmox, o OPNsense e os CTs chega por variavel de
ambiente. `carregar` valida TUDO e devolve TODOS os problemas de uma vez: um deploy que erra um
campo por tentativa gasta minutos em cada volta, e um segredo que faltou nao pode virar um
`KeyError` no meio de um pedido.

Nomes iguais aos do `broker.secrets.env` (PROXMOX_*, OPNSENSE_*): o mesmo arquivo de teste vira o
de producao. Segredo NUNCA entra em mensagem de erro; so o NOME da variavel.
"""
from __future__ import annotations

import ipaddress
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .alocador import ips_da_faixa
from .conexao import normalizar_impressao
from .proxmox import ConfigProxmox
from .ssh_install import ARQUIVOS_DA_LIB, ConfigSsh

TOKEN_MINIMO = 32


class ErroDeConfig(ValueError):
    """Configuracao invalida. `problemas` traz uma linha por variavel, sem nenhum valor secreto."""

    def __init__(self, problemas: list[str]):
        super().__init__("configuracao do broker invalida:\n  - " + "\n  - ".join(problemas))
        self.problemas = problemas


@dataclass(frozen=True)
class ConfigBroker:
    token: str
    ips_permitidos: tuple[str, ...]
    estado: Path
    pasta_games: Path
    pasta_lib: Path
    proxmox_url: str
    proxmox_token: str
    proxmox_impressao: str
    proxmox: ConfigProxmox
    opnsense_url: str
    opnsense_key: str
    opnsense_secret: str
    opnsense_impressao: str
    opnsense_wan: str
    ctids: range
    ctid_base: int
    ips: tuple[str, ...]
    portas: range
    max_instancias: int
    max_criacoes_por_hora: int
    ssh: ConfigSsh


class _Leitor:
    """Le variaveis acumulando problemas em vez de parar no primeiro."""

    def __init__(self, env: Mapping[str, str]):
        self._env = env
        self.problemas: list[str] = []

    def texto(self, nome: str, padrao: str | None = None) -> str:
        valor = (self._env.get(nome) or "").strip()
        if not valor and padrao is None:
            self.problemas.append(f"{nome}: obrigatoria e nao foi definida")
            return ""
        return valor or (padrao or "")

    def inteiro(self, nome: str, padrao: int, minimo: int, maximo: int) -> int:
        bruto = (self._env.get(nome) or "").strip()
        if not bruto:
            return padrao
        if not re.fullmatch(r"\d{1,9}", bruto, re.ASCII) or not minimo <= int(bruto) <= maximo:
            self.problemas.append(f"{nome}: deve ser um inteiro entre {minimo} e {maximo}")
            return padrao
        return int(bruto)

    def impressao(self, nome: str, obrigatoria: bool) -> str:
        bruto = (self._env.get(nome) or "").strip()
        if not bruto:
            if obrigatoria:
                self.problemas.append(f"{nome}: obrigatoria com https (impressao SHA-256 do certificado)")
            return ""
        try:
            return normalizar_impressao(bruto)
        except ValueError:
            self.problemas.append(f"{nome}: impressao SHA-256 invalida (64 digitos hexadecimais)")
            return ""

    def tentar(self, descricao: str, funcao):
        try:
            return funcao()
        except (ValueError, OSError) as erro:
            self.problemas.append(f"{descricao}: {erro}")
            return None


def _ips_permitidos(leitor: _Leitor) -> tuple[str, ...]:
    bruto = leitor.texto("BROKER_ALLOW_IPS", "")
    ips: list[str] = []
    for item in filter(None, (p.strip() for p in bruto.split(","))):
        try:
            ips.append(str(ipaddress.IPv4Address(item)))
        except ValueError:
            leitor.problemas.append(f"BROKER_ALLOW_IPS: '{item}' nao e um IPv4")
    return tuple(ips)


def _faixas(leitor: _Leitor) -> tuple[range, int, tuple[str, ...]]:
    ctid_ini = leitor.inteiro("BROKER_CTID_INICIO", 300, 100, 999_999_999)
    ctid_fim = leitor.inteiro("BROKER_CTID_FIM", 399, 100, 999_999_999)
    if ctid_fim < ctid_ini:
        leitor.problemas.append("BROKER_CTID_FIM: menor que BROKER_CTID_INICIO")
    # 0 = CTID escolhido a parte, na faixa acima; senao o CTID e a base + o ultimo numero do IP.
    ctid_base = leitor.inteiro("BROKER_CTID_BASE", 0, 0, 999_999_000)
    prefixo = leitor.texto("BROKER_IP_PREFIX")
    ini = leitor.inteiro("BROKER_IP_INICIO", 30, 1, 254)
    fim = leitor.inteiro("BROKER_IP_FIM", 99, 1, 254)
    if ctid_base and ctid_base + ini < 100:
        leitor.problemas.append("BROKER_CTID_BASE: com o primeiro IP da faixa o CTID ficaria abaixo de 100")
    ips = leitor.tentar("BROKER_IP_PREFIX/INICIO/FIM", lambda: ips_da_faixa(prefixo, ini, fim)) if prefixo else None
    return range(ctid_ini, ctid_fim + 1), ctid_base, ips or ()


def _faixa_de_portas(leitor: _Leitor) -> range:
    """Faixa so do broker para jogos que andam de porta. Fica fora das portas padrao dos jogos
    e abaixo das efemeras do Linux (32768+), que o proprio firewall usa em conexoes de saida."""
    ini = leitor.inteiro("BROKER_PORT_INICIO", 31000, 1024, 65535)
    fim = leitor.inteiro("BROKER_PORT_FIM", 31999, 1024, 65535)
    if fim < ini:
        leitor.problemas.append("BROKER_PORT_FIM: menor que BROKER_PORT_INICIO")
        return range(0)
    return range(ini, fim + 1)


def _confere_url(leitor: _Leitor, nome: str, url: str) -> None:
    """https sempre; http so em loopback (testes). Token em texto puro pela rede nao existe aqui."""
    partes = urlsplit(url)
    if not url:
        return
    if partes.scheme not in ("http", "https") or not partes.hostname:
        leitor.problemas.append(f"{nome}: deve ser http(s)://host[:porta]")
    elif partes.scheme == "http" and partes.hostname not in ("127.0.0.1", "localhost", "::1"):
        leitor.problemas.append(f"{nome}: sem TLS so em loopback; use https://")


def carregar(env: Mapping[str, str]) -> ConfigBroker:
    """Le e valida o ambiente. Levanta `ErroDeConfig` com todos os problemas."""
    leitor = _Leitor(env)
    token = leitor.texto("BROKER_TOKEN")
    if token and len(token) < TOKEN_MINIMO:
        leitor.problemas.append(f"BROKER_TOKEN: precisa ter ao menos {TOKEN_MINIMO} caracteres")

    px_url = leitor.texto("PROXMOX_URL")
    op_url = leitor.texto("OPNSENSE_URL")
    px_https, op_https = px_url.startswith("https://"), op_url.startswith("https://")
    _confere_url(leitor, "PROXMOX_URL", px_url)
    _confere_url(leitor, "OPNSENSE_URL", op_url)
    estado = Path(leitor.texto("BROKER_STATE_DIR", "/var/lib/gamebroker"))
    chave_ssh = Path(leitor.texto("BROKER_SSH_KEY", "/etc/gamebroker/ssh/id_ed25519"))
    pasta_lib = Path(leitor.texto("BROKER_LIB_DIR", "/opt/gamebroker/lib"))
    chave_painel = leitor.texto("BROKER_PANEL_PUBKEY")
    chave_broker = leitor.tentar("BROKER_SSH_KEY.pub", lambda: Path(f"{chave_ssh}.pub").read_text(encoding="utf-8").strip()) or ""

    ctids, ctid_base, ips = _faixas(leitor)
    portas = _faixa_de_portas(leitor)
    gateway = leitor.texto("BROKER_GATEWAY")
    prefixo_rede = leitor.inteiro("BROKER_PREFIXO_REDE", 24, 8, 30)
    # Le TODAS as variaveis antes; so constroi o objeto se elas vieram completas. Senao a mesma
    # falta apareceria duas vezes (a da variavel e a do construtor reclamando de texto vazio).
    antes = len(leitor.problemas)
    px = {"node": leitor.texto("PROXMOX_NODE"), "pool": leitor.texto("PROXMOX_POOL", "games"),
          "storage": leitor.texto("PROXMOX_STORAGE"), "template": leitor.texto("PROXMOX_TEMPLATE"),
          "bridge": leitor.texto("PROXMOX_BRIDGE")}
    proxmox = None
    if len(leitor.problemas) == antes and gateway and chave_broker and chave_painel:
        proxmox = leitor.tentar("PROXMOX_*", lambda: ConfigProxmox(
            **px, gateway=gateway, prefixo=prefixo_rede, chaves_ssh=(chave_broker, chave_painel)))
    faltando = [a for a in ARQUIVOS_DA_LIB if not (pasta_lib / a).is_file()]
    if faltando:
        leitor.problemas.append(f"BROKER_LIB_DIR: faltam {', '.join(faltando)} em {pasta_lib}")
    ssh = None
    if chave_broker:
        ssh = leitor.tentar("BROKER_SSH_*", lambda: ConfigSsh(
            chave_privada=chave_ssh, chave_publica=chave_broker, pasta_lib=pasta_lib))

    cfg_parcial = {
        "proxmox_impressao": leitor.impressao("PROXMOX_CERT_SHA256", px_https),
        "opnsense_impressao": leitor.impressao("OPNSENSE_CERT_SHA256", op_https),
        "proxmox_token": leitor.texto("PROXMOX_TOKEN"), "opnsense_key": leitor.texto("OPNSENSE_KEY"),
        "opnsense_secret": leitor.texto("OPNSENSE_SECRET"), "opnsense_wan": leitor.texto("OPNSENSE_WAN", "wan"),
        "max_instancias": leitor.inteiro("BROKER_MAX_INSTANCIAS", 8, 1, 100),
        "max_criacoes_por_hora": leitor.inteiro("BROKER_MAX_CRIACOES_HORA", 4, 1, 100),
        "ips_permitidos": _ips_permitidos(leitor),
    }
    if leitor.problemas or proxmox is None or ssh is None:
        raise ErroDeConfig(leitor.problemas or ["configuracao incompleta"])
    return ConfigBroker(
        token=token, estado=estado, pasta_games=Path(leitor.texto("BROKER_GAMES_DIR", "/opt/gamebroker/games")),
        pasta_lib=pasta_lib, proxmox_url=px_url, proxmox=proxmox, opnsense_url=op_url,
        ctids=ctids, ctid_base=ctid_base, ips=ips, portas=portas, ssh=ssh, **cfg_parcial)
