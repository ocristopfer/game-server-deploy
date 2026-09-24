"""Caminho do codigo VIVO no CT: sempre sob `current`, nunca o pacote direto em APP_DIR.

Desde que release virou pasta por versao, o codigo que o CT executa mora em
`/opt/<pacote>/current/<pacote>/`. `/opt/<pacote>/<pacote>/` e o layout ANTERIOR, e depois
da migracao ele simplesmente nao existe mais no CT.

Isso ja envelheceu em tres lugares de uma vez, e nenhum deles falha de forma visivel:

- a sonda do atalho de `deploy-admin.ps1` (`test -f .../gamepanel/app.py`) passou a dar
  errado SEMPRE, e todo deploy incremental virou um provisionamento completo em silencio --
  que passa pelo Proxmox, roda apt e redefine a senha do admin a cada vez;
- o cadastro do servidor no fim de `deploy-game.ps1` ficou apontando para um arquivo que
  nao existe: o deploy imprime "painel nao encontrado" e segue SEM cadastrar (o comentario
  de la registra que isso ja tinha acontecido uma vez, quando o codigo foi para `src/`);
- a doc mandava rodar `python3 /opt/gamepanel/gamepanel/app.py --reset-2fa`, que e a saida
  de emergencia de quem esta trancado FORA do painel -- a hora mais ruim para descobrir que
  o caminho mudou.

Nenhuma ferramenta liga um caminho escrito dentro de uma string de shell ao layout que o
instalador produz, e nao ha sintaxe errada em nenhum dos tres.
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[3]

# `/opt/gamepanel/gamepanel`, `/opt/gamebroker/gamebroker`: o pacote DIRETO em APP_DIR.
OLD_LAYOUT = re.compile(r"/opt/(gamepanel|gamebroker)/\1(?:/|\b)")

SCANNED = ("deploy/**/*.ps1", "deploy/**/*.sh", "lib/*.sh", "CLAUDE.md", "README.md")

# O painel em DOCKER nao tem release por versao: o `Dockerfile.prod` copia o pacote para
# dentro da imagem e o container e substituido inteiro em vez de ganhar uma pasta de versao.
# Ali o layout anterior e o layout certo. O que isenta e FALAR de docker -- na linha ou no
# nome do arquivo, e nao uma lista de arquivos escrita a mao, que envelheceria igual ao
# caminho que este teste guarda. O nome conta porque a linha que invoca o container nao
# repete a palavra (`"exec", $PanelContainer, ...`): quem a diz e o `deploy-docker.ps1`.
DOCKER_WORDS = ("docker", "compose", "dockerfile", "bind mount")


def _offenders() -> list[str]:
    found: list[str] = []
    for pattern in SCANNED:
        for path in sorted(REPO.glob(pattern)):
            for number, line in enumerate(
                    path.read_text(encoding="utf-8").splitlines(), start=1):
                if not OLD_LAYOUT.search(line):
                    continue
                relative = path.relative_to(REPO).as_posix()
                haystack = (line + " " + relative).lower()
                if any(word in haystack for word in DOCKER_WORDS):
                    continue
                found.append(f"{relative}:{number}: {line.strip()[:100]}")
    return found


def test_a_varredura_encontra_os_caminhos_do_docker():
    """Se o padrao parar de casar, o teste acima passa sem conferir nada.

    O caminho antigo EXISTE de proposito no deploy em Docker, entao ele serve de controle:
    achar zero ocorrencia em lugar nenhum significa que a expressao quebrou.
    """
    every = []
    for pattern in SCANNED:
        for path in sorted(REPO.glob(pattern)):
            every += OLD_LAYOUT.findall(path.read_text(encoding="utf-8"))
    assert every, "a expressao do layout antigo nao casa mais nada: ela ainda esta certa?"


def test_nenhum_script_de_deploy_aponta_para_o_layout_antigo():
    offenders = _offenders()
    assert not offenders, (
        "caminho do layout ANTERIOR ao release por versao (o codigo vivo esta sob"
        " `current/`):\n  " + "\n  ".join(offenders))
