# Painel administrativo - imagem de desenvolvimento.
# Mesmas dependencias do container LXC de producao (provision-admin-lxc.sh), so que
# o codigo entra por bind mount em vez de copia.
FROM debian:13-slim

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      python3 python3-flask gunicorn openssh-client ca-certificates \
 && rm -rf /var/lib/apt/lists/*

ENV GAMEPANEL_DB=/var/lib/gamepanel/panel.db \
    GAMEPANEL_SECRET_FILE=/etc/gamepanel/secret_key \
    GAMEPANEL_SSH_KEY=/etc/gamepanel/id_ed25519 \
    GAMEPANEL_KNOWN_HOSTS=/var/lib/gamepanel/known_hosts \
    GAMEPANEL_PORT=8080

COPY entrypoint.sh /usr/local/bin/panel-entrypoint
RUN chmod 0755 /usr/local/bin/panel-entrypoint

WORKDIR /opt/gamepanel
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/panel-entrypoint"]
