"""Quantos clientes estao conversando com o jogo AGORA, pelo firewall do proprio CT.

Para jogo que nao publica consulta nenhuma (o Dragonwilds usa EOS da Epic, e nao a Steam),
o log da os nomes mas reconstroi a contagem de eventos: quem caiu sem linha de saida fica
"online" ate o proximo restart. Este e o numero que nao depende do jogo escrever nada.

O `lib/ct-firewall.sh` mantem, na tabela dele, o conjunto `players`: o par IP:porta de
origem de quem mandou pacote para a porta UDP do jogo com a conversa ESTABELECIDA (o
servidor ja respondeu), com validade de alguns segundos. Scanner que manda um pacote solto
nao entra - o jogo nao responde a lixo -, e quem saiu some sozinho quando a validade
vence. IP:porta e nao so IP: dois jogadores da mesma casa saem pelo mesmo IP publico.
"""
from __future__ import annotations

import json
from collections.abc import Callable

from gamepanel.i18n import Message
from gamepanel.runtime.a2s import QueryError
from gamepanel.runtime.ssh import RemoteError, ServerLike

# O nome da tabela e do conjunto sao os do ct-firewall.sh: mudar la e mudar aqui.
PRESENCE_TABLE = "ct_firewall"
PRESENCE_SET = "players"
# `-j` e saida estavel para maquina; o texto do `nft list` muda de versao para versao.
PRESENCE_COMMAND = f"nft -j list set inet {PRESENCE_TABLE} {PRESENCE_SET}"

SshOutput = Callable[[ServerLike, str, int], str]


def count_from_json(raw: str) -> int:
    """Quantos elementos o conjunto tem, a partir do `nft -j`."""
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise QueryError(Message("presence.unreadable")) from exc
    for item in data.get("nftables", []) if isinstance(data, dict) else []:
        found = item.get("set") if isinstance(item, dict) else None
        if isinstance(found, dict) and found.get("name") == PRESENCE_SET:
            return len(found.get("elem") or [])
    raise QueryError(Message("presence.unreadable"))


def players_from_presence(ssh_output: SshOutput, server: ServerLike) -> dict:
    try:
        raw = ssh_output(server, PRESENCE_COMMAND, 20)
    except RemoteError as exc:
        # Sem o conjunto o nft diz "No such file or directory": e o CT com o firewall antigo
        # (ou sem firewall), e a tela precisa dizer o que fazer. Qualquer outra falha (SSH
        # fora do ar) sobe como veio - chamar isso de "falta o firewall" mandaria a pessoa
        # reaplicar regra num CT que so esta desligado.
        if "no such file" in str(exc).lower():
            raise QueryError(Message("presence.missing")) from exc
        raise QueryError(str(exc)) from exc
    return {"players": count_from_json(raw), "list": [], "error": "",
            "max_players": None, "server_name": "", "map": ""}
