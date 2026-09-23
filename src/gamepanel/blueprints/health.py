"""Sonda de saude, sem sessao: e o que um balanceador ou o deploy pergunta."""
from __future__ import annotations

from flask import Blueprint, jsonify

from gamepanel import version

bp = Blueprint("health", __name__)


@bp.get("/health")
def health():
    """Alem do "de pe", QUAL codigo esta de pe.

    O deploy publica um release e pergunta aqui se a versao que voltou e a que ele
    acabou de mandar. Sem isso, "o servico subiu" e compativel com "o systemd reiniciou
    a versao velha porque a nova nem foi importada" — e os dois casos mostram a mesma
    tela verde. Nao ha sessao nesta rota, entao o que sai e so identidade de codigo:
    nenhum caminho, nenhum endereco, nenhum nome de usuario.
    """
    return jsonify({"status": "ok", **version.BUILD.as_public()})
