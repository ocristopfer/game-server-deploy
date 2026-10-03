"""UE4SS (carregador de mods de jogo Unreal) - roda DENTRO do CT do jogo, nao no painel.

Mesmo desenho do `shroudtopia_remote.py`: o painel le este texto e o executa no container
com `python3 -c`, por SSH, como root. So stdlib e sem import do `gamepanel` - la dentro o
pacote nao existe -, e quem vai a internet e o CT, nunca o painel.

Vale para jogo Unreal cujo servidor e o executavel WINDOWS rodando sob o Proton: o UE4SS
entra injetando uma DLL nesse executavel. Servidor Linux nativo (Dragonwilds, Palworld daqui)
nao carrega isto - os ports Linux sao outra coisa, e nenhum tem binario confiavel.

Decisoes, cada uma com o motivo:
- **A `experimental-latest`, e nao a v3.0.1 estavel.** MEDIDO no Icarus de verdade (CT de teste,
  Proton GE 11, 2026-10-03): com a v3.0.1 o UE4SS carrega e roda Lua, mas a Steam do servidor
  sobe com `AppId: 0` e "Steam API failed to initialize" - sem ela a consulta A2S nunca abre e
  o servidor some do navegador. Desligado, volta `AppId: 1149460`. Com a experimental (o
  `dwmapi.dll` solto e o resto em `ue4ss/`), a Steam sobe, a A2S responde e os mods rodam. A
  versao ainda pode ser fixada numa estavel pela tela, para quem souber o que esta fazendo.
- **O zip normal, nunca o zDEV.** O `zDEV-UE4SS_*.zip` abre console e janela de debug por
  padrao; num servidor sem tela isso no minimo gasta, e no V Rising um console aberto sob o X
  virtual TRAVOU o servidor.
- **Entra pelo `dwmapi.dll` ao lado do `*-Win64-Shipping.exe`**, e o Wine so o usa com
  `dwmapi=n,b` no WINEDLLOVERRIDES (o padrao dele e a dwmapi embutida, e o UE4SS nunca roda).
  Desligar e tirar o ajuste: nenhum codigo do UE4SS roda, sem apagar mod nenhum.
- **Console e janela desligados** (`ConsoleEnabled`, `GuiConsoleEnabled`, `GuiConsoleVisible`).
- **Dos mods que vem no zip, so os carregadores de mod de blueprint ficam ligados**
  (`BPModLoaderMod`, `BPML_GenericFunctions`): sao eles que fazem mod `.pak` de logica rodar.
  O resto vem ligado de fabrica e e de cliente ou de trapaca (`CheatManagerEnablerMod`,
  `ConsoleEnablerMod`, `Keybinds`...): instalar o carregador nao pode mudar o jogo de ninguem.
- **Reinstalar preserva o `UE4SS-settings.ini` e o `mods.txt` do dono** - e o que o proprio
  UE4SS manda fazer ao atualizar - e os mods dele em `Mods/`.
- **O `mods.txt` oficial vem com BOM**, que gruda no nome do primeiro mod: sai na leitura.
- **Dois layouts**: a experimental poe tudo menos o proxy em `ue4ss/`; a v3.0.x estavel deixa
  tudo solto ao lado do `.exe`. O instalador segue o que o zip trouxer, e o status acha os dois.

Acoes (argv): [--scan SCRIPT] status | loader-install [VERSAO] | loader-enable | loader-disable,
seguidas da pasta do executavel (Binaries/Win64). Instalar exige `--scan` (o
`antivirus.SCAN_SCRIPT` do painel): o zip e verificado antes de qualquer arquivo chegar ao
jogo. Toda acao imprime o progresso e termina com UMA linha JSON, que e o que o painel le.
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
import tempfile
import urllib.request
import zipfile

# A experimental e reconstruida pelo projeto a cada mudanca, sempre com esta tag.
RELEASES = "https://api.github.com/repos/UE4SS-RE/RE-UE4SS/releases/tags/experimental-latest"
RELEASE_TAG = "https://api.github.com/repos/UE4SS-RE/RE-UE4SS/releases/tags/{tag}"
# A versao vira parte da URL: so numero e ponto (o painel confere a mesma forma).
VERSION = re.compile(r"\d{1,9}\.\d{1,9}\.\d{1,9}")
# O zip normal (UE4SS_v3.0.1.zip). O zDEV comeca com "z" e nao casa: e o de debug.
ASSET = re.compile(r"^UE4SS_v[0-9][0-9A-Za-z.\-]*\.zip$")
PROXY = "dwmapi.dll"
CORE = "UE4SS.dll"
SETTINGS = "UE4SS-settings.ini"
LOG = "UE4SS.log"
MODS = "Mods"
# Pasta do carregador no layout da experimental; vazio = solto ao lado do .exe (v3.0.x).
SUBDIR = "ue4ss"
MODS_TXT = "mods.txt"
MARK = ".gamepanel-ue4ss.json"
RUNTIME_ENV = "/etc/game-runtime.env"
OVERRIDE = "dwmapi=n,b"
OWNER = "steam"
TIMEOUT = 120
LOG_TAIL = 15
# Os unicos mods de fabrica que ficam ligados: carregam mod .pak de logica, sem trapaca.
KEEP_ENABLED = ("BPModLoaderMod", "BPML_GenericFunctions")
HEADLESS = (("Debug", "ConsoleEnabled", "0"), ("Debug", "GuiConsoleEnabled", "0"),
            ("Debug", "GuiConsoleVisible", "0"), ("General", "EnableHotReloadSystem", "0"))
# Arquivo do zip que mora debaixo de um destes vai para a pasta do executavel; o resto (docs,
# readme) fica de fora.
SKIP = {"readme.md", "readme.txt", "license", "license.md", "license.txt", "changelog.md"}


def fetch(url: str) -> bytes:
    # So https do github.com chega aqui: a API e fixa (RELEASES) e o download vem da resposta
    # dela, conferida contra github.com antes de baixar.
    req = urllib.request.Request(url, headers={"User-Agent": "gamepanel"})  # noqa: S310
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310
        return r.read()


# ------------------------------------------------------------------ antivirus
# IGUAL em thunderstore_remote.py e shroudtopia_remote.py (ha teste comparando): os tres rodam
# soltos no CT e nao importam um ao outro. A regra (o que conta como achado) nao mora aqui, e
# sim no script que o painel manda; aqui so se escreve o que baixou numa pasta e se chama o script.

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


def with_dwmapi(value: str) -> str:
    """O WINEDLLOVERRIDES com a dwmapi nativa, sem mexer no resto do que o jogo decidiu."""
    return ";".join([g for g in _groups(value) if not g.startswith("dwmapi=")] + [OVERRIDE])


def without_dwmapi(value: str) -> str:
    return ";".join(g for g in _groups(value) if not g.startswith("dwmapi="))


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
    _write_overrides(env_path, with_dwmapi(old) if enabled else without_dwmapi(old))


def is_enabled(env_path: str) -> bool:
    return OVERRIDE in _groups(_read_overrides(env_path))


# ------------------------------------------------------------------ configuracao

def set_ini(text: str, section: str, key: str, value: str) -> str:
    """`key = value` dentro de `[section]`, trocando o que houver ou acrescentando."""
    lines = text.splitlines()
    head = re.compile(rf"^\s*\[{re.escape(section)}\]\s*$", re.I)
    entry = re.compile(rf"^\s*{re.escape(key)}\s*=", re.I)
    start = next((i for i, ln in enumerate(lines) if head.match(ln)), None)
    if start is None:
        return "\n".join([*lines, f"[{section}]", f"{key} = {value}"]) + "\n"
    end = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("[")), len(lines))
    for i in range(start + 1, end):
        if entry.match(lines[i]):
            lines[i] = f"{key} = {value}"
            return "\n".join(lines) + "\n"
    lines.insert(end, f"{key} = {value}")
    return "\n".join(lines) + "\n"


def server_mods_txt(text: str) -> str:
    """O mods.txt de fabrica com tudo desligado, menos os carregadores de blueprint."""
    out = []
    for line in text.lstrip("\ufeff").splitlines():
        name, sep, _ = line.partition(":")
        if sep and not line.lstrip().startswith(";"):
            name = name.strip()
            out.append(f"{name} : {1 if name in KEEP_ENABLED else 0}")
        else:
            out.append(line)
    return "\n".join(out) + "\n"


def enabled_mods(text: str) -> dict[str, bool]:
    result = {}
    for line in text.lstrip("\ufeff").splitlines():
        name, sep, flag = line.partition(":")
        if sep and not line.lstrip().startswith(";"):
            result[name.strip()] = flag.strip() == "1"
    return result


# ------------------------------------------------------------------ o carregador

def _asset_url(release: dict) -> tuple[str, str]:
    for asset in release.get("assets", []):
        url = asset.get("browser_download_url", "")
        if ASSET.match(asset.get("name", "")) and url.startswith("https://github.com/"):
            return asset["name"], url
    raise ValueError("esta versao do UE4SS nao traz o zip normal (so o de debug?)")


def loader_dir(exe_dir: str) -> str:
    """Onde mora o UE4SS.dll (e a config, o log e Mods/) deste servidor."""
    sub = os.path.join(exe_dir, SUBDIR)
    if os.path.exists(os.path.join(sub, CORE)) or not os.path.exists(os.path.join(exe_dir, CORE)):
        return sub
    return exe_dir


def release_for(version: str = "", fetcher=fetch) -> dict:
    """A release pedida (vazio = a experimental, a que funciona sob o Proton)."""
    if not version:
        return json.loads(fetcher(RELEASES))
    if not VERSION.fullmatch(version):
        raise ValueError(f"versao invalida: {version!r}")
    last: OSError | None = None
    for tag in (f"v{version}", version):
        try:
            return json.loads(fetcher(RELEASE_TAG.format(tag=tag)))
        except OSError as exc:
            last = exc
    raise ValueError(f"o UE4SS nao tem a versao {version}: {last}")


def _safe_rel(path: str) -> str:
    """Caminho de dentro do zip, relativo e sem subir de pasta; vazio = recusado."""
    rel = posixpath.normpath(path.replace("\\", "/")).lstrip("/")
    if rel in (".", "") or rel.startswith("..") or "/../" in f"/{rel}/":
        return ""
    return rel


def install_loader(exe_dir: str, fetcher=fetch, env_path: str = RUNTIME_ENV, version: str = "",
                   scan=_no_scan) -> dict:
    if not os.path.isdir(exe_dir):
        raise ValueError(f"a pasta do executavel nao existe: {exe_dir}")
    release = release_for(version, fetcher)
    name, url = _asset_url(release)
    print(f"baixando {name}")
    data = fetcher(url)
    scan([(name, data)])
    z = zipfile.ZipFile(io.BytesIO(data))
    names = [n for n in z.namelist() if not n.endswith("/")]
    proxy = next((n for n in names if posixpath.basename(n).lower() == PROXY), "")
    if not proxy or not any(posixpath.basename(n) == CORE for n in names):
        raise ValueError(f"o zip nao tem {PROXY} e {CORE}: nao e o UE4SS")
    # Tudo e relativo a pasta do dwmapi.dll dentro do zip: e ela que vai ao lado do .exe.
    prefix = proxy[: -len(posixpath.basename(proxy))]
    keep = {SETTINGS.lower(), MODS_TXT.lower()}
    count = 0
    for entry in names:
        if not entry.startswith(prefix):
            continue
        rel = _safe_rel(entry[len(prefix):])
        if not rel or posixpath.basename(rel).lower() in SKIP:
            continue
        dest = os.path.join(exe_dir, rel)
        # Configuracao que ja existe e do dono do servidor: so nasce se faltar.
        if posixpath.basename(rel).lower() in keep and os.path.exists(dest):
            continue
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with z.open(entry) as src, open(dest, "wb") as out:
            shutil.copyfileobj(src, out)
        count += 1
    base = loader_dir(exe_dir)
    settings = os.path.join(base, SETTINGS)
    mods_txt = os.path.join(base, MODS, MODS_TXT)
    if os.path.exists(mods_txt):
        # BOM fora sempre; os mods de fabrica so na primeira instalacao (abaixo).
        text = _read_text(mods_txt)
        if not _read_json(os.path.join(exe_dir, MARK)):
            text = server_mods_txt(text)
        with open(mods_txt, "w", encoding="utf-8") as f:
            f.write(text.lstrip("\ufeff"))
    if not _read_json(os.path.join(exe_dir, MARK)):
        # Primeira instalacao: sem console nem janela. Numa reinstalacao a config e do dono.
        text = _read_text(settings)
        for section, key, value in HEADLESS:
            text = set_ini(text, section, key, value)
        with open(settings, "w", encoding="utf-8") as f:
            f.write(text)
    if os.path.exists(env_path):
        set_enabled(env_path, True)
    tag = release.get("tag_name", "")
    with open(os.path.join(exe_dir, MARK), "w", encoding="utf-8") as f:
        json.dump({"version": tag, "asset": name, "pinned": bool(version)}, f)
    print(f"UE4SS {tag} em {exe_dir} ({count} arquivos; console e mods de trapaca desligados)")
    return {"loader": "UE4SS", "version": tag, "files": count}


def status(exe_dir: str, env_path: str = RUNTIME_ENV) -> dict:
    base = loader_dir(exe_dir)
    mods_dir = os.path.join(base, MODS)
    flags = enabled_mods(_read_text(os.path.join(mods_dir, MODS_TXT)))
    mods = []
    for entry in sorted(os.listdir(mods_dir)) if os.path.isdir(mods_dir) else []:
        if os.path.isdir(os.path.join(mods_dir, entry)):
            enabled = flags.get(entry, os.path.exists(os.path.join(mods_dir, entry, "enabled.txt")))
            mods.append({"name": entry, "enabled": enabled})
    mark = _read_json(os.path.join(exe_dir, MARK))
    return {
        "loader_installed": os.path.exists(os.path.join(exe_dir, PROXY)) and os.path.exists(os.path.join(base, CORE)),
        "loader": "UE4SS", "loader_version": mark.get("version", ""),
        "loader_pinned": bool(mark.get("pinned")),
        "enabled": is_enabled(env_path) if os.path.exists(env_path) else False,
        "mods": mods,
        "log": _read_text(os.path.join(base, LOG)).splitlines()[-LOG_TAIL:],
    }


def _chown(exe_dir: str) -> None:
    """O jogo roda como 'steam': precisa ler a DLL e escrever o log e a config."""
    try:
        import pwd
        pw = pwd.getpwnam(OWNER)
    except (ImportError, KeyError):
        return
    for name in (PROXY, MARK):
        with contextlib.suppress(OSError):
            os.chown(os.path.join(exe_dir, name), pw.pw_uid, pw.pw_gid)
    # A pasta do carregador inteira: na experimental e `ue4ss/`; no layout solto, so o que e dele.
    base = loader_dir(exe_dir)
    if base != exe_dir:
        walk_roots = [base]
    else:
        for name in (CORE, SETTINGS):
            with contextlib.suppress(OSError):
                os.chown(os.path.join(exe_dir, name), pw.pw_uid, pw.pw_gid)
        walk_roots = [os.path.join(exe_dir, MODS)]
    for root, dirs, files in (w for r in walk_roots for w in os.walk(r)):
        for n in (root, *[os.path.join(root, d) for d in dirs], *[os.path.join(root, f) for f in files]):
            with contextlib.suppress(OSError):
                os.chown(n, pw.pw_uid, pw.pw_gid)


def main(argv: list[str]) -> int:
    script = ""
    if argv[:1] == ["--scan"]:
        script, argv = argv[1], argv[2:]
    action, exe_dir, *rest = argv
    try:
        if action == "loader-install" and not script:
            raise ValueError("instalar sem a verificacao do antivirus nao e caminho do painel")
        if action == "status":
            result = status(exe_dir)
        elif action == "loader-install":
            result = install_loader(exe_dir, version=rest[0] if rest else "", scan=scanner(script))
        elif action in ("loader-enable", "loader-disable"):
            set_enabled(RUNTIME_ENV, action == "loader-enable")
            result = {"enabled": action == "loader-enable"}
        else:
            raise ValueError(f"acao desconhecida: {action}")
        if action != "status":
            _chown(exe_dir)
    except (ValueError, KeyError, OSError, zipfile.BadZipFile) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
