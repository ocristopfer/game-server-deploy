# Toy broker - DEVELOPMENT image (gamebroker/dev.py: fake backends).
# It is not the production broker image, which runs in its own CT with the real Proxmox and
# OPNsense. Same dependencies it will have: only python3-flask from apt, no pip.
FROM debian:13-slim

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-flask ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/gamebroker
EXPOSE 8090
# The `gamebroker/` package and the `games/` catalog come in by bind mount (see docker-compose.yml).
CMD ["python3", "-m", "gamebroker.dev"]
