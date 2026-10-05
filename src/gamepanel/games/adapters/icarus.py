"""Configuration fields for Icarus (reads ServerSettings.ini)."""
from __future__ import annotations

import re

from gamepanel.games.base import LABEL_ADMIN_PASSWORD, LABEL_JOIN_PASSWORD, LABEL_NAME, FieldSpec, flag

# The panel picks the catalog by the file NAME, which is the same criterion
# it already uses to pick the reader.
FILENAME = re.compile(r"^ServerSettings\.ini$", re.I)

# ----------------------------------------------- Icarus (reads ServerSettings.ini)
FIELDS = {
    "SessionName": FieldSpec(LABEL_NAME, "Como ele aparece no navegador de servidores."),
    "JoinPassword": FieldSpec(LABEL_JOIN_PASSWORD, "Vazio = qualquer um entra.", kind="password"),
    "AdminPassword": FieldSpec(LABEL_ADMIN_PASSWORD, "Dá acesso aos comandos de administrador no jogo.",
                               kind="password"),
    "MaxPlayers": FieldSpec("Vagas", "Máximo de jogadores simultâneos.",
                            kind="number", minimum=1, maximum=64, step=1),
    "AllowNonAdminsToLaunchProspects": flag(
        "Jogador comum pode iniciar prospect",
        "Desligado, só admin escolhe qual missão (prospect) roda no servidor."),
    "AllowNonAdminsToDeleteProspects": flag(
        "Jogador comum pode apagar prospect", "Cuidado: apagar prospect apaga o progresso dele."),
    "ShutdownIfNotJoinedFor": FieldSpec(
        "Desliga se ninguém entrar", "Segundos sem NENHUMA conexão até o servidor se encerrar. "
                                     "O systemd reinicia logo depois; aumente para manter de pé.",
        kind="number", minimum=0, maximum=86400, step=60, unit="s"),
    "ShutdownIfEmptyFor": FieldSpec(
        "Desliga ao ficar vazio", "Segundos com o servidor vazio até ele se encerrar.",
        kind="number", minimum=0, maximum=86400, step=60, unit="s"),
    "ResumeProspect": flag("Retomar prospect",
                            "Ligado, o servidor volta sozinho para a missão que estava rodando."),
    "LoadProspect": FieldSpec("Prospect a carregar", "Nome do prospect salvo que deve ser aberto."),
    "CreateProspect": FieldSpec("Prospect a criar", "Cria uma missão nova com este nome ao subir."),
    "LastProspectName": FieldSpec("Último prospect",
                                  "Preenchido pelo próprio jogo. Não edite à mão."),
}
