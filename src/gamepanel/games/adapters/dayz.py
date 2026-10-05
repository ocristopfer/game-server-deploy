"""Configuration fields for DayZ (reads serverDZ.cfg)."""
from __future__ import annotations

import re

from gamepanel.games.base import LABEL_ADMIN_PASSWORD, LABEL_JOIN_PASSWORD, LABEL_NAME, FieldSpec

# The panel picks the catalog by the file NAME, which is the same criterion
# it already uses to pick the reader.
FILENAME = re.compile(r"^serverDZ\.cfg$", re.I)

# --------------------------------------------------- DayZ (reads serverDZ.cfg)
FIELDS = {
    "hostname": FieldSpec(LABEL_NAME, "Como aparece no navegador de servidores."),
    "password": FieldSpec(LABEL_JOIN_PASSWORD, "Vazio = servidor aberto.", kind="password"),
    "passwordAdmin": FieldSpec(LABEL_ADMIN_PASSWORD, "Acesso ao console remoto. TROQUE antes de expor.",
                               kind="password"),
    "maxPlayers": FieldSpec("Vagas", "Máximo de jogadores simultâneos.",
                            kind="number", minimum=1, maximum=127, step=1),
    "steamQueryPort": FieldSpec("Porta de consulta",
                                "Sem ela o servidor não aparece no navegador do cliente. "
                                "Precisa bater com o que está liberado no roteador.",
                                kind="number", minimum=1024, maximum=65535, step=1),
    "verifySignatures": FieldSpec("Verificar assinaturas",
                                  "2 = só aceita mods assinados. Deixe em 2.",
                                  kind="number", minimum=0, maximum=2, step=1),
    "forceSameBuild": FieldSpec("Mesma versão", "1 = cliente precisa estar na mesma versão do servidor.",
                                kind="number", minimum=0, maximum=1, step=1),
    "disable3rdPerson": FieldSpec("Somente 1a pessoa", "1 = servidor apenas em primeira pessoa.",
                                  kind="number", minimum=0, maximum=1, step=1),
    "disableVoN": FieldSpec("Desligar voz", "0 = voz habilitada.",
                            kind="number", minimum=0, maximum=1, step=1),
    "serverTimeAcceleration": FieldSpec(
        "Aceleração do tempo", "12 = um dia do jogo a cada 2 horas reais.",
        kind="number", minimum=0, maximum=64, step=1, unit="x"),
    "instanceId": FieldSpec("ID da instância", "Define a pasta storage_<id> da persistência."),
}
