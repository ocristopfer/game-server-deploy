"""A POLITICA do historico: como cada acao se chama e quem pode ler a saida dela.

Sem Flask e sem SQL. O que dispara um job (thread, SSH, banco) fica no `app.py`, porque
depende da conexao por requisicao e do `g`; o que esta aqui e a decisao, que e pura e
por isso testavel sem subir nada.

Duas listas moram aqui porque as tres telas que as usam (historico do servidor,
historico geral e a rota de API) TEM de concordar. Escritas em cada consulta, uma delas
um dia deixa passar o que as outras escondem.
"""
from __future__ import annotations

from collections.abc import Mapping

# Acao -> chave de catalogo. CHAVE e nunca texto pronto: o historico e uma tela como as
# outras e segue o idioma de quem a abriu (ver `i18n`).
EXTRA_LABELS: Mapping[str, str] = {
    "shell": "job.shell",
    "terminal": "job.terminal",
    "edit-file": "job.file_saved",
    "delete-file": "job.file_deleted",
    "edit-config": "job.config_changed",
    "download-file": "job.file_downloaded",
    "upload-file": "job.file_uploaded",
    "backup": "job.backup",
    "restore-backup": "job.backup_restored",
    "delete-backup": "job.backup_deleted",
    # Moderacao nao da root em container nenhum: e operacao, e fica visivel ao operador.
    "player-action": "job.player_action",
    "broker-criar": "job.instance_created",
    "broker-desativar": "job.instance_deactivated",
    "broker-remover": "job.instance_removed",
    "broker-jogo": "job.game_added",
}

# O historico guarda a saida INTEIRA do que rodou. Estas acoes so um admin consegue
# disparar (console, terminal, editor de arquivos), entao a saida delas — que carrega o
# comando digitado, o conteudo do arquivo e o que mais tenha passado pela tela — tambem
# so ele pode ler. Sem esta lista, o operador que leva 403 no console leria o resultado
# do console abrindo o job pelo id.
ADMIN_ONLY_ACTIONS = frozenset({
    "shell", "terminal", "edit-file", "delete-file", "download-file",
    # 'backup' fica de fora: criar copia e operacao, e o operador pode dispara-la. Ja
    # restaurar e apagar destroem dado, e baixar tira o save do container — sao de admin,
    # e o registro delas acompanha.
    "upload-file", "restore-backup", "delete-backup",
    # Tudo do broker e de admin: a saida cita IP, CTID e portas da infraestrutura.
    "broker-criar", "broker-desativar", "broker-remover", "broker-jogo",
    # 'edit-config' fica de fora de proposito: mexer na configuracao do jogo e coisa de
    # operador, e a saida dela nao passa disso.
})


def labels(action_labels: Mapping[str, str]) -> dict[str, str]:
    """Junta os rotulos das acoes de botao com os das que nascem de outras telas."""
    return {**action_labels, **EXTRA_LABELS}


def is_restricted(action: str) -> bool:
    return action in ADMIN_ONLY_ACTIONS


def hidden_filter(is_admin: bool) -> tuple[str, tuple[str, ...]]:
    """Pedaco de WHERE que esconde do operador os jobs das acoes restritas.

    Devolve `("", ())` para o admin: sem clausula nenhuma, e nao uma que aceita tudo —
    assim a consulta do admin nao paga por um `NOT IN` com doze valores.
    """
    if is_admin:
        return "", ()
    hidden = tuple(sorted(ADMIN_ONLY_ACTIONS))
    markers = ",".join("?" * len(hidden))
    return f" AND action NOT IN ({markers})", hidden
