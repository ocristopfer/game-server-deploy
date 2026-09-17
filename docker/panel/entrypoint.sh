#!/bin/sh
# Sobe o painel no container: chave SSH, usuario admin e (so no ambiente de
# desenvolvimento) os dois servidores de teste ja cadastrados.
#
# PANEL_SEED_DEMO=1  -> cadastra os containers falsos do docker-compose.yml
# GAMEPANEL_DEV=1    -> gunicorn com --reload (o codigo vem por bind mount)
set -e

install -d -m 0755 /var/lib/gamepanel /etc/gamepanel /keys

if [ ! -f "$GAMEPANEL_SSH_KEY" ]; then
  echo "==> gerando a chave SSH do painel"
  ssh-keygen -t ed25519 -N '' -C 'gamepanel@docker' -f "$GAMEPANEL_SSH_KEY" >/dev/null
fi
# Os containers de jogo leem daqui na hora de montar o authorized_keys.
cp -f "${GAMEPANEL_SSH_KEY}.pub" /keys/panel.pub
touch "$GAMEPANEL_KNOWN_HOSTS"

echo "==> garantindo o usuario ${PANEL_USER:-admin}"
python3 /opt/gamepanel/app.py --create-user "${PANEL_USER:-admin}" \
  --password "${PANEL_PASSWORD:-admin12345}"

if [ "${PANEL_SEED_DEMO:-0}" = "1" ]; then
  echo "==> cadastrando os servidores de teste (PANEL_SEED_DEMO=1)"
  python3 - <<'PY'
import sys

sys.path.insert(0, "/opt/gamepanel")
import app as panel  # noqa: E402  (o import ja cria/migra o banco)

SEEDS = [
    # Sem player_source: o painel deduz a2s pela porta de consulta. A API REST falsa
    # (127.0.0.1:8212, admin/troque-me) fica esperando em Configurar contagem > API HTTP.
    dict(name="Palworld (teste)", host="game-palworld", service="palworld.service",
         game_port="8211/udp", query_port=27015,
         config_path="/opt/game/Pal/Saved/Config/LinuxServer",
         config_files="/opt/game/Pal/Saved/Config/LinuxServer/PalWorldSettings.ini",
         notes="Container de teste do docker compose."),
    # Sem porta de consulta: este imita o jogo que so da para contar pelo log.
    dict(name="Dragonwilds (teste)", host="game-dragonwilds", service="dragonwilds.service",
         game_port="7777/udp", query_port=0,
         config_path="/opt/game/RSDragonwilds/Saved/Config/LinuxServer",
         config_files="/opt/game/RSDragonwilds/Saved/Config/LinuxServer/DedicatedServer.ini",
         notes="Container de teste do docker compose."),
]

for seed in SEEDS:
    criado = panel.ensure_server(panel.ServidorDoDeploy(**seed))
    print(f"servidor de teste {'cadastrado' if criado else 'ja existia'}: {seed['name']}")
PY
fi

echo "==> painel em http://localhost:${GAMEPANEL_PORT} (usuario ${PANEL_USER:-admin})"
if [ "${GAMEPANEL_DEV:-0}" = "1" ]; then
  exec gunicorn --workers 1 --threads 16 --timeout 120 --reload \
    --bind "0.0.0.0:${GAMEPANEL_PORT}" --access-logfile - app:app
fi
exec gunicorn --workers 1 --threads 16 --timeout 120 \
  --bind "0.0.0.0:${GAMEPANEL_PORT}" --access-logfile - app:app
