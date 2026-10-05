#!/bin/sh
# Starts the panel in the container: SSH key, admin user and (only in the development
# environment) the two test servers already registered.
#
# PANEL_SEED_DEMO=1  -> registers the fake containers from docker-compose.yml
# GAMEPANEL_DEV=1    -> gunicorn with --reload (the code comes by bind mount)
set -e

install -d -m 0755 /var/lib/gamepanel /etc/gamepanel /keys

if [ ! -f "$GAMEPANEL_SSH_KEY" ]; then
  echo "==> gerando a chave SSH do painel"
  ssh-keygen -t ed25519 -N '' -C 'gamepanel@docker' -f "$GAMEPANEL_SSH_KEY" >/dev/null
fi
# The game containers read from here when building authorized_keys.
cp -f "${GAMEPANEL_SSH_KEY}.pub" /keys/panel.pub
touch "$GAMEPANEL_KNOWN_HOSTS"

echo "==> garantindo o usuario ${PANEL_USER:-admin}"
python3 -m gamepanel.app --create-user "${PANEL_USER:-admin}" \
  --password "${PANEL_PASSWORD:-admin12345}"

if [ "${PANEL_SEED_DEMO:-0}" = "1" ]; then
  echo "==> cadastrando os servidores de teste (PANEL_SEED_DEMO=1)"
  python3 - <<'PY'
import sys

sys.path.insert(0, "/opt/gamepanel")
from gamepanel import app as panel  # noqa: E402  (the import already creates/migrates the database)

SEEDS = [
    # No player_source: the panel infers a2s from the query port. The fake REST API
    # (127.0.0.1:8212, admin/troque-me) waits under Configurar contagem > API HTTP.
    # Helper mode (GAME_SSH_USER=gamepanel in docker-compose.yml): root SSH is refused there.
    # ensure_server also UPDATES an existing row, so an old dev database switches over too.
    dict(name="Palworld (teste)", host="game-palworld", service="palworld.service",
         ssh_user="gamepanel",
         game_port="8211/udp", query_port=27015,
         config_path="/opt/game/Pal/Saved/Config/LinuxServer",
         config_files="/opt/game/Pal/Saved/Config/LinuxServer/PalWorldSettings.ini",
         notes="Container de teste do docker compose."),
    # No query port: this one mimics the game that can only be counted through the log.
    # Legacy mode: the panel still logs in as root here, on purpose (see docker-compose.yml).
    dict(name="Dragonwilds (teste)", host="game-dragonwilds", service="dragonwilds.service",
         ssh_user="root",
         game_port="7777/udp", query_port=0,
         config_path="/opt/game/RSDragonwilds/Saved/Config/LinuxServer",
         config_files="/opt/game/RSDragonwilds/Saved/Config/LinuxServer/DedicatedServer.ini",
         notes="Container de teste do docker compose."),
]

for seed in SEEDS:
    criado = panel.ensure_server(panel.DeployServer(**seed))
    print(f"servidor de teste {'cadastrado' if criado else 'ja existia'}: {seed['name']}")
PY
fi

echo "==> painel em http://localhost:${GAMEPANEL_PORT} (usuario ${PANEL_USER:-admin})"
if [ "${GAMEPANEL_DEV:-0}" = "1" ]; then
  exec gunicorn --workers 1 --threads 16 --timeout 120 --reload \
    --bind "0.0.0.0:${GAMEPANEL_PORT}" --access-logfile - gamepanel.wsgi:app
fi
exec gunicorn --workers 1 --threads 16 --timeout 120 \
  --bind "0.0.0.0:${GAMEPANEL_PORT}" --access-logfile - gamepanel.wsgi:app
