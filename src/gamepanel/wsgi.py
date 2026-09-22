"""Entry point WSGI para o gunicorn: `gunicorn gamepanel.wsgi:app`.

`app.py` ainda expoe `app = Flask(__name__)` direto no nivel do modulo (a
fatiacao em application factory `create_app()` e trabalho da Fase 4). Este
wsgi.py so reexporta `app` para que o comando do gunicorn nao precise mudar
de novo quando isso acontecer.
"""

from gamepanel.app import app  # noqa: F401
