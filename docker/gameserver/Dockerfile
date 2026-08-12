# Servidor de jogo DE VERDADE em Docker (o docker/game/ ao lado e o simulado do
# ambiente de desenvolvimento).
#
# A imagem e a mesma coisa que o provision-game-lxc.sh monta dentro do LXC: Debian +
# SteamCMD + sshd para o painel entrar + os atalhos que o painel chama (systemctl,
# journalctl, update-game, check-game-update). Nao ha systemd dentro de container, entao
# 'systemctl' aqui e um supervisor proprio com a MESMA interface que o painel usa.
#
# A definicao do jogo (games/<jogo>.env) entra na imagem em tempo de build, por isso o
# contexto de build e a RAIZ do repositorio:
#   docker build -f docker/gameserver/Dockerfile --build-arg GAME_ENV=games/palworld.env .
FROM debian:13-slim

# Qual jogo esta imagem instala. O deploy-docker.ps1 preenche isso.
ARG GAME_ENV=games/_template.env

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl tar xz-utils locales tzdata \
      openssh-server procps psmisc coreutils findutils util-linux \
      lib32gcc-s1 lib32stdc++6 \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --shell /bin/bash steam

# SteamCMD ja vem na imagem: o container sobe direto para o download do jogo.
RUN install -d /opt/steamcmd \
 && curl -fsSL https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz \
    | tar -xz -C /opt/steamcmd \
 && chown -R steam:steam /opt/steamcmd

# Os arquivos entram como *.sh (o .gitattributes garante LF) e viram os comandos que o
# painel espera encontrar no container.
COPY docker/gameserver/systemctl.sh      /usr/local/bin/systemctl
COPY docker/gameserver/journalctl.sh     /usr/local/bin/journalctl
COPY docker/gameserver/supervisor.sh     /usr/local/bin/game-supervisor
COPY docker/gameserver/update-game.sh    /usr/local/bin/update-game
COPY docker/gameserver/check-update.sh   /usr/local/bin/check-game-update
COPY docker/gameserver/autoupdate.sh     /usr/local/bin/game-autoupdate
COPY docker/gameserver/game-ctl.sh       /usr/local/bin/game-ctl
COPY docker/gameserver/entrypoint.sh     /usr/local/bin/game-entrypoint
RUN chmod 0755 /usr/local/bin/systemctl /usr/local/bin/journalctl \
      /usr/local/bin/game-supervisor /usr/local/bin/update-game \
      /usr/local/bin/check-game-update /usr/local/bin/game-autoupdate \
      /usr/local/bin/game-ctl /usr/local/bin/game-entrypoint \
 && for atalho in game-start game-stop game-restart game-status game-logs; do \
      printf '#!/bin/sh\nexec game-ctl %s "$@"\n' "${atalho#game-}" > "/usr/local/bin/$atalho"; \
      chmod 0755 "/usr/local/bin/$atalho"; \
    done

COPY ${GAME_ENV} /etc/game/game.env

# /opt/game (jogo) e /home/steam (token da Steam, prefixo do Wine) sao os volumes:
# recriar o container nao pode significar baixar tudo de novo.
VOLUME ["/opt/game", "/home/steam"]
EXPOSE 22
ENTRYPOINT ["/usr/local/bin/game-entrypoint"]
