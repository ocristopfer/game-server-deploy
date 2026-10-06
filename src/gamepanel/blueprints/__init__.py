"""The panel's HTTP layer, one screen per file.

Each module here only does the HTTP work: read the request, call whoever decides and pick
the template. The rules stay in `services/`, remote access in `runtime/` and the assembly
(database, session, decorators, tables) in `app.py`, which is where everything gets wired.

**Why the blueprints call `panel.X` instead of importing the function directly.** The tests
swap functions for fakes with `monkeypatch.setattr(panel, "server_status", ...)`, which
replaces the name IN THE `gamepanel.app` MODULE. A `from gamepanel.app import server_status`
here would copy the reference at import time, and the test's swap would stop taking effect
**silently**: the tests would pass without testing anything. That is why every access is
`panel.server_status(...)`, and why `app.py` registers the blueprints at the END of the
file, when everything they call already exists.
"""
from __future__ import annotations

from flask import Flask


def register_all(app: Flask) -> None:
    """Attach each blueprint to the app. Called at the bottom of `app.py`.

    The import lives INSIDE the function on purpose: at the top it would run while
    `gamepanel.app` is still executing, and each blueprint would `import
    gamepanel.app` from a half-built module.
    """
    from gamepanel.blueprints import (
        account,
        alerts,
        auth,
        backups,
        broker,
        charts,
        config_quick,
        console,
        dashboard,
        files,
        health,
        history,
        jobs,
        mods,
        passkeys,
        players,
        preferences,
        push,
        pwa,
        schedules,
        servers,
        terminal,
        users,
    )

    for module in (
        account, alerts, auth, backups, broker, charts, config_quick, console,
        dashboard, files, health, history, jobs, mods, passkeys, players, preferences, push, pwa,
        schedules, servers, terminal, users,
    ):
        app.register_blueprint(module.bp)
