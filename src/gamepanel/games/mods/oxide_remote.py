"""Oxide (uMod), o carregador de plugins do Rust - roda DENTRO do CT do jogo, nao no painel.

Mesmo desenho dos outros instaladores remotos: o painel le este texto e o executa no
container com `python3 -c`, por SSH, como root. So stdlib e sem import do `gamepanel`.

O pacote (`Oxide.Rust-linux.zip`, release do GitHub OxideMod/Oxide.Rust) e so a pasta
`RustDedicated_Data/Managed/` - conferido baixando a 2.0.7801 -, e ele SOBRESCREVE DLLs do
proprio jogo. Daqui saem as decisoes:
- **O que vai ser sobrescrito e guardado antes** (`.gamepanel-oxide/original/`). Desligar
  devolve o original; religar poe o Oxide de novo, sem baixar nada. Sem a copia, "desligar"
  so seria possivel validando o jogo inteiro pela Steam.
- **Atualizacao do Rust pela Steam APAGA o Oxide** (o SteamCMD devolve as DLLs do jogo), e
  o Rust atualiza toda primeira quinta do mes, alem dos hotfixes. O status compara o que esta
  na pasta com o que o instalador pos, e a tela pede para reinstalar quando nao bate. A copia
  do original tambem fica velha nessa hora: reinstalar a refaz.
- **Plugins sao `.cs` em `oxide/plugins`**, enviados pela tela (o envio passa pelo antivirus).
  O Oxide compila e carrega plugin novo sem reiniciar o servidor.

NAO TESTADO num servidor de verdade ainda.

Acoes (argv): [--scan SCRIPT] status | loader-install [VERSAO] | loader-enable | loader-disable,
seguidas da pasta do jogo (onde mora o RustDedicated). Toda acao termina com UMA linha JSON.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

RELEASES = "https://api.github.com/repos/OxideMod/Oxide.Rust/releases/latest"
RELEASE_TAG = "https://api.github.com/repos/OxideMod/Oxide.Rust/releases/tags/{tag}"
# As versoes do Oxide sao x.y.zzzz (2.0.7801).
VERSION = re.compile(r"\d{1,9}\.\d{1,9}\.\d{1,9}")
ASSET = "Oxide.Rust-linux.zip"
PREFIX = "RustDedicated_Data/Managed/"
STATE_DIR = ".gamepanel-oxide"
ORIGINAL = "original"
PACKAGE = "package"
MARK = "install.json"
PLUGINS = posixpath.join("oxide", "plugins")
OWNER = "steam"
TIMEOUT = 120
LOG_TAIL = 15


def fetch(url: str) -> bytes:
    # So https do github.com chega aqui: a API e fixa (RELEASES) e o download vem da resposta
    # dela, conferida contra github.com antes de baixar.
    req = urllib.request.Request(url, headers={"User-Agent": "gamepanel"})  # noqa: S310
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310
        return r.read()


# ------------------------------------------------------------------ antivirus
# IGUAL nos outros instaladores remotos (ha teste comparando): rodam soltos no CT e nao importam
# um ao outro. A regra (o que conta como achado) nao mora aqui, e sim no script que o painel
# manda; aqui so se escreve o que baixou numa pasta e se chama o script.

def scanner(script: str):
    """Funcao que verifica [(nome, bytes)] com o script do painel; ValueError = recusado."""
    def scan(blobs: list[tuple[str, bytes]]) -> None:
        # /var/tmp e nao /tmp: no Debian 13 o /tmp e tmpfs (memoria), e o pacote pode ter
        # dezenas de MB. O prefixo e o que o script do antivirus aceita apagar. mkdtemp:
        # nome imprevisivel e 0700.
        os.makedirs("/var/tmp", exist_ok=True)  # noqa: S108
        work = tempfile.mkdtemp(prefix="gamepanel-scan-", dir="/var/tmp")
        try:
            for i, (name, data) in enumerate(blobs):
                safe = re.sub(r"[^A-Za-z0-9._-]", "_", name)[:120]
                with open(os.path.join(work, f"{i:02d}-{safe}.zip"), "wb") as f:
                    f.write(data)
            sys.stdout.flush()
            proc = subprocess.run(["bash", "-c", script, "gp", work],  # noqa: S603, S607
                                  capture_output=True, text=True, check=False)
            sys.stdout.write((proc.stdout or "") + (proc.stderr or ""))
            if proc.returncode != 0:
                raise ValueError("o antivirus recusou o pacote: nada foi instalado")
        finally:
            shutil.rmtree(work, ignore_errors=True)
    return scan


def _no_scan(blobs: list[tuple[str, bytes]]) -> None:
    """So para teste e status: `main` recusa instalar sem `--scan`."""


def _read_json(path: str) -> dict:
    with contextlib.suppress(OSError, ValueError):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    return {}


def _sha(path: str) -> str:
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return ""


def _safe_rel(path: str) -> str:
    rel = posixpath.normpath(path.replace("\\", "/")).lstrip("/")
    if rel in (".", "") or rel.startswith("..") or "/../" in f"/{rel}/":
        return ""
    return rel


def release_for(version: str = "", fetcher=fetch) -> dict:
    if not version:
        return json.loads(fetcher(RELEASES))
    if not VERSION.fullmatch(version):
        raise ValueError(f"versao invalida: {version!r}")
    return json.loads(fetcher(RELEASE_TAG.format(tag=version)))


def _asset_url(release: dict) -> str:
    for asset in release.get("assets", []):
        url = asset.get("browser_download_url", "")
        if asset.get("name") == ASSET and url.startswith("https://github.com/"):
            return url
    raise ValueError(f"esta versao do Oxide nao traz o {ASSET}")


def install_loader(game_dir: str, version: str = "", fetcher=fetch, scan=_no_scan) -> dict:
    if not os.path.isdir(os.path.join(game_dir, "RustDedicated_Data")):
        raise ValueError(f"nao parece um servidor de Rust: falta RustDedicated_Data em {game_dir}")
    release = release_for(version, fetcher)
    data = fetcher(_asset_url(release))
    scan([(f"Oxide.Rust-{release.get('tag_name', '')}", data)])
    z = zipfile.ZipFile(io.BytesIO(data))
    files = [n for n in z.namelist() if n.startswith(PREFIX) and not n.endswith("/") and _safe_rel(n)]
    if not files:
        raise ValueError(f"o zip nao tem {PREFIX}: nao e o Oxide do Rust")
    state = os.path.join(game_dir, STATE_DIR)
    original = os.path.join(state, ORIGINAL)
    package = os.path.join(state, PACKAGE)
    ours = _read_json(os.path.join(state, MARK)).get("files", {})
    shutil.rmtree(package, ignore_errors=True)
    hashes = {}
    for entry in files:
        rel = _safe_rel(entry)
        dest = os.path.join(game_dir, rel)
        # Entra no backup o arquivo que NAO e o que o instalador pos: o do jogo. Com o Oxide
        # ligado, o que esta na pasta e o Oxide, e o backup de antes continua valendo; depois
        # de uma atualizacao do Rust, o que esta na pasta e o jogo NOVO, e substitui o velho.
        if os.path.exists(dest) and _sha(dest) != ours.get(rel):
            os.makedirs(os.path.dirname(os.path.join(original, rel)), exist_ok=True)
            shutil.copy2(dest, os.path.join(original, rel))
        body = z.read(entry)
        for base in (game_dir, package):
            out = os.path.join(base, rel)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "wb") as f:
                f.write(body)
        hashes[rel] = hashlib.sha256(body).hexdigest()
    os.makedirs(os.path.join(game_dir, PLUGINS), exist_ok=True)
    tag = release.get("tag_name", "")
    with open(os.path.join(state, MARK), "w", encoding="utf-8") as f:
        json.dump({"version": tag, "pinned": bool(version), "files": hashes}, f)
    print(f"Oxide {tag}: {len(files)} arquivos em {game_dir}/{PREFIX}")
    return {"loader": "Oxide", "version": tag, "files": len(files)}


def _copy_tree(src: str, dest: str) -> int:
    count = 0
    for root, _, names in os.walk(src):
        for name in names:
            rel = os.path.relpath(os.path.join(root, name), src)
            out = os.path.join(dest, rel)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            shutil.copy2(os.path.join(root, name), out)
            count += 1
    return count


def set_enabled(game_dir: str, enabled: bool) -> dict:
    state = os.path.join(game_dir, STATE_DIR)
    mark = _read_json(os.path.join(state, MARK))
    if not mark:
        raise ValueError("o Oxide nao foi instalado pelo painel neste servidor")
    if enabled:
        count = _copy_tree(os.path.join(state, PACKAGE), game_dir)
    else:
        # Arquivo que o Oxide trouxe e o jogo nao tinha sai; o que o jogo tinha volta.
        for rel in mark.get("files", {}):
            if not os.path.exists(os.path.join(state, ORIGINAL, rel)):
                with contextlib.suppress(FileNotFoundError):
                    os.remove(os.path.join(game_dir, rel))
        count = _copy_tree(os.path.join(state, ORIGINAL), game_dir)
    return {"enabled": enabled, "files": count}


def status(game_dir: str) -> dict:
    mark = _read_json(os.path.join(game_dir, STATE_DIR, MARK))
    files = mark.get("files", {})
    matching = sum(1 for rel, sha in files.items() if _sha(os.path.join(game_dir, rel)) == sha)
    plugins_dir = os.path.join(game_dir, PLUGINS)
    plugins = [{"name": n, "size": os.path.getsize(os.path.join(plugins_dir, n))}
               for n in sorted(os.listdir(plugins_dir)) if n.endswith(".cs")] if os.path.isdir(plugins_dir) else []
    log_dir = os.path.join(game_dir, "oxide", "logs")
    logs = sorted(n for n in os.listdir(log_dir) if n.endswith(".txt")) if os.path.isdir(log_dir) else []
    log: list[str] = []
    if logs:
        newest = os.path.join(log_dir, logs[-1])
        with contextlib.suppress(OSError), open(newest, encoding="utf-8", errors="replace") as f:
            log = f.read().splitlines()[-LOG_TAIL:]
    return {
        "loader_installed": bool(files),
        "loader": "Oxide", "loader_version": mark.get("version", ""),
        "loader_pinned": bool(mark.get("pinned")),
        # Tudo no lugar = ligado; nada = desligado (ou o jogo foi atualizado); parte = quebrado.
        "enabled": bool(files) and matching == len(files),
        "wiped": bool(files) and 0 < matching < len(files),
        "mods": plugins, "log": log,
    }


def _chown(game_dir: str) -> None:
    try:
        import pwd
        pw = pwd.getpwnam(OWNER)
    except (ImportError, KeyError):
        return
    for root, dirs, names in os.walk(os.path.join(game_dir, "oxide")):
        for n in (root, *[os.path.join(root, d) for d in dirs], *[os.path.join(root, f) for f in names]):
            with contextlib.suppress(OSError):
                os.chown(n, pw.pw_uid, pw.pw_gid)
    for rel in _read_json(os.path.join(game_dir, STATE_DIR, MARK)).get("files", {}):
        with contextlib.suppress(OSError):
            os.chown(os.path.join(game_dir, rel), pw.pw_uid, pw.pw_gid)


def main(argv: list[str]) -> int:
    script = ""
    if argv[:1] == ["--scan"]:
        script, argv = argv[1], argv[2:]
    action, game_dir, *rest = argv
    try:
        if action == "loader-install" and not script:
            raise ValueError("instalar sem a verificacao do antivirus nao e caminho do painel")
        if action == "status":
            result = status(game_dir)
        elif action == "loader-install":
            result = install_loader(game_dir, rest[0] if rest else "", scan=scanner(script))
        elif action in ("loader-enable", "loader-disable"):
            result = set_enabled(game_dir, action == "loader-enable")
        else:
            raise ValueError(f"acao desconhecida: {action}")
        if action != "status":
            _chown(game_dir)
    except (ValueError, KeyError, OSError, zipfile.BadZipFile) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
