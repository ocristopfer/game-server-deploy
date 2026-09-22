"""Application factory do painel.

Esqueleto minimo da Fase 3 (etapa 2): valida que o layout src/gamepanel/
resolve import em producao (gunicorn, sem pip install, so PYTHONPATH) antes
de mover as 8175 linhas de admin/app.py pra ca (etapa 5). O conteudo de
verdade (rotas, banco, SSH, etc.) ainda mora em admin/app.py.
"""

from flask import Flask


def create_app() -> Flask:
    app = Flask(__name__)

    @app.get("/health")
    def health() -> tuple[dict[str, bool], int]:
        return {"ok": True}, 200

    return app
