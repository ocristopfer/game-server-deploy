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

from gamebroker.integrations.http_client import normalize_fingerprint
from gamebroker.runtime.proxmox import ConfigProxmox
from gamebroker.runtime.ssh_installer import ARQUIVOS_DA_LIB, ConfigSsh
from gamebroker.services.allocator import ips_in_range

TOKEN_MINIMO = 32


class ConfigError(ValueError):
    """Configuracao invalida. `problemas` traz uma linha por variavel, sem nenhum valor secreto."""

    def __init__(self, problems: list[str]):
        super().__init__("configuracao do broker invalida:\n  - " + "\n  - ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class ConfigBroker:
    token: str
    allowed_ips: tuple[str, ...]
    state_dir: Path
    games_dir: Path
    lib_dir: Path
    proxmox_url: str
    proxmox_token: str
    proxmox_fingerprint: str
    proxmox: ConfigProxmox
    opnsense_url: str
    opnsense_key: str
    opnsense_secret: str
    opnsense_fingerprint: str
    opnsense_wan: str
    ctids: range
    ctid_base: int
    ips: tuple[str, ...]
    ports: range
    max_instances: int
    max_creations_per_hour: int
    ssh: ConfigSsh


class _Reader:
    """Le variaveis acumulando problemas em vez de parar no primeiro."""

    def __init__(self, env: Mapping[str, str]):
        self._env = env
        self.problems: list[str] = []

    def text(self, nome: str, default: str | None = None) -> str:
        valor = (self._env.get(nome) or "").strip()
        if not valor and default is None:
            self.problems.append(f"{nome}: obrigatoria e nao foi definida")
            return ""
        return valor or (default or "")

    def integer(self, nome: str, default: int, minimum: int, maximum: int) -> int:
        bruto = (self._env.get(nome) or "").strip()
        if not bruto:
            return default
        if not re.fullmatch(r"\d{1,9}", bruto, re.ASCII) or not minimum <= int(bruto) <= maximum:
            self.problems.append(f"{nome}: deve ser um inteiro entre {minimum} e {maximum}")
            return default
        return int(bruto)

    def fingerprint(self, nome: str, required: bool) -> str:
        bruto = (self._env.get(nome) or "").strip()
        if not bruto:
            if required:
                self.problems.append(f"{nome}: obrigatoria com https (impressao SHA-256 do certificado)")
            return ""
        try:
            return normalize_fingerprint(bruto)
        except ValueError:
            self.problems.append(f"{nome}: impressao SHA-256 invalida (64 digitos hexadecimais)")
            return ""

    def attempt(self, description: str, func):
        try:
            return func()
        except (ValueError, OSError) as erro:
            self.problems.append(f"{description}: {erro}")
            return None


def _read_allowed_ips(reader: _Reader) -> tuple[str, ...]:
    bruto = reader.text("BROKER_ALLOW_IPS", "")
    ips: list[str] = []
    for item in filter(None, (p.strip() for p in bruto.split(","))):
        try:
            ips.append(str(ipaddress.IPv4Address(item)))
        except ValueError:
            reader.problems.append(f"BROKER_ALLOW_IPS: '{item}' nao e um IPv4")
    return tuple(ips)


def _ranges(reader: _Reader) -> tuple[range, int, tuple[str, ...]]:
    ctid_ini = reader.integer("BROKER_CTID_INICIO", 300, 100, 999_999_999)
    ctid_fim = reader.integer("BROKER_CTID_FIM", 399, 100, 999_999_999)
    if ctid_fim < ctid_ini:
        reader.problems.append("BROKER_CTID_FIM: menor que BROKER_CTID_INICIO")
    # 0 = CTID escolhido a parte, na faixa acima; senao o CTID e a base + o ultimo numero do IP.
    ctid_base = reader.integer("BROKER_CTID_BASE", 0, 0, 999_999_000)
    prefixo = reader.text("BROKER_IP_PREFIX")
    ini = reader.integer("BROKER_IP_INICIO", 30, 1, 254)
    fim = reader.integer("BROKER_IP_FIM", 99, 1, 254)
    if ctid_base and ctid_base + ini < 100:
        reader.problems.append("BROKER_CTID_BASE: com o primeiro IP da faixa o CTID ficaria abaixo de 100")
    ips = reader.attempt("BROKER_IP_PREFIX/INICIO/FIM", lambda: ips_in_range(prefixo, ini, fim)) if prefixo else None
    return range(ctid_ini, ctid_fim + 1), ctid_base, ips or ()


def _port_range(reader: _Reader) -> range:
    """Faixa so do broker para jogos que andam de porta. Fica fora das portas padrao dos jogos
    e abaixo das efemeras do Linux (32768+), que o proprio firewall usa em conexoes de saida."""
    ini = reader.integer("BROKER_PORT_INICIO", 31000, 1024, 65535)
    fim = reader.integer("BROKER_PORT_FIM", 31999, 1024, 65535)
    if fim < ini:
        reader.problems.append("BROKER_PORT_FIM: menor que BROKER_PORT_INICIO")
        return range(0)
    return range(ini, fim + 1)


def _check_url(reader: _Reader, nome: str, url: str) -> None:
    """https sempre; http so em loopback (testes). Token em texto puro pela rede nao existe aqui."""
    partes = urlsplit(url)
    if not url:
        return
    if partes.scheme not in ("http", "https") or not partes.hostname:
        reader.problems.append(f"{nome}: deve ser http(s)://host[:porta]")
    elif partes.scheme == "http" and partes.hostname not in ("127.0.0.1", "localhost", "::1"):
        reader.problems.append(f"{nome}: sem TLS so em loopback; use https://")


def load(env: Mapping[str, str]) -> ConfigBroker:
    """Le e valida o ambiente. Levanta `ErroDeConfig` com todos os problemas."""
    reader = _Reader(env)
    token = reader.text("BROKER_TOKEN")
    if token and len(token) < TOKEN_MINIMO:
        reader.problems.append(f"BROKER_TOKEN: precisa ter ao menos {TOKEN_MINIMO} caracteres")

    px_url = reader.text("PROXMOX_URL")
    op_url = reader.text("OPNSENSE_URL")
    px_https, op_https = px_url.startswith("https://"), op_url.startswith("https://")
    _check_url(reader, "PROXMOX_URL", px_url)
    _check_url(reader, "OPNSENSE_URL", op_url)
    state_dir = Path(reader.text("BROKER_STATE_DIR", "/var/lib/gamebroker"))
    chave_ssh = Path(reader.text("BROKER_SSH_KEY", "/etc/gamebroker/ssh/id_ed25519"))
    lib_dir = Path(reader.text("BROKER_LIB_DIR", "/opt/gamebroker/lib"))
    chave_painel = reader.text("BROKER_PANEL_PUBKEY")
    chave_broker = reader.attempt("BROKER_SSH_KEY.pub", lambda: Path(f"{chave_ssh}.pub").read_text(encoding="utf-8").strip()) or ""

    ctids, ctid_base, ips = _ranges(reader)
    ports = _port_range(reader)
    gateway = reader.text("BROKER_GATEWAY")
    prefixo_rede = reader.integer("BROKER_PREFIXO_REDE", 24, 8, 30)
    # Le TODAS as variaveis antes; so constroi o objeto se elas vieram completas. Senao a mesma
    # falta apareceria duas vezes (a da variavel e a do construtor reclamando de texto vazio).
    antes = len(reader.problems)
    px = {"node": reader.text("PROXMOX_NODE"), "pool": reader.text("PROXMOX_POOL", "games"),
          "storage": reader.text("PROXMOX_STORAGE"), "template": reader.text("PROXMOX_TEMPLATE"),
          "bridge": reader.text("PROXMOX_BRIDGE")}
    proxmox = None
    if len(reader.problems) == antes and gateway and chave_broker and chave_painel:
        proxmox = reader.attempt("PROXMOX_*", lambda: ConfigProxmox(
            **px, gateway=gateway, prefixo=prefixo_rede, chaves_ssh=(chave_broker, chave_painel)))
    faltando = [a for a in ARQUIVOS_DA_LIB if not (lib_dir / a).is_file()]
    if faltando:
        reader.problems.append(f"BROKER_LIB_DIR: faltam {', '.join(faltando)} em {lib_dir}")
    ssh = None
    if chave_broker:
        ssh = reader.attempt("BROKER_SSH_*", lambda: ConfigSsh(
            chave_privada=chave_ssh, chave_publica=chave_broker, lib_dir=lib_dir))

    cfg_parcial = {
        "proxmox_fingerprint": reader.fingerprint("PROXMOX_CERT_SHA256", px_https),
        "opnsense_fingerprint": reader.fingerprint("OPNSENSE_CERT_SHA256", op_https),
        "proxmox_token": reader.text("PROXMOX_TOKEN"), "opnsense_key": reader.text("OPNSENSE_KEY"),
        "opnsense_secret": reader.text("OPNSENSE_SECRET"), "opnsense_wan": reader.text("OPNSENSE_WAN", "wan"),
        "max_instances": reader.integer("BROKER_MAX_INSTANCIAS", 8, 1, 100),
        "max_creations_per_hour": reader.integer("BROKER_MAX_CRIACOES_HORA", 4, 1, 100),
        "allowed_ips": _read_allowed_ips(reader),
    }
    if reader.problems or proxmox is None or ssh is None:
        raise ConfigError(reader.problems or ["configuracao incompleta"])
    return ConfigBroker(
        token=token, state_dir=state_dir, games_dir=Path(reader.text("BROKER_GAMES_DIR", "/opt/gamebroker/games")),
        lib_dir=lib_dir, proxmox_url=px_url, proxmox=proxmox, opnsense_url=op_url,
        ctids=ctids, ctid_base=ctid_base, ips=ips, ports=ports, ssh=ssh, **cfg_parcial)
