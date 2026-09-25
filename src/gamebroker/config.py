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
from typing import Any
from urllib.parse import urlsplit

from gamebroker.integrations.http_client import normalize_fingerprint
from gamebroker.runtime.proxmox import ConfigProxmox
from gamebroker.runtime.ssh_installer import LIB_FILES, ConfigSsh, SteamAccount
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

    def text(self, name: str, default: str | None = None) -> str:
        value = (self._env.get(name) or "").strip()
        if not value and default is None:
            self.problems.append(f"{name}: obrigatoria e nao foi definida")
            return ""
        return value or (default or "")

    def integer(self, name: str, default: int, minimum: int, maximum: int) -> int:
        raw_text = (self._env.get(name) or "").strip()
        if not raw_text:
            return default
        if not re.fullmatch(r"\d{1,9}", raw_text, re.ASCII) or not minimum <= int(raw_text) <= maximum:
            self.problems.append(f"{name}: deve ser um inteiro entre {minimum} e {maximum}")
            return default
        return int(raw_text)

    def fingerprint(self, name: str, required: bool) -> str:
        raw_text = (self._env.get(name) or "").strip()
        if not raw_text:
            if required:
                self.problems.append(f"{name}: obrigatoria com https (impressao SHA-256 do certificado)")
            return ""
        try:
            return normalize_fingerprint(raw_text)
        except ValueError:
            self.problems.append(f"{name}: impressao SHA-256 invalida (64 digitos hexadecimais)")
            return ""

    def attempt(self, description: str, func):
        try:
            return func()
        except (ValueError, OSError) as error:
            self.problems.append(f"{description}: {error}")
            return None


def _read_allowed_ips(reader: _Reader) -> tuple[str, ...]:
    raw_text = reader.text("BROKER_ALLOW_IPS", "")
    ips: list[str] = []
    for item in filter(None, (p.strip() for p in raw_text.split(","))):
        try:
            ips.append(str(ipaddress.IPv4Address(item)))
        except ValueError:
            reader.problems.append(f"BROKER_ALLOW_IPS: '{item}' nao e um IPv4")
    return tuple(ips)


def _ranges(reader: _Reader) -> tuple[range, int, tuple[str, ...]]:
    ctid_start = reader.integer("BROKER_CTID_INICIO", 300, 100, 999_999_999)
    ctid_end = reader.integer("BROKER_CTID_FIM", 399, 100, 999_999_999)
    if ctid_end < ctid_start:
        reader.problems.append("BROKER_CTID_FIM: menor que BROKER_CTID_INICIO")
    # 0 = CTID escolhido a parte, na faixa acima; senao o CTID e a base + o ultimo numero do IP.
    ctid_base = reader.integer("BROKER_CTID_BASE", 0, 0, 999_999_000)
    prefix = reader.text("BROKER_IP_PREFIX")
    ini = reader.integer("BROKER_IP_INICIO", 30, 1, 254)
    end_at = reader.integer("BROKER_IP_FIM", 99, 1, 254)
    if ctid_base and ctid_base + ini < 100:
        reader.problems.append("BROKER_CTID_BASE: com o primeiro IP da faixa o CTID ficaria abaixo de 100")
    ips = reader.attempt("BROKER_IP_PREFIX/INICIO/FIM", lambda: ips_in_range(prefix, ini, end_at)) if prefix else None
    return range(ctid_start, ctid_end + 1), ctid_base, ips or ()


def _port_range(reader: _Reader) -> range:
    """Faixa so do broker para jogos que andam de porta. Fica fora das portas padrao dos jogos
    e abaixo das efemeras do Linux (32768+), que o proprio firewall usa em conexoes de saida."""
    ini = reader.integer("BROKER_PORT_INICIO", 31000, 1024, 65535)
    end_at = reader.integer("BROKER_PORT_FIM", 31999, 1024, 65535)
    if end_at < ini:
        reader.problems.append("BROKER_PORT_FIM: menor que BROKER_PORT_INICIO")
        return range(0)
    return range(ini, end_at + 1)


def _steam_account(reader: _Reader) -> SteamAccount | None:
    """Opcional: sem as duas, o jogo que exige conta (DayZ) so fica fora do catalogo criavel.

    Uma sem a outra e ERRO, e nao "sem conta": quem preencheu uma quis ligar o recurso, e
    desliga-lo calado deixaria o DayZ "manual" sem ninguem saber por que.
    """
    user = reader.text("STEAM_USER", "")
    password = reader.text("STEAM_PASS", "")
    if not user and not password:
        return None
    if not (user and password):
        reader.problems.append("STEAM_USER/STEAM_PASS: defina as duas, ou nenhuma")
        return None
    return reader.attempt("STEAM_USER/STEAM_PASS", lambda: SteamAccount(user, password))


def _check_url(reader: _Reader, name: str, url: str) -> None:
    """https sempre; http so em loopback (testes). Token em texto puro pela rede nao existe aqui."""
    parts = urlsplit(url)
    if not url:
        return
    if parts.scheme not in ("http", "https") or not parts.hostname:
        reader.problems.append(f"{name}: deve ser http(s)://host[:porta]")
    elif parts.scheme == "http" and parts.hostname not in ("127.0.0.1", "localhost", "::1"):
        reader.problems.append(f"{name}: sem TLS so em loopback; use https://")


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
    ssh_key = Path(reader.text("BROKER_SSH_KEY", "/etc/gamebroker/ssh/id_ed25519"))
    lib_dir = Path(reader.text("BROKER_LIB_DIR", "/opt/gamebroker/lib"))
    panel_key = reader.text("BROKER_PANEL_PUBKEY")
    broker_key = reader.attempt(
        "BROKER_SSH_KEY.pub",
        lambda: Path(f"{ssh_key}.pub").read_text(encoding="utf-8").strip()) or ""

    ctids, ctid_base, ips = _ranges(reader)
    ports = _port_range(reader)
    gateway = reader.text("BROKER_GATEWAY")
    network_prefix = reader.integer("BROKER_PREFIXO_REDE", 24, 8, 30)
    # Le TODAS as variaveis antes; so constroi o objeto se elas vieram completas. Senao a mesma
    # falta apareceria duas vezes (a da variavel e a do construtor reclamando de texto vazio).
    before = len(reader.problems)
    # `dict[str, Any]` e o tipo HONESTO, e nao uma supressao: o dicionario e heterogeneo
    # (texto, numero, tupla) e existe para ser aberto com `**` num construtor tipado. Sem a
    # anotacao o verificador infere `dict[str, str]` a partir das primeiras chaves e acusa
    # cada campo que nao e texto — e essa e a armadilha que o CLAUDE.md descreve: aqui o
    # nome do campo viaja como TEXTO, e nenhuma ferramenta liga a chave ao parametro.
    px: dict[str, Any] = {"node": reader.text("PROXMOX_NODE"), "pool": reader.text("PROXMOX_POOL", "games"),
          "storage": reader.text("PROXMOX_STORAGE"), "template": reader.text("PROXMOX_TEMPLATE"),
          "bridge": reader.text("PROXMOX_BRIDGE")}
    proxmox = None
    if len(reader.problems) == before and gateway and broker_key and panel_key:
        proxmox = reader.attempt("PROXMOX_*", lambda: ConfigProxmox(
            **px, gateway=gateway, prefix=network_prefix, ssh_keys=(broker_key, panel_key)))
    missing_ones = [a for a in LIB_FILES if not (lib_dir / a).is_file()]
    if missing_ones:
        reader.problems.append(f"BROKER_LIB_DIR: faltam {', '.join(missing_ones)} em {lib_dir}")
    steam = _steam_account(reader)
    ssh = None
    if broker_key:
        ssh = reader.attempt("BROKER_SSH_*", lambda: ConfigSsh(
            private_key=ssh_key, public_key=broker_key, lib_dir=lib_dir, steam=steam))

    cfg_parcial: dict[str, Any] = {
        "proxmox_fingerprint": reader.fingerprint("PROXMOX_CERT_SHA256", px_https),
        "opnsense_fingerprint": reader.fingerprint("OPNSENSE_CERT_SHA256", op_https),
        "proxmox_token": reader.text("PROXMOX_TOKEN"), "opnsense_key": reader.text("OPNSENSE_KEY"),
        "opnsense_secret": reader.text("OPNSENSE_SECRET"), "opnsense_wan": reader.text("OPNSENSE_WAN", "wan"),
        "max_instances": reader.integer("BROKER_MAX_INSTANCIAS", 8, 1, 100),
        "max_creations_per_hour": reader.integer("BROKER_MAX_CREATIONS_PER_HOUR", 4, 1, 100),
        "allowed_ips": _read_allowed_ips(reader),
    }
    if reader.problems or proxmox is None or ssh is None:
        raise ConfigError(reader.problems or ["configuracao incompleta"])
    return ConfigBroker(
        token=token, state_dir=state_dir, games_dir=Path(reader.text("BROKER_GAMES_DIR", "/opt/gamebroker/games")),
        lib_dir=lib_dir, proxmox_url=px_url, proxmox=proxmox, opnsense_url=op_url,
        ctids=ctids, ctid_base=ctid_base, ips=ips, ports=ports, ssh=ssh, **cfg_parcial)
