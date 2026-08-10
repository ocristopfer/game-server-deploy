# Container de jogo FALSO, so para testar o painel local.
# Nao instala SteamCMD nem jogo nenhum: tem sshd, um systemctl/journalctl de mentira e
# os arquivos .ini que o jogo de verdade criaria.
FROM debian:13-slim

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      openssh-server ca-certificates procps psmisc coreutils findutils \
      htop nano vim-tiny less tree file python3-minimal \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --shell /bin/bash steam

# Os arquivos entram como *.sh (o .gitattributes garante LF) e viram os comandos que o
# painel espera encontrar no container.
COPY fake-systemctl.sh   /usr/local/bin/systemctl
COPY fake-journalctl.sh  /usr/local/bin/journalctl
COPY fake-game-loop.sh   /usr/local/bin/fake-game-loop
COPY fake-update-game.sh /usr/local/bin/update-game
COPY fake-check-update.sh /usr/local/bin/check-game-update
COPY fake-a2s.py         /usr/local/bin/fake-a2s
COPY entrypoint.sh       /usr/local/bin/game-entrypoint
RUN chmod 0755 /usr/local/bin/systemctl /usr/local/bin/journalctl \
      /usr/local/bin/fake-game-loop /usr/local/bin/update-game \
      /usr/local/bin/check-game-update /usr/local/bin/fake-a2s \
      /usr/local/bin/game-entrypoint

EXPOSE 22
ENTRYPOINT ["/usr/local/bin/game-entrypoint"]
