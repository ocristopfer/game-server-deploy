"""CSRF proprio do painel — nao e o Flask-WTF.

Producao so tem stdlib mais o `python3-flask` do apt (ver CLAUDE.md), entao nao ha
`CSRFProtect` para instalar. A protecao e o par: `token()` gera e guarda na sessao, e
`check()` barra todo POST que nao traga o mesmo valor de volta.

Analisador estatico costuma marcar o `Flask(__name__)` do `app.py` como "CSRF
desabilitado" porque nao enxerga um `CSRFProtect(app)`. E falso positivo, e ha um
`# NOSONAR` la com o motivo. **Nao remova o `check()` do `before_request`.**
"""
from __future__ import annotations

import hmac
import secrets
from collections.abc import Mapping, MutableMapping

TOKEN_BYTES = 32
SESSION_KEY = "csrf"
FORM_FIELD = "csrf"
# O terminal e o editor postam JSON (sem formulario), entao mandam o mesmo valor por
# cabecalho. Sem isto eles precisariam de um caminho proprio, sem protecao.
HEADER = "X-CSRF-Token"


def token(session: MutableMapping[str, object]) -> str:
    """O token desta sessao, criado na primeira vez que alguem o pede."""
    current = session.get(SESSION_KEY)
    if not current:
        current = secrets.token_urlsafe(TOKEN_BYTES)
        session[SESSION_KEY] = current
    return str(current)


def matches(session: Mapping[str, object], form: Mapping[str, str],
            headers: Mapping[str, str]) -> bool:
    """O que voltou e o que esta na sessao?

    `compare_digest` e nao `==`: o tempo de resposta de uma comparacao comum diz quantos
    bytes do inicio batem, e isso e o bastante para descobrir o token byte a byte.
    """
    sent = form.get(FORM_FIELD, "") or headers.get(HEADER, "")
    expected = str(session.get(SESSION_KEY, ""))
    return bool(sent) and hmac.compare_digest(sent, expected)
