"""Every command the panel runs in a game container is built here, stating its INTENT.

There are two ways the panel can be logged in to a container (see
docs/security-hardening-contract.md):

- **legacy mode** (`servers.ssh_user == 'root'`): the commands are exactly the ones the panel
  always sent. Nothing changes for a server registered before the hardening, and the full test
  suite is the proof - every string built here for root is byte-identical to the old one.
- **helper mode** (any other user, `gamepanel` for new containers): the login user has no
  rights of its own. It reaches root ONLY through the fixed `sudo -n` lines of the sudoers file
  (service verbs, update, presence, ClamAV install), and touches game content ONLY as `steam`
  (`sudo -n -u steam --`), so a symlink the game planted points at nothing steam could not
  already write.

Callers never write a prefix by hand: they say what the command is FOR (`service_action`,
`as_steam`, `unprivileged`...). A raw `sudo` scattered across the code is how one call site
ends up running as the wrong user without anyone noticing - here a new call site has to pick
an intent, and the choice is visible in review.
"""
from __future__ import annotations

from gamepanel.runtime.ssh import ServerLike, quote_command

# The user that means "legacy mode". Anything else is helper mode.
LEGACY_USER = "root"
# The login user of every container created from now on (broker, deploy, the form default).
HELPER_USER = "gamepanel"
# Who owns the game and its files. Content operations run as this user in helper mode.
GAME_USER = "steam"

# Root helpers (fixed paths: sudo matches the command by its absolute path, and the sudoers
# file lists exactly these).
GP_SERVICE = "/usr/local/sbin/gp-service"
GP_CLAMAV_ENSURE = "/usr/local/sbin/gp-clamav-ensure"
UPDATE_GAME = "/usr/local/bin/update-game"
CHECK_GAME_UPDATE = "/usr/local/bin/check-game-update"
NFT = "/usr/sbin/nft"
# Same words as the sudoers line: one argument more or less and sudo asks for a password,
# which `-n` turns into an immediate failure instead of a hang.
PRESENCE_ARGS = ("-j", "list", "set", "inet", "ct_firewall", "players")

# The service verbs `gp-service` accepts. The unit name never travels: the helper reads it
# from the root-owned /etc/gamepanel/ct.env, so `gp-service stop ssh` cannot exist.
SERVICE_VERBS = ("start", "stop", "restart")
# The update helpers take no argument at all.
ROOT_HELPERS = {"update": UPDATE_GAME, "check-update": CHECK_GAME_UPDATE}

# `-n` (never prompt): a missing sudoers line must FAIL at once. Without it sudo would wait for
# a password on a session that has no terminal, and the job would hang until its timeout.
_SUDO = ("sudo", "-n")
# `cd /` before switching to steam: the SSH session starts in gamepanel's home (0700), which
# steam cannot enter. bash then prints "shell-init: error retrieving current directory" and
# `find` fails with "Failed to restore initial working directory" - on every content command.
# The `cd` runs in gamepanel's own shell, so the sudo line itself is still the contract's.
_STEAM_PREFIX = "cd / && "


def ssh_user(server: ServerLike) -> str:
    """The login user of this server; a row (or dict) without the field is legacy.

    Missing and empty count as root on purpose: they are what a server registered before the
    column had a real choice looks like, and legacy mode is what such a server still speaks.
    """
    try:
        user = server["ssh_user"]
    except (KeyError, IndexError):
        return LEGACY_USER
    return str(user or LEGACY_USER)


def privileged(server: ServerLike) -> bool:
    """True for legacy mode (the panel logs in as root), False for helper mode."""
    return ssh_user(server) == LEGACY_USER


def content_user(server: ServerLike) -> str:
    """Who the console, the terminal and the file manager act as on this server.

    For the screens: "commands run as root" on a helper-mode server would be a lie, and the
    person reading it decides what to type based on it.
    """
    return ssh_user(server) if privileged(server) else GAME_USER


def unprivileged(*argv: str) -> str:
    """A command that needs no right at all (status, logs, metrics, HTTP from inside).

    The same string in both modes. It exists so the call site SAYS it needs nothing - the
    next person adding a call does not have to wonder whether the missing wrapper is a bug.
    """
    return quote_command(*argv)


def as_root_action(server: ServerLike, action: str) -> str:
    """What one of the panel's action buttons runs (`app.COMMANDS`).

    Legacy: `systemctl <verb> <unit>` and the update scripts, exactly as before. Helper: the
    same through the fixed sudo lines.
    """
    if action in SERVICE_VERBS:
        if privileged(server):
            return quote_command("systemctl", action, server["service"])
        return quote_command(*_SUDO, GP_SERVICE, action)
    helper = ROOT_HELPERS.get(action)
    if helper is None:
        raise ValueError(f"acao sem comando: {action}")
    if privileged(server):
        return helper
    return quote_command(*_SUDO, helper)


def presence(server: ServerLike) -> str:
    """Read the firewall's set of active players (`nft -j`)."""
    if privileged(server):
        return quote_command("nft", *PRESENCE_ARGS)
    return quote_command(*_SUDO, NFT, *PRESENCE_ARGS)


def as_steam(server: ServerLike, *argv: str) -> str:
    """A command that touches game CONTENT: files, backups, mods, console, port discovery.

    Legacy: the command as it always was (it runs as root). Helper: as `steam`, the owner of
    what it touches - files come out with the right owner and a planted symlink only reaches
    what steam could already write. stdin passes through untouched (`!use_pty` in the sudoers
    file), which is what uploads and the backup push depend on.
    """
    if privileged(server):
        return quote_command(*argv)
    return _STEAM_PREFIX + quote_command(*_SUDO, "-u", GAME_USER, "--", *argv)


def interactive_shell(server: ServerLike) -> str | None:
    """The remote command for the interactive terminal, or None for ssh's own login shell.

    Legacy: None - the terminal is root's login shell, as it always was. Helper: a login shell
    of `steam` (`-i` also changes to steam's home, so there is no `cd /` to add). Root
    break-glass for a migrated container is `pct enter` on the host, never the panel.
    """
    if privileged(server):
        return None
    return quote_command(*_SUDO, "-u", GAME_USER, "-i")


def clamav_ensure() -> str:
    """Install ClamAV if missing and refresh its signatures (helper mode only).

    In legacy mode the antivirus scripts do this inline, as root; in helper mode the scan
    runs as steam, which can neither `apt-get` nor stop the freshclam daemon, so it becomes a
    step of its own through the fixed root helper.
    """
    return quote_command(*_SUDO, GP_CLAMAV_ENSURE)
