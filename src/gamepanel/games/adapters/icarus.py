"""Campos de configuracao de Icarus (le ServerSettings.ini)."""
from __future__ import annotations

import re

from gamepanel.games.base import LABEL_ADMIN_PASSWORD, LABEL_JOIN_PASSWORD, LABEL_NAME, FieldSpec, flag

# O painel escolhe o catalogo pelo NOME do arquivo, que e o mesmo criterio
# que ele ja usa para escolher o leitor.
FILENAME = re.compile(r"^ServerSettings\.ini$", re.I)

# ----------------------------------------------- Icarus (le ServerSettings.ini)
FIELDS = {
    "SessionName": FieldSpec(LABEL_NAME, "Como ele aparece no navegador de servidores."),
    "JoinPassword": FieldSpec(LABEL_JOIN_PASSWORD, "Vazio = qualquer um entra.", kind="password"),
    "AdminPassword": FieldSpec(LABEL_ADMIN_PASSWORD, "Da acesso aos comandos de administrador no jogo.",
                               kind="password"),
    "MaxPlayers": FieldSpec("Vagas", "Maximo de jogadores simultaneos.",
                            kind="number", minimum=1, maximum=64, step=1),
    "AllowNonAdminsToLaunchProspects": flag(
        "Jogador comum pode iniciar prospect",
        "Desligado, so admin escolhe qual missao (prospect) roda no servidor."),
    "AllowNonAdminsToDeleteProspects": flag(
        "Jogador comum pode apagar prospect", "Cuidado: apagar prospect apaga o progresso dele."),
    "ShutdownIfNotJoinedFor": FieldSpec(
        "Desliga se ninguem entrar", "Segundos sem NENHUMA conexao ate o servidor se encerrar. "
                                     "O systemd reinicia logo depois; aumente para manter de pe.",
        kind="number", minimum=0, maximum=86400, step=60, unit="s"),
    "ShutdownIfEmptyFor": FieldSpec(
        "Desliga ao ficar vazio", "Segundos com o servidor vazio ate ele se encerrar.",
        kind="number", minimum=0, maximum=86400, step=60, unit="s"),
    "ResumeProspect": flag("Retomar prospect",
                            "Ligado, o servidor volta sozinho para a missao que estava rodando."),
    "LoadProspect": FieldSpec("Prospect a carregar", "Nome do prospect salvo que deve ser aberto."),
    "CreateProspect": FieldSpec("Prospect a criar", "Cria uma missao nova com este nome ao subir."),
    "LastProspectName": FieldSpec("Ultimo prospect",
                                  "Preenchido pelo proprio jogo. Nao edite a mao."),
}
