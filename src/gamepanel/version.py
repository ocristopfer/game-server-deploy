"""Which version of the panel is running, and which commit it came from.

The real value is written by `tools/build-release.py` into a `_build.py` that exists ONLY
inside the tarball, never in the working tree. That way `git status` stays clean after
packaging, and what runs in production carries the identity of the artifact that was
published, instead of one somebody remembered to edit by hand.

Without that file (that is: running from the repository), the version is the one in the
root `VERSION` with the `+dev` mark. The mark matters: it is what tells "the panel on the
CT is at 0.1.0" apart from "someone is looking at their own machine".
"""
from __future__ import annotations

import os
from typing import NamedTuple

DEV_SUFFIX = "+dev"
UNKNOWN = "0.0.0"
VERSION_FILE = "VERSION"
SEARCH_LEVELS = 4


class Build(NamedTuple):
    """The identity of what is running."""

    version: str
    commit: str
    built_at: str

    @property
    def is_dev(self) -> bool:
        return self.version.endswith(DEV_SUFFIX)

    def as_public(self) -> dict[str, str]:
        return {"version": self.version, "commit": self.commit, "built_at": self.built_at}


def version_from_repo(start: str, levels: int = SEARCH_LEVELS) -> str:
    """Read the repository root `VERSION`, walking up folders from `start`.

    It walks up instead of hardcoding `../../VERSION` because the package is also mounted at
    `/opt/gamepanel/gamepanel` in the development container, where the repository root
    is somewhere else. Not finding it is not an error: it is just a panel with no declared
    version, and `UNKNOWN` says exactly that.
    """
    folder = os.path.dirname(os.path.abspath(start))
    for _ in range(levels):
        candidate = os.path.join(folder, VERSION_FILE)
        if os.path.isfile(candidate):
            try:
                with open(candidate, encoding="utf-8") as fh:
                    return fh.read().strip() or UNKNOWN
            except OSError:
                break
        parent = os.path.dirname(folder)
        if parent == folder:
            break
        folder = parent
    return UNKNOWN


def _current() -> Build:
    # `_build` holds plain text, not a ready `Build`: importing the type from here would make
    # this module depend on what depends on it, and the import would become circular.
    try:
        # Not in the tree: the packager writes it inside the tarball.
        from gamepanel import _build  # type: ignore[attr-defined]
    except ImportError:
        return Build(version_from_repo(__file__) + DEV_SUFFIX, "", "")
    return Build(_build.VERSION, _build.COMMIT, _build.BUILT_AT)


BUILD = _current()
__version__ = BUILD.version
