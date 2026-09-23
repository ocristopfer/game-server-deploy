"""Entrega de alerta em webhook (Discord, Slack, ou qualquer coisa que aceite JSON).

So o envio: quem decide QUE avisar, e a quem, e o `services.alert_service`. Aqui nao
ha banco nem regra — e um POST e o motivo da falha em portugues, para a tela.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from gamepanel.runtime.http_probe import URL_RE

# Quanto do corpo da resposta de erro vale a pena ler: o destino diz o que nao gostou
# nas primeiras linhas, e guardar mais que isso so enche a tela de alerta.
ERROR_MAX = 300
RESPONSE_MAX = 2048
# Caminho no formato .../<id>/<token>: com os dois da para mostrar o id e esconder so
# o token. Com menos que isso nao ha o que separar, e tudo vira asterisco.
PARTS_WITH_ID_AND_TOKEN = 2


def mask_url(url: str) -> str:
    """Deixa so o bastante para reconhecer o destino, sem expor o token.

    A URL de webhook e uma credencial: quem le a tela por cima do ombro (ou num
    screenshot colado num chat) nao deveria sair de la podendo escrever no canal.
    """
    if not url:
        return ""
    cut = url.split("://", 1)[-1]
    host, _, rest = cut.partition("/")
    if not rest:
        return host
    parts = [p for p in rest.split("/") if p]
    if len(parts) >= PARTS_WITH_ID_AND_TOKEN:
        # Discord: .../webhooks/<id>/<token>. O id identifica, o token e que e segredo.
        return f"{host}/.../{parts[-2]}/{'*' * 8}"
    return f"{host}/.../{'*' * 8}"


def send(url: str, text: str, timeout: float, user_agent: str) -> str:
    """Faz o POST. Devolve "" quando deu certo, ou o motivo da falha.

    O corpo leva 'content' E 'text': o primeiro e o campo do Discord, o segundo o do
    Slack. Cada um le o seu e ignora o outro, entao a mesma chamada serve para os dois
    (e para qualquer coisa que aceite JSON).
    """
    if not URL_RE.match(url or ""):
        return "URL invalida (use http:// ou https://)"
    body = json.dumps({"content": text, "text": text}).encode("utf-8")
    request_body = urllib.request.Request(  # noqa: S310  # NOSONAR - URL_RE ja recusou o que nao for http(s)
        url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": user_agent},
    )
    try:
        with urllib.request.urlopen(request_body, timeout=timeout) as resp:  # noqa: S310  # NOSONAR
            resp.read(RESPONSE_MAX)
        return ""
    except urllib.error.HTTPError as exc:
        # O corpo da resposta e onde o destino diz o que nao gostou (o Discord manda um
        # JSON com 'message'). Sem ele, um 400 por payload torto e um 403 por bloqueio
        # do Cloudflare ficam com a mesma cara na tela.
        try:
            reason = exc.read(ERROR_MAX).decode("utf-8", "replace").strip().replace("\n", " ")
        # Resposta ja consumida/fechada.
        except Exception:  # noqa: BLE001
            reason = ""
        return f"o webhook respondeu HTTP {exc.code}" + (f": {reason}" if reason else "")
    # Rede: DNS, TLS, timeout, recusa...
    except Exception as exc:  # noqa: BLE001
        return f"nao consegui chamar o webhook: {exc}"
