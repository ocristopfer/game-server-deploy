"""The history POLICY: what each action is called and who may read its output.

No Flask and no SQL. What starts a job (thread, SSH, database) stays in `app.py`, because
it depends on the per-request connection and on `g`; what lives here is the decision,
which is pure and therefore testable without starting anything.

Two lists live here because the three screens that use them (server history, global
history and the API route) MUST agree. Written out in each query, one of them would
someday let through what the others hide.
"""
from __future__ import annotations

from collections.abc import Mapping

# Action -> catalog key. A KEY and never ready-made text: the history is a screen like the
# others and follows the language of whoever opened it (see `i18n`).
EXTRA_LABELS: Mapping[str, str] = {
    "shell": "job.shell",
    "terminal": "job.terminal",
    "edit-file": "job.file_saved",
    "delete-file": "job.file_deleted",
    "edit-config": "job.config_changed",
    "download-file": "job.file_downloaded",
    "upload-file": "job.file_uploaded",
    "upload-mod": "job.mod_uploaded",
    "delete-mod": "job.mod_deleted",
    "mod-loader": "job.mod_loader",
    "mod-install": "job.mod_installed",
    "mod-remove": "job.mod_removed_plugin",
    "mod-audit": "job.mod_audited",
    "mod-workshop": "job.mod_workshop",
    "backup": "job.backup",
    "restore-backup": "job.backup_restored",
    "delete-backup": "job.backup_deleted",
    "backup-to-panel": "job.backup_sent_to_panel",
    # Moderation gives no root on any container: it is an operation, and stays visible to
    # the operator.
    "player-action": "job.player_action",
    "broker-criar": "job.instance_created",
    "broker-desativar": "job.instance_deactivated",
    "broker-remover": "job.instance_removed",
    "broker-jogo": "job.game_added",
    "broker-jogo-editar": "job.game_edited",
    "broker-jogo-apagar": "job.game_removed",
}

# The history keeps the WHOLE output of what ran. Only an admin can trigger these actions
# (console, terminal, file editor), so their output, which carries the typed command, the
# file contents and whatever else went across the screen, is also readable only by an
# admin. Without this list, an operator who gets a 403 on the console could read the
# console's result by opening the job by id.
ADMIN_ONLY_ACTIONS = frozenset({
    "shell", "terminal", "edit-file", "delete-file", "download-file",
    # 'backup' is left out: making a copy is an operation, and the operator may trigger it.
    # Restoring and deleting, however, destroy data, and downloading takes the save out of
    # the container: those are admin actions, and their records follow suit.
    "upload-file", "restore-backup", "delete-backup",
    # Mods go in and out of the container, like the upload on the Files screen.
    "upload-mod", "delete-mod", "mod-loader", "mod-install", "mod-remove", "mod-audit",
    "mod-workshop",
    # Everything from the broker is admin-only: the output names IPs, CTIDs and ports of
    # the infrastructure.
    "broker-criar", "broker-desativar", "broker-remover", "broker-jogo",
    "broker-jogo-editar", "broker-jogo-apagar",
    # 'edit-config' is left out on purpose: changing the game configuration is an operator
    # task, and its output goes no further than that.
})


def labels(action_labels: Mapping[str, str]) -> dict[str, str]:
    """Merges the labels of the button actions with those born on other screens."""
    return {**action_labels, **EXTRA_LABELS}


def is_restricted(action: str) -> bool:
    return action in ADMIN_ONLY_ACTIONS


def hidden_filter(is_admin: bool) -> tuple[str, tuple[str, ...]]:
    """WHERE fragment that hides the jobs of restricted actions from the operator.

    Returns `("", ())` for the admin: no clause at all, rather than one that accepts
    everything, so the admin's query does not pay for a `NOT IN` with a dozen values.
    """
    if is_admin:
        return "", ()
    hidden = tuple(sorted(ADMIN_ONLY_ACTIONS))
    markers = ",".join("?" * len(hidden))
    return f" AND action NOT IN ({markers})", hidden
