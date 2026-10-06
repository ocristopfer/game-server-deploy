#!/usr/bin/env bash
# Installs a release INSIDE the container, from a tar.gz and its sha256.
#
#   bash install-release.sh <package> <tarball> <sha256> <app_dir> <service> [health_command]
#
# The same file serves both publishing paths: direct upload over SSH (deploy-*.ps1) and
# provisioning from the Proxmox host (provision-*-lxc.sh, via pct).
# Having ONE implementation is the point: when there were two, each had its own hand-written
# list of which folders to delete before copying, and both fell behind with every new
# folder in the package - leaving a renamed module alive in the container, importable,
# without anyone noticing.
#
# The design is one FOLDER per release, with a symlink pointing at the current one:
#
#   /opt/gamepanel/releases/0.1.0+abc1234/gamepanel/...
#   /opt/gamepanel/current -> releases/0.1.0+abc1234
#
# Nothing is copied over anything. A file that disappeared from the package cannot survive,
# and going back to the previous version means moving the symlink back - not repeating a deploy.
set -euo pipefail

KEEP_RELEASES=5
HEALTH_TRIES=10
HEALTH_SLEEP=2

# A failure inside $(...) ends the script before the `die` that would explain it: without this
# trap the deploy stops without saying a word, and that is how the first real deploy ended.
trap 'echo "ERROR at line ${LINENO}: ${BASH_COMMAND}" >&2' ERR

die() { echo "ERROR: $*" >&2; exit 1; }
msg() { echo "==> $*"; }

[[ $# -ge 5 ]] || die "usage: install-release.sh <package> <tarball> <sha256> <app_dir> <service> [health_command]"

PACKAGE="$1"
TARBALL="$2"
EXPECTED_SHA="$3"
APP_DIR="$4"
SERVICE="$5"
HEALTH_CMD="${6:-}"

RELEASES_DIR="${APP_DIR}/releases"
CURRENT_LINK="${APP_DIR}/current"

[[ -f "$TARBALL" ]] || die "tarball not found: $TARBALL"

# --- 1. is the file what the deploy sent? -------------------------------------
# The hash is deterministic (see tools/build-release.py), so it answers "does the CT have
# THIS code?", and not just "did the file arrive intact?".
actual_sha="$(sha256sum "$TARBALL" | cut -d' ' -f1 || true)"
[[ -n "$actual_sha" ]] || die "could not compute the sha256 of $TARBALL"
[[ "$actual_sha" == "$EXPECTED_SHA" ]] \
  || die "sha256 nao confere: esperado $EXPECTED_SHA, recebido $actual_sha"

# --- 2. extract to a temporary place and find out the version -----------------
# The version comes from the STAMP inside the package, not from the file name: a name can be
# renamed, the stamp is what the process will present itself as in /health.
staging="$(mktemp -d "${APP_DIR}/.staging.XXXXXX" || true)"
[[ -n "$staging" ]] || die "could not create a temporary folder in $APP_DIR"
cleanup() { rm -rf "$staging"; }
trap 'cleanup' EXIT

tar -xzf "$TARBALL" -C "$staging" || die "tar failed to extract $TARBALL"
stamp="${staging}/${PACKAGE}/_build.py"
[[ -f "$stamp" ]] || die "the package has no ${PACKAGE}/_build.py (was it built by tools/build-release.py?)"
version="$(sed -n "s/^VERSION = '\\(.*\\)'$/\\1/p" "$stamp" || true)"
[[ -n "$version" ]] || die "could not read VERSION from ${PACKAGE}/_build.py"

target="${RELEASES_DIR}/${version}"
msg "release ${version}"

# --- 3. install the version folder --------------------------------------------
install -d -m 0755 "$RELEASES_DIR"
# Reinstalling the SAME version is a normal case (redeploy after a configuration tweak): the
# old folder goes away entirely so it does not become a mix of the two extractions.
rm -rf "$target"
install -d -m 0755 "$target"
mv "${staging}/${PACKAGE}" "${target}/${PACKAGE}"
chown -R root:root "$target"
chmod -R a+rX "$target"

# Failing here is better than the service crashing at start with ModuleNotFoundError, or the
# browser getting a TemplateNotFound.
( cd "$target" && python3 -c "import ${PACKAGE}, ${PACKAGE}.version" ) \
  || die "the package does not import from ${target}"

# --- 4. flip the symlink (and remember where it pointed) ----------------------
previous=""
if [[ -L "$CURRENT_LINK" ]]; then
  previous="$(readlink -f "$CURRENT_LINK" || true)"
fi

# ln -sfn on a symlink that already exists creates the link INSIDE the folder it points to.
# The safe way is to create it alongside and rename: `mv -T` is atomic, so there is never
# an instant in which `current` points nowhere.
ln -sfn "$target" "${CURRENT_LINK}.new"
mv -T "${CURRENT_LINK}.new" "$CURRENT_LINK"

# --- 5. restart and check; if it does not come up, go back to the previous ----
restart_and_check() {
  # On the first provisioning the unit does not exist yet: it is written after the code is
  # in place. There is nothing to restart or probe, and insisting here would make the whole
  # provisioning fail before reaching the part that creates the service.
  if ! systemctl cat "$SERVICE" >/dev/null 2>&1; then
    msg "service ${SERVICE} does not exist yet - provisioning is what starts it"
    return 0
  fi
  systemctl restart "$SERVICE" || return 1
  local try
  for try in $(seq 1 "$HEALTH_TRIES"); do
    sleep "$HEALTH_SLEEP"
    systemctl is-active --quiet "$SERVICE" || return 1
    # A bare `[[ ... ]] && return 0` would kill the script through `set -e` when the condition
    # is false: a failing `&&` is a failure of the whole command.
    if [[ -z "$HEALTH_CMD" ]] || eval "$HEALTH_CMD" >/dev/null 2>&1; then
      return 0
    fi
    echo "   health check has not answered yet (${try}/${HEALTH_TRIES})"
  done
  return 1
}

if restart_and_check; then
  msg "live: ${version}"
  # Keep a copy of THIS installer where the automatic updater looks for it
  # (gamepanel/updater.py): the deploys only bring it to a temporary folder they delete, and
  # without a copy that every deploy refreshes, the updater would run whatever version of the
  # installer was left behind - or none at all.
  persisted="/usr/local/lib/${PACKAGE}/install-release.sh"
  self_path="$(readlink -f "${BASH_SOURCE[0]}" || true)"
  if [[ -n "$self_path" && "$self_path" != "$(readlink -f "$persisted" 2>/dev/null || true)" ]]; then
    install -D -m 0755 "$self_path" "$persisted" || echo "   could not keep a copy of the installer in ${persisted}"
  fi
else
  if [[ -n "$previous" && -d "$previous" && "$previous" != "$target" ]]; then
    msg "did NOT come up - rolling back to $(basename "$previous")"
    ln -sfn "$previous" "${CURRENT_LINK}.new"
    mv -T "${CURRENT_LINK}.new" "$CURRENT_LINK"
    systemctl restart "$SERVICE" || true
  fi
  die "service ${SERVICE} did not stay up with release ${version}"
fi

# --- 6. prune -----------------------------------------------------------------
# Keeping the latest ones is what makes "go back one version" possible without repackaging.
# The current and the previous are never pruned, even if their date puts them at the end of the queue.
keep_current="$(readlink -f "$CURRENT_LINK" || true)"
while IFS= read -r old; do
  [[ "$old" == "$keep_current" || "$old" == "$previous" ]] && continue
  rm -rf "$old"
done < <(find "$RELEASES_DIR" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' \
         | sort -rn | tail -n "+$((KEEP_RELEASES + 1))" | cut -d' ' -f2-)

# Old layout: what existed in ${APP_DIR} before this mechanism. Once the symlink took over,
# it only confuses -- and the risk is not cosmetic: it is code with the OLD NAMES still
# alive and importable in the container, with nothing updating it. A list of what to remove
# does not work, because each earlier version left a different layout (the panel left 27 loose
# .py files plus templates/ and static/; the broker left the broker/ folder, the package name
# before the rename), and a hand-written list would be born incomplete -- that is how the list
# of subfolders to delete fell behind with every new folder, which is the reason the
# per-version layout exists. So the rule is inverted: we say what STAYS.
#
# ${APP_DIR} only holds the release mechanism and the directories provisioning pushes
# separately (the broker's lib/ and games/, which are not the Python package). Data and config
# were never here: they live in /var/lib and /etc. That is why removing the rest is safe.
KEPT_IN_APP_DIR=(releases current lib games)

prune_old_layout() {
  local entry base keep
  for entry in "${APP_DIR}"/* "${APP_DIR}"/.[!.]*; do
    [[ -e "$entry" || -L "$entry" ]] || continue
    base="$(basename "$entry")"
    # This script's temporary folder is not old layout: the exit trap removes it. Without
    # this line the deploy log announced "removing the old layout: .staging.XXXXXX",
    # which sends the reader looking for a problem that does not exist.
    case "$base" in .staging.*) continue;; esac
    keep=0
    for name in "${KEPT_IN_APP_DIR[@]}"; do
      [[ "$base" == "$name" ]] && keep=1 && break
    done
    [[ "$keep" -eq 1 ]] && continue
    msg "removing the old layout: ${base}"
    # ${APP_DIR:?} so an empty APP_DIR becomes an error instead of "rm -rf /name".
    rm -rf "${APP_DIR:?}/${base}"
  done
}

prune_old_layout
