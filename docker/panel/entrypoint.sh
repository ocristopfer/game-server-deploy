#!/bin/sh
# Prepara o painel para o ambiente local: chave SSH, usuario admin e dois servidores
# ja cadastrados apontando para os containers de jogo falsos.
set -e

install -d -m 0755 /var/lib/gamepanel /etc/gamepanel /keys

if [ ! -f "$GAMEPANEL_SSH_KEY" ]; then
  echo "==> gerando a chave SSH do painel"
  ssh-keygen -t ed25519 -N '' -C 'gamepanel@dev' -f "$GAMEPANEL_SSH_KEY" >/dev/null
fi
# Os containers de jogo leem daqui na hora de montar o authorized_keys.
cp -f "${GAMEPANEL_SSH_KEY}.pub" /keys/panel.pub
touch "$GAMEPANEL_KNOWN_HOSTS"

echo "==> criando usuario ${PANEL_USER:-admin} e semeando os servidores de teste"
python3 - <<'PY'
import os
import sys

sys.path.insert(0, "/opt/gamepanel")
import app as panel  # noqa: E402  (o import ja cria/migra o banco)

panel.ensure_admin_user(os.environ.get("PANEL_USER", "admin"),
                        os.environ.get("PANEL_PASSWORD", "admin12345"))

SEEDS = [
    ("Palworld (teste)", "game-palworld", "palworld.service", "8211/udp",
     "/opt/game/Pal/Saved/Config/LinuxServer"),
    ("Dragonwilds (teste)", "game-dragonwilds", "dragonwilds.service", "7777/udp",
     "/opt/game/RSDragonwilds/Saved/Config/LinuxServer"),
]

conn = panel._connect()
with conn:
    for name, host, service, ports, config_path in SEEDS:
        exists = conn.execute("SELECT 1 FROM servers WHERE host = ?", (host,)).fetchone()
        if exists:
            continue
        conn.execute(
            "INSERT INTO servers (name, host, ssh_port, ssh_user, service, game_port,"
            " notes, config_path, created_at) VALUES (?,?,22,'root',?,?,?,?,?)",
            (name, host, service, ports, "Container de teste do docker compose.",
             config_path, panel.now_iso()),
        )
        print(f"servidor de teste cadastrado: {name} ({host})")
conn.close()
PY

echo "==> painel em http://localhost:${GAMEPANEL_PORT} (usuario ${PANEL_USER:-admin})"
exec gunicorn \
  --workers 1 --threads 16 --timeout 120 --reload \
  --bind "0.0.0.0:${GAMEPANEL_PORT}" --access-logfile - app:app
