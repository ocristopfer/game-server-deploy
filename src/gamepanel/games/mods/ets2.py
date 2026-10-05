"""What is inside the `server_packages.sii` of Euro Truck Simulator 2 (and American Truck).

It is the file the game exports (`export_server_packages`) and the server reads to learn the
map, DLCs and mods. SCS's own format (SiiNunit), text:

    server_packages_info : _nameless.1fe.9af2.f648 {
     dlc_non_essential_list: 8
     mod_list: 21
     map_name: "/map/brbrasil.mbd"
    }
    server_mod_detail : _nameless.1fe.c082.c808 {
     package_name: "mod_workshop_package.00000000C4089C7D"
     mod_name: "Scania L6 Straight pipe "
     mod_id: 3288898685
     workshop_mod: true
     optional_mod: true
    }

A Workshop mod carries its ID in `mod_id` (and in hexadecimal in `package_name`); a mod
installed by hand (the BR Map) carries only an internal signature there, which links to nothing.
DLCs come as codes, not names: they can be counted, not listed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_BLOCK = re.compile(r"(\w+)\s*:\s*[\w.]+\s*\{(.*?)\n\s*\}", re.DOTALL)
_ATTR = re.compile(r"^\s*([\w\[\]]+)\s*:\s*(.*?)\s*$", re.MULTILINE)
_WORKSHOP_PACKAGE = re.compile(r"mod_workshop_package\.([0-9A-Fa-f]{1,16})$")
_DLC_COUNT = re.compile(r"^dlc_(essential|non_essential)_list$")


@dataclass(frozen=True)
class Mod:
    name: str
    package: str
    workshop_id: int
    optional: bool


@dataclass(frozen=True)
class Packages:
    map_name: str = ""
    dlc_count: int = 0
    mods: tuple[Mod, ...] = field(default_factory=tuple)

    @property
    def workshop_ids(self) -> list[int]:
        return [m.workshop_id for m in self.mods if m.workshop_id]


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        value = value[1:-1]
    return value


def _attrs(body: str) -> dict[str, str]:
    return {m.group(1): _unquote(m.group(2)) for m in _ATTR.finditer(body)}


def _workshop_id(attrs: dict[str, str]) -> int:
    if attrs.get("workshop_mod") != "true":
        return 0
    if attrs.get("mod_id", "").isdigit():
        return int(attrs["mod_id"])
    # Without a readable mod_id, the one in the package name (hexadecimal) says the same.
    hex_id = _WORKSHOP_PACKAGE.search(attrs.get("package_name", ""))
    return int(hex_id.group(1), 16) if hex_id else 0


def parse(text: str) -> Packages:
    """Read the file; whatever is not recognized is left out, with no error (it is a SUGGESTION for the screen)."""
    map_name, dlcs, mods = "", 0, []
    for kind, body in _BLOCK.findall((text or "").removeprefix("﻿")):
        attrs = _attrs(body)
        if kind == "server_packages_info":
            map_name = attrs.get("map_name", "")
            dlcs = sum(int(v) for k, v in attrs.items() if _DLC_COUNT.match(k) and v.isdigit())
        elif kind == "server_mod_detail":
            mods.append(Mod(
                name=attrs.get("mod_name", "").strip() or attrs.get("package_name", "?"),
                package=attrs.get("package_name", ""),
                workshop_id=_workshop_id(attrs),
                optional=attrs.get("optional_mod") == "true",
            ))
    return Packages(map_name=map_name, dlc_count=dlcs, mods=tuple(mods))
