"""WSGI entry point for gunicorn: `gunicorn gamepanel.wsgi:app`.

`app.py` still exposes `app = Flask(__name__)` directly at module level (splitting
it into a `create_app()` application factory is Phase 4 work). This
wsgi.py only re-exports `app` so the gunicorn command does not have to change
again when that happens.
"""

from gamepanel.app import app  # noqa: F401
