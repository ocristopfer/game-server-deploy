"""O historico do painel: tudo o que aconteceu, de todos os servidores."""
from __future__ import annotations

from flask import Blueprint, render_template, request

from gamepanel import app as panel

bp = Blueprint("history", __name__)


@bp.get("/history")
@panel.login_required
def index():
    """Tudo o que aconteceu no painel, de todos os servidores.

    O historico por servidor mostra os ultimos 15; e aqui que se responde "quem mexeu
    nisso" e "o que o agendador andou fazendo".
    """
    conn = panel.db()
    servers = conn.execute(panel.SQL_ALL_SERVERS).fetchall()
    nomes = {int(s["id"]): s["name"] for s in servers}

    filtro_srv = (request.args.get("servidor", "") or "").strip()
    filtro_acao = (request.args.get("acao", "") or "").strip()
    filtro_user = (request.args.get("usuario", "") or "").strip()[:80]
    try:
        pagina = max(0, int(request.args.get("p", "0")))
    except ValueError:
        pagina = 0

    onde, valores = ["1 = 1"], []
    if filtro_srv.isdigit():
        onde.append("server_id = ?")
        valores.append(int(filtro_srv))
    if filtro_acao in panel.JOB_LABELS:
        onde.append("action = ?")
        valores.append(filtro_acao)
    if filtro_user:
        onde.append("username = ?")
        valores.append(filtro_user)

    corte, escondidas = panel.role_filter()
    sql_onde = " AND ".join(onde) + corte
    valores.extend(escondidas)

    # Pede um a mais que o tamanho da pagina: e como se sabe se existe proxima sem contar
    # a tabela inteira.
    lines_of = conn.execute(
        f"SELECT * FROM jobs WHERE {sql_onde} ORDER BY id DESC LIMIT ? OFFSET ?",
        (*valores, panel.HISTORY_PAGE + 1, pagina * panel.HISTORY_PAGE),
    ).fetchall()
    tem_mais = len(lines_of) > panel.HISTORY_PAGE
    jobs = lines_of[:panel.HISTORY_PAGE]

    usuarios = [r[0] for r in conn.execute(
        f"SELECT DISTINCT username FROM jobs WHERE username <> '' {corte} ORDER BY username",
        escondidas,
    ).fetchall()]

    return render_template(
        "history.html", jobs=jobs, servers=servers, nomes=nomes, usuarios=usuarios,
        acoes=sorted(panel.JOB_LABELS), filtro_srv=filtro_srv, filtro_acao=filtro_acao,
        filtro_user=filtro_user, pagina=pagina, tem_mais=tem_mais,
        manter_dias=panel.JOBS_KEEP_DAYS,
    )
