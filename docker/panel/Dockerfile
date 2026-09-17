# Painel administrativo - imagem de desenvolvimento.
# Mesmas dependencias do container LXC de producao (provision-admin-lxc.sh), so que
# o codigo entra por bind mount em vez de copia.
FROM debian:13-slim

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      python3 python3-flask gunicorn openssh-client ca-certificates \
      python3-pytest \
 && rm -rf /var/lib/apt/lists/*
# python3-pytest e SO desta imagem de desenvolvimento: as sete suites de teste do
# painel (admin/test_*.py) usam pytest, e este e o container onde elas rodam contra
# Python de verdade. O painel em si nunca importa pytest - por isso ele fica de fora
# do Dockerfile.prod e do provision-admin-lxc.sh, que sao a imagem que roda de fato.

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
