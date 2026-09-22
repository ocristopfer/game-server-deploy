"""Entry point WSGI para o gunicorn: `gunicorn gamepanel.wsgi:app`."""

from gamepanel.app import create_app

app = create_app()
