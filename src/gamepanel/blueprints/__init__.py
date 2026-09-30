"""A camada HTTP do painel, uma tela por arquivo.

Cada modulo aqui so faz o trabalho de HTTP: ler o pedido, chamar quem decide e escolher
o template. A regra continua em `services/`, o acesso remoto em `runtime/` e a montagem
(banco, sessao, decoradores, tabelas) no `app.py`, que e o ponto onde tudo e ligado.

**Por que os blueprints chamam `panel.X` e nao importam a funcao direto.** Os testes
trocam funcao por falsa com `monkeypatch.setattr(panel, "server_status", ...)`, que
substitui o nome NO MODULO `gamepanel.app`. Um `from gamepanel.app import server_status`
aqui copiaria a referencia na hora do import, e a troca do teste deixaria de valer **em
silencio** — os testes passariam sem testar nada. Por isso todo acesso e
`panel.server_status(...)`, e por isso o `app.py` registra os blueprints no FIM do
arquivo, quando tudo o que eles chamam ja existe.
"""
from __future__ import annotations

from flask import Flask


def register_all(app: Flask) -> None:
    """Liga cada blueprint ao app. Chamado no rodape do `app.py`.

    O import mora DENTRO da funcao de proposito: no topo ele rodaria enquanto o
    `gamepanel.app` ainda esta sendo executado, e cada blueprint faria `import
    gamepanel.app` de um modulo pela metade.
    """
    from gamepanel.blueprints import (
        account,
        alerts,
        auth,
        backups,
        broker,
        charts,
        config_quick,
        console,
        dashboard,
        files,
        health,
        history,
        jobs,
        mods,
        players,
        pwa,
        schedules,
        servers,
        terminal,
        users,
    )

    for module in (
        account, alerts, auth, backups, broker, charts, config_quick, console,
        dashboard, files, health, history, jobs, mods, players, pwa, schedules, servers,
        terminal, users,
    ):
        app.register_blueprint(module.bp)
