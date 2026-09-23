"""Sonda de saude, sem sessao: e o que um balanceador ou o deploy pergunta."""
from __future__ import annotations

from flask import Blueprint, jsonify

bp = Blueprint("health", __name__)


@bp.get("/health")
def health():
    return jsonify({"status": "ok"})
