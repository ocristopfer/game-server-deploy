# FAKE game container, only for testing the panel locally.
# It installs neither SteamCMD nor any game: it has sshd, a fake systemctl/journalctl and
# the .ini files the real game would create.
#
# On purpose it has NO curl: the real game container does (see
# docker/gameserver/Dockerfile and provision-game-lxc.sh), so leaving this image with only
# python3 makes the local environment exercise the fallback path of the HTTP player count.
# Full python3, not python3-minimal: minimal ships neither http.server nor urllib.
#
# sudo + lib/ct-panel-access.sh: with GAME_SSH_USER=gamepanel the container runs in helper mode
# (the panel logs in as gamepanel, root SSH is refused), the same piece a real CT gets. The lib
# comes from the `lib` build context (docker-compose.yml, additional_contexts): the build context
# stays this folder, and the piece is the repository's own file, never a copy that drifts.
FROM debian:13-slim

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      openssh-server ca-certificates procps psmisc coreutils findutils \
      htop nano vim-tiny less tree file python3 sudo \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --shell /bin/bash steam

# The files come in as *.sh (.gitattributes guarantees LF) and become the commands the
# panel expects to find in the container.
COPY fake-systemctl.sh   /usr/local/bin/systemctl
COPY fake-journalctl.sh  /usr/local/bin/journalctl
COPY fake-game-loop.sh   /usr/local/bin/fake-game-loop
COPY fake-update-game.sh /usr/local/bin/update-game
COPY fake-check-update.sh /usr/local/bin/check-game-update
COPY fake-a2s.py         /usr/local/bin/fake-a2s
COPY fake-restapi.py     /usr/local/bin/fake-restapi
COPY entrypoint.sh       /usr/local/bin/game-entrypoint
COPY --from=lib ct-panel-access.sh /usr/local/lib/gamepanel/ct-panel-access.sh
RUN chmod 0755 /usr/local/bin/systemctl /usr/local/bin/journalctl \
      /usr/local/bin/fake-game-loop /usr/local/bin/update-game \
      /usr/local/bin/check-game-update /usr/local/bin/fake-a2s \
      /usr/local/bin/fake-restapi /usr/local/bin/game-entrypoint \
      /usr/local/lib/gamepanel/ct-panel-access.sh

EXPOSE 22
ENTRYPOINT ["/usr/local/bin/game-entrypoint"]
