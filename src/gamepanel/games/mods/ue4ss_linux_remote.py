"""UE4SS nativo de Linux (port XarminaEu/ue4ss-linux) - roda DENTRO do CT do jogo.

Mesmo desenho dos outros instaladores remotos: o painel le este texto e o executa no
container com `python3 -c`, por SSH, como root. So stdlib e sem import do `gamepanel`.

Para servidor Unreal que e LINUX NATIVO (Palworld daqui): o UE4SS oficial so injeta em .exe
de Windows; este port entra por LD_PRELOAD (`libUE4SS.so`), num drop-in do systemd, sem
trocar o script de partida do jogo. O port foi feito e verificado pelos autores no Palworld
(UE 5.1); aqui ainda nao rodou num servidor de verdade.

O que foi MEDIDO no Dragonwilds (UE 5.6.1, binario sem simbolos), e por isso ele NAO tem
este instalador: a v3.0.2 acha o motor (GUObjectArray, FName) e roda Lua puro, mas QUALQUER
acesso ao jogo - `FindFirstOf`/`GetFullName` ou um `RegisterHook` - derruba o servidor (os
deslocamentos sao os do Palworld 5.1). A v3.0.26 (dev) acha o motor e nao roda mod nenhum.

Decisoes, cada uma com o motivo:
- **A release estavel (`releases/latest`, v3.0.2), e nao os `*-linux-dev`.** Medido acima.
- **O .so e trocado ao lado e movido por cima** (`rename`): copiar sobre o arquivo com o
  servidor rodando corrompe o mapeamento na memoria (aviso do proprio port).
- **Bibliotecas que faltam vem do apt** (o .so liga em X11/OpenGL por causa da GUI, mesmo sem
  usa-la): no Dragonwilds faltava a `libX11.so.6`, e sem ela o LD_PRELOAD nem carrega.
- **Sem console, sem janela e sem recarregar sozinho**; config e mods.txt do dono preservados.
- **Desligar e apagar o drop-in**: nenhum codigo do UE4SS roda, sem apagar mod nenhum.
- **O proprio jogo pode acusar o .so** (o Dragonwilds marca a sessao com ModDetection=1): e so
  um aviso no log do jogo, nao bloqueia.

Acoes (argv): [--scan SCRIPT] --unit SERVICO status|loader-install [VERSAO]|loader-enable|
loader-disable, seguidas da pasta do executavel (Binaries/Linux). Termina com UMA linha JSON.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

RELEASES = "https://api.github.com/repos/XarminaEu/ue4ss-linux/releases/latest"
RELEASE_TAG = "https://api.github.com/repos/XarminaEu/ue4ss-linux/releases/tags/{tag}"
VERSION = re.compile(r"\d{1,9}\.\d{1,9}\.\d{1,9}")
ASSET = re.compile(r"^ue4ss-linux-v[0-9][0-9A-Za-z.\-]*\.tar\.gz$")
LIB = "libUE4SS.so"
SETTINGS = "UE4SS-settings.ini"
LOG = "UE4SS.log"
MODS = "Mods"
MODS_TXT = "mods.txt"
MARK = ".gamepanel-ue4ss-linux.json"
SYSTEMD_DIR = "/etc/systemd/system"
DROPIN = "gamepanel-ue4ss.conf"
UNIT = re.compile(r"[A-Za-z0-9_.@-]{1,120}\.service")
OWNER = "steam"
TIMEOUT = 120
LOG_TAIL = 15
# O que o .so pede por causa da GUI embutida (lido com ldd no CT do Dragonwilds).
APT_LIBS = ("libx11-6", "libxrandr2", "libxinerama1", "libxcursor1", "libxi6", "libgl1", "libegl1")
SETTINGS_TEXT = """[General]
EnableHotReloadSystem = false
EnableAutoReloadingLuaMods = false
EnableDebugKeyBindings = false

[Debug]
ConsoleEnabled = 0
GuiConsoleEnabled = 0
GuiConsoleVisible = 0
"""


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


def _read_text(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _read_json(path: str) -> dict:
    with contextlib.suppress(ValueError):
        data = json.loads(_read_text(path) or "{}")
        return data if isinstance(data, dict) else {}
    return {}


# ------------------------------------------------------------------ systemd

def dropin_path(unit: str) -> str:
    if not UNIT.fullmatch(unit or ""):
        raise ValueError(f"servico invalido: {unit!r}")
    return posixpath.join(SYSTEMD_DIR, f"{unit}.d", DROPIN)


def _daemon_reload() -> None:
    subprocess.run(["systemctl", "daemon-reload"], check=False)  # noqa: S607


def set_enabled(exe_dir: str, unit: str, enabled: bool) -> None:
    path = dropin_path(unit)
    if enabled:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"[Service]\nEnvironment=LD_PRELOAD={posixpath.join(exe_dir, LIB)}\n")
    else:
        with contextlib.suppress(FileNotFoundError):
            os.remove(path)
    # Sem o daemon-reload o systemd segue com o ambiente antigo ate o proximo boot.
    _daemon_reload()


# ------------------------------------------------------------------ o carregador

def release_for(version: str = "", fetcher=fetch) -> dict:
    if not version:
        return json.loads(fetcher(RELEASES))
    if not VERSION.fullmatch(version):
        raise ValueError(f"versao invalida: {version!r}")
    return json.loads(fetcher(RELEASE_TAG.format(tag=f"v{version}")))


def _asset_url(release: dict) -> tuple[str, str]:
    for asset in release.get("assets", []):
        url = asset.get("browser_download_url", "")
        if ASSET.match(asset.get("name", "")) and url.startswith("https://github.com/"):
            return asset["name"], url
    raise ValueError("esta versao do port nao traz o ue4ss-linux-*.tar.gz")


def _lib_from_tar(data: bytes) -> bytes:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        member = next((m for m in tar.getmembers() if m.isfile() and posixpath.basename(m.name) == LIB), None)
        if member is None:
            raise ValueError(f"o pacote nao tem {LIB}: nao e o UE4SS Linux")
        handle = tar.extractfile(member)
        if handle is None:
            raise ValueError(f"nao consegui ler o {LIB} do pacote")
        return handle.read()


def _ensure_libs(lib_path: str) -> None:
    """Instala as bibliotecas de sistema que o .so pede e o CT nao tem."""
    # O caminho e o que o proprio instalador acabou de gravar, nunca algo vindo de fora.
    proc = subprocess.run(["ldd", lib_path], capture_output=True, text=True, check=False)  # noqa: S603, S607
    if "not found" not in (proc.stdout or ""):
        return
    print("instalando as bibliotecas de sistema que o UE4SS pede (apt)...")
    env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
    subprocess.run(["apt-get", "install", "-y", "-qq", "--no-install-recommends", *APT_LIBS],  # noqa: S603, S607
                   capture_output=True, check=False, env=env)
    again = subprocess.run(["ldd", lib_path], capture_output=True, text=True, check=False)  # noqa: S603, S607
    if "not found" in (again.stdout or ""):
        missing = [ln.split()[0] for ln in again.stdout.splitlines() if "not found" in ln]
        raise ValueError(f"faltam bibliotecas de sistema: {', '.join(missing)}")


def install_loader(exe_dir: str, unit: str, version: str = "", fetcher=fetch, scan=_no_scan) -> dict:
    if not os.path.isdir(exe_dir):
        raise ValueError(f"a pasta do executavel nao existe: {exe_dir}")
    dropin_path(unit)  # confere o servico antes de baixar qualquer coisa
    release = release_for(version, fetcher)
    name, url = _asset_url(release)
    print(f"baixando {name}")
    data = fetcher(url)
    scan([(name, data)])
    lib = _lib_from_tar(data)
    target = os.path.join(exe_dir, LIB)
    staged = target + ".new"
    with open(staged, "wb") as f:
        f.write(lib)
    os.chmod(staged, 0o755)  # noqa: S103
    # Por cima com rename: o servidor pode estar com o .so velho mapeado na memoria.
    os.replace(staged, target)
    _ensure_libs(target)
    settings = os.path.join(exe_dir, SETTINGS)
    if not os.path.exists(settings):
        with open(settings, "w", encoding="utf-8") as f:
            f.write(SETTINGS_TEXT)
    os.makedirs(os.path.join(exe_dir, MODS), exist_ok=True)
    mods_txt = os.path.join(exe_dir, MODS, MODS_TXT)
    if not os.path.exists(mods_txt):
        with open(mods_txt, "w", encoding="utf-8") as f:
            f.write("")
    set_enabled(exe_dir, unit, True)
    tag = release.get("tag_name", "")
    with open(os.path.join(exe_dir, MARK), "w", encoding="utf-8") as f:
        json.dump({"version": tag, "pinned": bool(version)}, f)
    print(f"UE4SS Linux {tag} em {exe_dir} (LD_PRELOAD no {unit})")
    return {"loader": "UE4SS Linux", "version": tag}


def enabled_mods(text: str) -> dict[str, bool]:
    result = {}
    for line in text.lstrip("﻿").splitlines():
        name, sep, flag = line.partition(":")
        if sep and not line.lstrip().startswith(";"):
            result[name.strip()] = flag.strip() == "1"
    return result


def status(exe_dir: str, unit: str) -> dict:
    mods_dir = os.path.join(exe_dir, MODS)
    flags = enabled_mods(_read_text(os.path.join(mods_dir, MODS_TXT)))
    mods = []
    for entry in sorted(os.listdir(mods_dir)) if os.path.isdir(mods_dir) else []:
        if os.path.isdir(os.path.join(mods_dir, entry)):
            mods.append({"name": entry, "enabled": flags.get(
                entry, os.path.exists(os.path.join(mods_dir, entry, "enabled.txt")))})
    mark = _read_json(os.path.join(exe_dir, MARK))
    return {
        "loader_installed": os.path.exists(os.path.join(exe_dir, LIB)),
        "loader": "UE4SS Linux", "loader_version": mark.get("version", ""),
        "loader_pinned": bool(mark.get("pinned")),
        "enabled": os.path.exists(dropin_path(unit)),
        "mods": mods,
        "log": _read_text(os.path.join(exe_dir, LOG)).splitlines()[-LOG_TAIL:],
    }


def _chown(exe_dir: str) -> None:
    try:
        import pwd
        pw = pwd.getpwnam(OWNER)
    except (ImportError, KeyError):
        return
    for name in (LIB, SETTINGS, MARK):
        with contextlib.suppress(OSError):
            os.chown(os.path.join(exe_dir, name), pw.pw_uid, pw.pw_gid)
    for root, dirs, files in os.walk(os.path.join(exe_dir, MODS)):
        for n in (root, *[os.path.join(root, d) for d in dirs], *[os.path.join(root, f) for f in files]):
            with contextlib.suppress(OSError):
                os.chown(n, pw.pw_uid, pw.pw_gid)


def main(argv: list[str]) -> int:
    script = unit = ""
    if argv[:1] == ["--scan"]:
        script, argv = argv[1], argv[2:]
    if argv[:1] == ["--unit"]:
        unit, argv = argv[1], argv[2:]
    action, exe_dir, *rest = argv
    try:
        if action == "loader-install" and not script:
            raise ValueError("instalar sem a verificacao do antivirus nao e caminho do painel")
        if action == "status":
            result = status(exe_dir, unit)
        elif action == "loader-install":
            result = install_loader(exe_dir, unit, rest[0] if rest else "", scan=scanner(script))
        elif action in ("loader-enable", "loader-disable"):
            set_enabled(exe_dir, unit, action == "loader-enable")
            result = {"enabled": action == "loader-enable"}
        else:
            raise ValueError(f"acao desconhecida: {action}")
        if action != "status":
            _chown(exe_dir)
    except (ValueError, KeyError, OSError, tarfile.TarError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
