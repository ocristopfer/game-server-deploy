"""Steam Workshop IDs: what the person pastes and what the panel gives back as a link.

The list arrives the way it circulates among players - link after link, with a chat name
and time in front (`[14:48] Fulano: https://steamcommunity.com/...?id=3132251325`). That is
why the reader looks for the `id=` on each line and also accepts the bare number, instead of
demanding a format. A short number in the middle of the conversation (the time, "1.61") is
not an ID: Workshop IDs have 6 digits or more.
"""
from __future__ import annotations

import re

_URL_ID = re.compile(r"[?&]id=(\d{6,20})", re.ASCII)
_BARE_ID = re.compile(r"^\s*(\d{6,20})\s*$", re.ASCII)
# Cap on what can be pasted: the list is the mods of one server, not a dump.
MAX_IDS = 200


def parse_ids(text: str) -> list[int]:
    """The IDs, in the order they appear and without repeats."""
    found: list[int] = []
    for line in (text or "").splitlines():
        ids = _URL_ID.findall(line) or _BARE_ID.findall(line)
        found.extend(int(i) for i in ids)
    return list(dict.fromkeys(found))[:MAX_IDS]


# Arma Reforger: the workshop is Bohemia's, and the ID is a 16-hex GUID. The page link carries
# the name after the GUID (`/workshop/5965550F24A0C152-WhereAmI`); a pasted line may carry the
# name after it (`5965550F24A0C152 Where Am I`), which is how it shows up in the config.
_GUID = re.compile(r"(?<![0-9A-Fa-f])([0-9A-Fa-f]{16})(?![0-9A-Fa-f])(?:-([A-Za-z0-9_]+))?(.*)$", re.ASCII)
# The name goes into the JSON and into the server log: short text, no control characters.
_NAME_JUNK = re.compile(r"[\x00-\x1f\x7f=]")
NAME_MAX = 80


def parse_guids(text: str) -> list[tuple[str, str]]:
    """(uppercase GUID, name) of each line, in order and without repeating the GUID."""
    found: dict[str, str] = {}
    for line in (text or "").splitlines():
        m = _GUID.search(line)
        if not m:
            continue
        guid, slug, rest = m.group(1).upper(), m.group(2) or "", m.group(3)
        name = _NAME_JUNK.sub("", rest).strip(" -:\t") or slug
        found.setdefault(guid, name[:NAME_MAX].strip())
    return list(found.items())[:MAX_IDS]


def reforger_url(guid: str) -> str:
    return f"https://reforger.armaplatform.com/workshop/{guid}"


def url(workshop_id: int) -> str:
    return f"https://steamcommunity.com/sharedfiles/filedetails/?id={workshop_id}"
