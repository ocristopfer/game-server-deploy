"""O que faz o painel instalar no celular: manifest, service worker e a tela sem rede."""
from __future__ import annotations

from flask import Blueprint, render_template

from gamepanel import app as panel

bp = Blueprint("pwa", __name__)


@bp.get("/manifest.webmanifest")
def manifest():
    """Ficha do aplicativo: nome, icones, cor e tela inicial.

    Sai de um template (e nao de um arquivo estatico) para os caminhos dos icones
    virem do proprio Flask — inclusive a marca de versao do `static_url`.
    """
    resp = panel.app.response_class(
        render_template("manifest.webmanifest.jinja"),
        mimetype="application/manifest+json",
    )
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@bp.get("/sw.js")
def service_worker():
    """O service worker, servido da RAIZ de proposito.

    O escopo de um service worker e a pasta em que ele mora: em /static/sw.js ele so
    enxergaria /static/ e nao veria a navegacao do painel. Por isso ele nao e um
    arquivo estatico — e uma rota.
    """
    precache, version_mark = panel._shell_files()
    resp = panel.app.response_class(
        render_template("sw.js.jinja", versao=version_mark, precache=precache),
        mimetype="text/javascript",
    )
    # Sem isto o proprio arquivo do worker ficaria em cache e o painel nunca
    # descobriria que existe uma versao nova dele.
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["Service-Worker-Allowed"] = "/"
    return resp


@bp.get("/offline")
def offline():
    """Tela de "sem conexao", guardada no aparelho junto com o casco.

    Nao exige login: ela e servida do cache, sem passar pelo servidor, e nao mostra
    dado nenhum — so explica o que aconteceu e oferece "tentar de novo".
    """
    return render_template("offline.html")
