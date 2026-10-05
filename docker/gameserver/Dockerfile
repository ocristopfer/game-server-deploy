# REAL game server in Docker (docker/game/ next to it is the simulated one of the
# development environment).
#
# The image is the same thing provision-game-lxc.sh builds inside the LXC: Debian +
# SteamCMD + sshd for the panel to log in + the shortcuts the panel calls (systemctl,
# journalctl, update-game, check-game-update). There is no systemd inside a container, so
# 'systemctl' here is our own supervisor with the SAME interface the panel uses.
#
# The game definition (games/<game>.env) goes into the image at build time, which is why
# the build context is the repository ROOT:
#   docker build -f docker/gameserver/Dockerfile --build-arg GAME_ENV=games/palworld.env .
FROM debian:13-slim

# Which game this image installs. deploy-docker.ps1 fills this in.
ARG GAME_ENV=games/_template.env

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl tar xz-utils locales tzdata \
      openssh-server procps psmisc coreutils findutils util-linux \
      lib32gcc-s1 lib32stdc++6 sudo \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --shell /bin/bash steam

# SteamCMD already ships in the image: the container goes straight to downloading the game.
RUN install -d /opt/steamcmd \
 && curl -fsSL https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz \
    | tar -xz -C /opt/steamcmd \
 && chown -R steam:steam /opt/steamcmd

# The files come in as *.sh (.gitattributes guarantees LF) and become the commands the
# panel expects to find in the container.
COPY docker/gameserver/systemctl.sh      /usr/local/bin/systemctl
COPY docker/gameserver/journalctl.sh     /usr/local/bin/journalctl
COPY docker/gameserver/supervisor.sh     /usr/local/bin/game-supervisor
COPY docker/gameserver/update-game.sh    /usr/local/bin/update-game
COPY docker/gameserver/check-update.sh   /usr/local/bin/check-game-update
COPY docker/gameserver/autoupdate.sh     /usr/local/bin/game-autoupdate
COPY docker/gameserver/game-ctl.sh       /usr/local/bin/game-ctl
COPY docker/gameserver/entrypoint.sh     /usr/local/bin/game-entrypoint
# The panel logs in as gamepanel (sudo for gp-service/update-game, steam for files) and root SSH
# is refused. Same piece a real CT gets; the entrypoint runs it once the panel key is known.
COPY lib/ct-panel-access.sh              /usr/local/lib/gamepanel/ct-panel-access.sh
RUN chmod 0755 /usr/local/bin/systemctl /usr/local/bin/journalctl \
      /usr/local/bin/game-supervisor /usr/local/bin/update-game \
      /usr/local/bin/check-game-update /usr/local/bin/game-autoupdate \
      /usr/local/bin/game-ctl /usr/local/bin/game-entrypoint \
      /usr/local/lib/gamepanel/ct-panel-access.sh \
 && for atalho in game-start game-stop game-restart game-status game-logs; do \
      printf '#!/bin/sh\nexec game-ctl %s "$@"\n' "${atalho#game-}" > "/usr/local/bin/$atalho"; \
      chmod 0755 "/usr/local/bin/$atalho"; \
    done

COPY ${GAME_ENV} /etc/game/game.env

# /opt/game (game) and /home/steam (Steam token, Wine prefix) are the volumes:
# recreating the container must not mean downloading everything again. The panel's backups
# and the Mods screen's environment overlay (lib/ct-panel-access.sh) are volumes too: without
# them a redeploy deleted every backup, and a loader installed in /opt/game stayed on disk but
# silently stopped loading (its LD_PRELOAD/Wine setting lived in the container's /etc).
VOLUME ["/opt/game", "/home/steam", "/var/backups/gamepanel", "/etc/gamepanel/game-env"]
EXPOSE 22
ENTRYPOINT ["/usr/local/bin/game-entrypoint"]
