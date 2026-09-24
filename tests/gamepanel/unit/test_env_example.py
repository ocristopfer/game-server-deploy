"""O `.env.example` tem de passar no `source` do bash.

Ele nao e lido so pelo PowerShell: os tres `provision-*-lxc.sh` fazem `source` de um
arquivo de ambiente no `load_env_file`, e quem roda o provisionamento a mao passa o
proprio `.env` (copiado deste exemplo) direto.

O defeito que motivou este arquivo: `UPDATE_SCHEDULE=*-*-* 06:00:00`, sem aspas. Para o
bash isso nao e um valor com espaco -- e a atribuicao `UPDATE_SCHEDULE=*-*-*` seguida do
COMANDO `06:00:00`. Duas consequencias, as duas caladas: a variavel fica com metade do
valor (um agendamento do systemd sem horario), e o comando inexistente devolve 127 --
que com o `set -Eeuo pipefail` dos provisionamentos aborta o deploy no PRIMEIRO passo.

E a mesma regra que o CLAUDE.md ja cobra de `games/*.env`, aqui na raiz.
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[3]

# KEY=valor, so o que o bash leria como atribuicao no comeco da linha.
ASSIGNMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def _value_as_bash_sees_it(raw: str) -> str:
    """Tira o comentario de fim de linha, que o bash descarta antes de tudo.

    So conta como comentario o `#` precedido de espaco (ou no comeco): `VALOR#1` e valor,
    e nao valor com comentario -- e por isso que a checagem nao pode ser um `split('#')`.
    """
    without_comment = re.split(r"(?:^|\s)#", raw, maxsplit=1)[0]
    return without_comment.strip()


def test_nenhum_valor_do_exemplo_tem_espaco_sem_aspas():
    lines = (REPO / ".env.example").read_text(encoding="utf-8").splitlines()
    broken: list[str] = []
    for number, line in enumerate(lines, start=1):
        match = ASSIGNMENT.match(line)
        if not match:
            continue
        value = _value_as_bash_sees_it(match.group(2))
        if not value or value[0] in "\"'":
            continue
        if re.search(r"\s", value):
            broken.append(f'linha {number}: {match.group(1)}={value!r}')
    assert not broken, (
        "valor com espaco e sem aspas: o bash le o resto como COMANDO e o provisionamento"
        " morre com 127 no load_env_file.\n  " + "\n  ".join(broken))
