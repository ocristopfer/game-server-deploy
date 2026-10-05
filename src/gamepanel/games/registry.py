"""Which adapter applies to which configuration file.

The choice is by the file NAME, not by the game registered on the server: it is the same
criterion the panel already uses to pick the reader (ini, json, cfg), and it works even on
a server whose game nobody declared.
"""
from __future__ import annotations

from gamepanel.games.adapters import dayz, dragonwilds, enshrouded, ets2, icarus, palworld
from gamepanel.games.base import FieldSpec

# Order does not matter: the patterns are distinct file names. The list is explicit -
# and not a scan of the folder - so that a reader knows, without running anything, which
# games have their own screen. The test makes sure it does not fall behind.
ADAPTERS = (dragonwilds, enshrouded, palworld, icarus, dayz, ets2)


def catalog_for(filename: str) -> dict[str, FieldSpec]:
    """Catalog for the file, or empty when the game has not been mapped yet."""
    name = (filename or "").strip().rsplit("/", 1)[-1]
    for adapter in ADAPTERS:
        if adapter.FILENAME.match(name):
            return adapter.FIELDS
    return {}


def describe(filename: str, key: str) -> FieldSpec | None:
    """Description of a field, or None when it is not mapped.

    The lookup is by key name only: the same field shows up in different sections
    (`userGroups[0].password` and `userGroups[1].password`, for example) and the description
    applies to both.
    """
    catalog = catalog_for(filename)
    if not catalog:
        return None
    return catalog.get((key or "").strip())
