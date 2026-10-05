#!/bin/bash
# Fake SteamCMD: records the arguments and creates what an app_update would create.
echo "steamcmd $*" >> /var/log/fake-steamcmd.log
dir=""; app=""
while [ $# -gt 0 ]; do
  case "$1" in +force_install_dir) dir="$2"; shift ;; +app_update) app="$2"; shift ;; esac
  shift
done
[ -n "$dir" ] && [ -n "$app" ] || exit 0
mkdir -p "$dir/steamapps"
printf '"AppState"\n{\n\t"buildid"\t\t"4242"\n}\n' > "$dir/steamapps/appmanifest_${app}.acf"
# Files the "downloaded game" must have (list written by the driver, one per line).
if [ -r /etc/fake-game-files ]; then
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    mkdir -p "$dir/$(dirname "$f")"; printf '#!/bin/sh\nexit 0\n' > "$dir/$f"; chmod +x "$dir/$f"
  done < /etc/fake-game-files
fi
