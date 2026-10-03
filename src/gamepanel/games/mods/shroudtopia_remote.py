"""Shroudtopia (carregador de mods do Enshrouded) - roda DENTRO do CT do jogo, nao no painel.

Mesmo desenho do `thunderstore_remote.py`: o painel le este texto e o executa no container
com `python3 -c`, por SSH, como root. So stdlib e sem import do `gamepanel` - la dentro o
pacote nao existe -, e quem vai a internet e o CT, nunca o painel.

O que foi MEDIDO no Enshrouded de verdade (CT 303, Proton GE 11) e cada item aqui existe
por um desses:
- o carregador entra pelo `winmm.dll` ao lado do `enshrouded_server.exe`, e o Wine so o
  carrega com `winmm=n,b` no WINEDLLOVERRIDES (sem isso usa o winmm dele e nada acontece);
- com isso ele sobe (`Running on server: 1`), le o `shroudtopia.json` e carrega as DLLs de
  `mods/`; o servidor continua respondendo a A2S;
- o pacote oficial traz mods de EXEMPLO com trapaca ligada (sem dano de queda, sem custo de
  recurso). Eles NAO entram: instalar o carregador nao pode mudar o jogo de ninguem;
- mod feito para outra versao do jogo nao derruba o servidor, mas some funcao em silencio
  (`... not found` no log): por isso o status devolve o fim do `shroudtopia.log`.

Desligar e tirar o `winmm=n,b`: o Wine volta ao winmm dele e nenhum codigo do carregador
roda. Mais seguro que confiar no `"active": false` do json, que ainda carrega a DLL.

Acoes (argv): status | loader-install | loader-enable | loader-disable. Toda acao imprime o
progresso e termina com UMA linha JSON, que e o que o painel le.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import sys
import urllib.request
import zipfile

RELEASES = "https://api.github.com/repos/s0t7x/shroudtopia/releases/latest"
# O zip da versao: Shroudtopia-0.1.1.zip. Asset com outro nome nao e o carregador.
ASSET = re.compile(r"^Shroudtopia-[0-9][0-9A-Za-z.\-]*\.zip$")
# O que sai do zip. O resto (mods/ de exemplo) fica de fora de proposito.
LOADER_FILES = ("winmm.dll", "shroudtopia.dll")
CONFIG = "shroudtopia.json"
LOG = "shroudtopia.log"
MODS = "mods"
MARK = ".gamepanel-shroudtopia.json"
RUNTIME_ENV = "/etc/game-runtime.env"
OVERRIDE = "winmm=n,b"
OWNER = "steam"
TIMEOUT = 120
LOG_TAIL = 15
# A config so liga o log e o carregador: os mods ficam vazios, cada um entra pela tela.
DEFAULT_CONFIG = {"active": True, "bootDelay": 3000, "enableLogging": True,
                  "logLevel": "INFO", "mods": {}, "updateDelay": 500}


def fetch(url: str) -> bytes:
    # So https do github.com chega aqui: a API e fixa (RELEASES) e o download vem da resposta
    # dela, conferida contra github.com antes de baixar.
    req = urllib.request.Request(url, headers={"User-Agent": "gamepanel"})  # noqa: S310
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310
        return r.read()


def _read_text(path: str, default: str = "") -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return default


def _read_json(path: str) -> dict:
    with contextlib.suppress(ValueError):
        data = json.loads(_read_text(path) or "{}")
        return data if isinstance(data, dict) else {}
    return {}


# ------------------------------------------------------------------ o Wine

def _groups(value: str) -> list[str]:
    return [g.strip() for g in value.split(";") if g.strip()]


def with_winmm(value: str) -> str:
    """O WINEDLLOVERRIDES com o winmm nativo, sem mexer no resto do que o jogo decidiu."""
    return ";".join([g for g in _groups(value) if not g.startswith("winmm=")] + [OVERRIDE])


def without_winmm(value: str) -> str:
    return ";".join(g for g in _groups(value) if not g.startswith("winmm="))


def _read_overrides(env_path: str) -> str:
    for line in _read_text(env_path).splitlines():
        if line.startswith("WINE_DLL_OVERRIDES="):
            return line.split("=", 1)[1].strip().strip("'\"")
    return ""


def _write_overrides(env_path: str, value: str) -> None:
    lines = _read_text(env_path).splitlines()
    # O arquivo e lido com `source`: aspas simples, e o valor nunca tem aspa (so dll,=;).
    new = f"WINE_DLL_OVERRIDES='{value}'"
    lines = [new if ln.startswith("WINE_DLL_OVERRIDES=") else ln for ln in lines]
    if new not in lines:
        lines.append(new)
    with open(env_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def set_enabled(env_path: str, enabled: bool) -> None:
    old = _read_overrides(env_path)
    _write_overrides(env_path, with_winmm(old) if enabled else without_winmm(old))


def is_enabled(env_path: str) -> bool:
    return OVERRIDE in _groups(_read_overrides(env_path))


# ------------------------------------------------------------------ o carregador

def _asset_url(release: dict) -> tuple[str, str]:
    for asset in release.get("assets", []):
        url = asset.get("browser_download_url", "")
        if ASSET.match(asset.get("name", "")) and url.startswith("https://github.com/"):
            return asset["name"], url
    raise ValueError("a versao mais recente do Shroudtopia nao traz o zip do carregador")


def install_loader(game_dir: str, fetcher=fetch, env_path: str = RUNTIME_ENV) -> dict:
    release = json.loads(fetcher(RELEASES))
    name, url = _asset_url(release)
    print(f"baixando {name}")
    z = zipfile.ZipFile(io.BytesIO(fetcher(url)))
    by_base = {n.rsplit("/", 1)[-1].lower(): n for n in z.namelist() if not n.endswith("/")}
    missing = [f for f in LOADER_FILES if f not in by_base]
    if missing:
        raise ValueError(f"o zip nao tem {', '.join(missing)}: nao e o carregador")
    for wanted in LOADER_FILES:
        with z.open(by_base[wanted]) as src, open(os.path.join(game_dir, wanted), "wb") as out:
            out.write(src.read())
    config_path = os.path.join(game_dir, CONFIG)
    # Config que ja existe e do dono do servidor (os mods dele estao ali): so nasce se faltar.
    if not os.path.exists(config_path):
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=4)
    os.makedirs(os.path.join(game_dir, MODS), exist_ok=True)
    if os.path.exists(env_path):
        set_enabled(env_path, True)
    version = release.get("tag_name", "")
    with open(os.path.join(game_dir, MARK), "w", encoding="utf-8") as f:
        json.dump({"version": version, "asset": name}, f)
    print(f"Shroudtopia {version} em {game_dir} (sem os mods de exemplo)")
    return {"loader": "Shroudtopia", "version": version}


def status(game_dir: str, env_path: str = RUNTIME_ENV) -> dict:
    mods_dir = os.path.join(game_dir, MODS)
    mods = []
    for entry in sorted(os.listdir(mods_dir)) if os.path.isdir(mods_dir) else []:
        path = os.path.join(mods_dir, entry)
        if entry.lower().endswith(".dll") or os.path.isdir(path):
            mods.append({"name": entry, "dir": os.path.isdir(path),
                         "size": 0 if os.path.isdir(path) else os.path.getsize(path)})
    log = _read_text(os.path.join(game_dir, LOG)).splitlines()[-LOG_TAIL:]
    mark = _read_json(os.path.join(game_dir, MARK))
    return {
        "loader_installed": all(os.path.exists(os.path.join(game_dir, f)) for f in LOADER_FILES),
        "loader": "Shroudtopia", "loader_version": mark.get("version", ""),
        "enabled": is_enabled(env_path) if os.path.exists(env_path) else False,
        "mods": mods, "log": log,
    }


def _chown(game_dir: str) -> None:
    """O jogo roda como 'steam' e precisa ler o carregador e escrever o log e a config."""
    try:
        import pwd
        pw = pwd.getpwnam(OWNER)
    except (ImportError, KeyError):
        return
    paths = [os.path.join(game_dir, n) for n in (*LOADER_FILES, CONFIG, MARK, MODS)]
    for path in paths:
        with contextlib.suppress(OSError):
            os.chown(path, pw.pw_uid, pw.pw_gid)


def main(argv: list[str]) -> int:
    action, game_dir, *_ = argv
    try:
        if action == "status":
            result = status(game_dir)
        elif action == "loader-install":
            result = install_loader(game_dir)
        elif action in ("loader-enable", "loader-disable"):
            set_enabled(RUNTIME_ENV, action == "loader-enable")
            result = {"enabled": action == "loader-enable"}
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
