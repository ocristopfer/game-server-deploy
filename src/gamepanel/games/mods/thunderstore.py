"""The PANEL side of Thunderstore mods: what the person pastes becomes (namespace, name).

Downloading and installing is done by `thunderstore_remote.py`, inside the CT. Here we only
decide what was asked for, and if the answer is "I don't know", nothing goes to the container:
the name becomes a folder and a URL in there.

Accepts the forms in which a package circulates: the page link, the download link,
`author/package` and the full Thunderstore name (`deca-VampireCommandFramework-0.11.0`). When
the pasted text already carries the version (the full name, the download link or a version
link), it comes along: whoever pasted the name with a version wants THAT version, not the newest.
"""
from __future__ import annotations

import re

# The same charset the remote installer checks again (thunderstore_remote.PART).
_PART = r"[A-Za-z0-9_]{1,64}"
# A Thunderstore version is always major.minor.patch (the site rejects any other form). Checked
# here and again in the CT (thunderstore_remote.VERSION): it becomes part of the API URL.
_VERSION = r"\d{1,9}\.\d{1,9}\.\d{1,9}"
VERSION = re.compile(rf"^{_VERSION}$", re.ASCII)
_URL = re.compile(rf"thunderstore\.io/(?:c/[a-z0-9-]+/p|package(?:/download)?)/({_PART})/({_PART})"
                  rf"(?:/v)?(?:/({_VERSION}))?(?:/|$)", re.ASCII)
_SLASH = re.compile(rf"^({_PART})/({_PART})$", re.ASCII)
_FULL = re.compile(rf"^({_PART})-({_PART})(?:-({_VERSION}))?$", re.ASCII)


def parse_package(text: str) -> tuple[str, str, str] | None:
    """(namespace, name, version); empty version = the newest."""
    value = (text or "").strip()
    for pattern in (_URL, _SLASH, _FULL):
        found = pattern.search(value) if pattern is _URL else pattern.match(value)
        if found:
            version = found.group(3) if pattern is not _SLASH else None
            return found.group(1), found.group(2), version or ""
    return None


def parse_version(text: str) -> str | None:
    """The version typed in the form: empty = the newest; None = invalid (nothing runs)."""
    value = (text or "").strip().lstrip("vV")
    if not value:
        return ""
    return value if VERSION.match(value) else None


def package_url(community: str, ns: str, name: str) -> str:
    return f"https://thunderstore.io/c/{community}/p/{ns}/{name}/"


def split_dir(plugin_dir: str) -> tuple[str, str] | None:
    """The `ns-name` folder the installer creates, back to (ns, name)."""
    found = _FULL.match(plugin_dir or "")
    # The folder never carries a version: `ns-name-1.0.0` is not a folder the installer creates.
    return (found.group(1), found.group(2)) if found and not found.group(3) else None
