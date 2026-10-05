# Admin panel - development image.
# Same dependencies as the production LXC container (provision-admin-lxc.sh), except
# that the code comes in by bind mount instead of being copied.
FROM debian:13-slim

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      python3 python3-flask gunicorn openssh-client ca-certificates \
      python3-pytest \
 && rm -rf /var/lib/apt/lists/*
# python3-pytest is ONLY in this development image: the panel's seven test suites
# (admin/test_*.py) use pytest, and this is the container where they run against
# real Python. The panel itself never imports pytest - that is why it is left out
# of Dockerfile.prod and provision-admin-lxc.sh, which are the image that actually runs.

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
