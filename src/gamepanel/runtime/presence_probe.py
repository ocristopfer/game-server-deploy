"""How many clients are talking to the game RIGHT NOW, via the CT's own firewall.

For a game that publishes no query at all (Dragonwilds uses Epic's EOS, not Steam), the
log gives the names but rebuilds the count from events: whoever dropped without a leave
line stays "online" until the next restart. This is the number that does not depend on
the game writing anything.

`lib/ct-firewall.sh` keeps, in its table, the `players` set: the source IP:port pair of
whoever sent a packet to the game's UDP port with the conversation ESTABLISHED (the
server already replied), with a lifetime of a few seconds. A scanner sending a stray
packet does not get in - the game does not answer garbage - and whoever left disappears
on their own when the lifetime expires. IP:port and not just IP: two players in the same
house go out through the same public IP.
"""
from __future__ import annotations

import json
from collections.abc import Callable

from gamepanel.i18n import Message
from gamepanel.runtime import remote_cmd
from gamepanel.runtime.a2s import QueryError
from gamepanel.runtime.ssh import RemoteError, ServerLike

# The table and set names are the ones in ct-firewall.sh: changing them there means
# changing them here.
PRESENCE_TABLE = "ct_firewall"
PRESENCE_SET = "players"
# `-j` is stable machine output; the `nft list` text changes from version to version.
# The legacy-mode command; `remote_cmd.presence` builds it per server (helper mode goes
# through the fixed sudo line).
PRESENCE_COMMAND = f"nft -j list set inet {PRESENCE_TABLE} {PRESENCE_SET}"

SshOutput = Callable[[ServerLike, str, int], str]


def count_from_json(raw: str) -> int:
    """How many elements the set has, from `nft -j`."""
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
        raw = ssh_output(server, remote_cmd.presence(server), 20)
    except RemoteError as exc:
        # Without the set nft says "No such file or directory": it is a CT with the old
        # firewall (or no firewall), and the screen needs to say what to do. Any other
        # failure (SSH down) goes up as it came - calling it "firewall missing" would send
        # the person to reapply rules on a CT that is merely powered off.
        if "no such file" in str(exc).lower():
            raise QueryError(Message("presence.missing")) from exc
        # The original reason as is: it may be a `Message`, and `str` would freeze it in the
        # deploy language.
        raise QueryError(exc.args[0] if exc.args else str(exc)) from exc
    return {"players": count_from_json(raw), "list": [], "error": "",
            "max_players": None, "server_name": "", "map": ""}
