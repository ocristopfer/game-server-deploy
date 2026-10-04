"""Mods do Thunderstore (BepInEx) - roda DENTRO do CT do jogo, nao no painel.

O painel le o texto deste arquivo e o executa no container com `python3 -c`, por SSH, como
root. E assim porque o painel nao vai a internet (regra do repositorio: sem SSRF, sem
dependencia de terceiro em producao) e o CT do jogo vai: o firewall dele libera a saida
para a internet. So stdlib, e sem import do `gamepanel`: la dentro nao existe o pacote.

O que foi MEDIDO num servidor V Rising de verdade sob o Proton, e cada item aqui existe por
um desses:
- o BepInEx e todo .NET, e o `mscoree=` (desligado) que os .env de Windows usam fazia o
  Wine recusar cada DLL dele ("IL-only binary ... cannot be loaded"): sai da lista;
- o BepInEx entra pelo `winhttp.dll` do doorstop, que so e carregado com `winhttp=n,b`;
- o console do BepInEx (ligado por padrao) TRAVAVA o servidor sob o X virtual, parado sem
  CPU e sem log: fica desligado;
- a primeira subida gera o codigo do jogo inteiro e chegou a 9,4 GB de memoria.

Acoes (argv): [--scan SCRIPT] status | loader-install [VERSAO] | loader-enable | loader-disable |
loader-uninstall | plugin-install NS NOME [VERSAO] | plugin-remove NS NOME. Sem VERSAO vale a mais nova; com ela,
o pacote e as dependencias vem nas versoes que ELE declara (ver `install_plugin`). Toda acao
imprime o progresso e termina com UMA linha JSON, que e o que o painel le.

Instalar exige `--scan` (o `antivirus.SCAN_SCRIPT` do painel): tudo o que vai ser instalado
- o pacote e TODAS as dependencias - e baixado primeiro, verificado de uma vez e so entao
gravado na pasta do jogo. Achado ou verificacao que nao roda = nada e instalado.
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

API = "https://thunderstore.io/api/experimental/package/{ns}/{name}/"
API_VERSION = "https://thunderstore.io/api/experimental/package/{ns}/{name}/{version}/"
# Namespace e nome de pacote do Thunderstore: letras, numeros e sublinhado. Conferido aqui
# de novo (o painel ja confere): isto vira caminho de pasta e URL.
PART = re.compile(r"[A-Za-z0-9_]{1,64}")
# A mesma forma de versao que o painel confere (thunderstore.VERSION): vira parte da URL.
VERSION = re.compile(r"\d{1,9}\.\d{1,9}\.\d{1,9}")
# O que vem no zip de todo pacote e nao e do jogo.
SKIP = {"icon.png", "readme.md", "manifest.json", "changelog.md", "license", "license.md",
        "license.txt"}
MARK = ".gamepanel.json"
RUNTIME_ENV = "/etc/game-runtime.env"
DOORSTOP_CONFIG = "doorstop_config.ini"
OWNER = "steam"
MAX_PACKAGES = 25
TIMEOUT = 120


def fetch(url: str) -> bytes:
    # So https do thunderstore.io chega aqui: a API e fixa (API, acima) e o download vem da
    # resposta dela, nunca de quem pediu no painel.
    req = urllib.request.Request(url, headers={"User-Agent": "gamepanel"})  # noqa: S310
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310
        return r.read()


# ------------------------------------------------------------------ antivirus
# IGUAL em shroudtopia_remote.py (ha teste comparando): os dois rodam soltos no CT e nao
# importam um ao outro. A regra (o que conta como achado) nao mora aqui, e sim no script
# que o painel manda; aqui so se escreve o que baixou numa pasta e se chama o script.

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
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return default


def _read_json(path: str) -> dict:
    """O JSON do arquivo, ou vazio: arquivo que falta ou esta torto nao derruba o status."""
    with contextlib.suppress(ValueError):
        data = json.loads(_read_text(path) or "{}")
        return data if isinstance(data, dict) else {}
    return {}


def check_part(value: str) -> str:
    if not PART.fullmatch(value or ""):
        raise ValueError(f"nome de pacote invalido: {value!r}")
    return value


def check_version(value: str) -> str:
    if not VERSION.fullmatch(value or ""):
        raise ValueError(f"versao invalida: {value!r}")
    return value


def latest(ns: str, name: str, fetcher=fetch) -> dict:
    data = json.loads(fetcher(API.format(ns=check_part(ns), name=check_part(name))))
    return data["latest"]


def package_meta(ns: str, name: str, version: str = "", fetcher=fetch) -> dict:
    """Os dados de UMA versao do pacote; versao vazia = a mais nova."""
    if not version:
        return latest(ns, name, fetcher)
    url = API_VERSION.format(ns=check_part(ns), name=check_part(name), version=check_version(version))
    meta = json.loads(fetcher(url))
    # Pediu a 1.2.0 e veio outra coisa: instalar assim mesmo seria mentir na tela.
    if meta.get("version_number") != version:
        raise ValueError(f"o Thunderstore nao tem {ns}-{name}-{version}")
    return meta


def _dependency(dep: str) -> tuple[str, str, str]:
    """`ns-nome-1.2.3` como vem na lista de dependencias de um pacote."""
    parts = dep.split("-")
    if len(parts) != 3:
        raise ValueError(f"dependencia que nao entendi: {dep!r}")
    return parts[0], parts[1], parts[2]


def _safe_rel(path: str) -> str:
    """Caminho de dentro do zip, relativo e sem subir de pasta; vazio = recusado."""
    rel = posixpath.normpath(path.replace("\\", "/")).lstrip("/")
    if rel in (".", "") or rel.startswith("..") or "/../" in f"/{rel}/":
        return ""
    return rel


# ------------------------------------------------------------------ o carregador (BepInEx)

def fix_overrides(value: str) -> str:
    """O WINEDLLOVERRIDES que o BepInEx precisa, a partir do que o jogo ja tinha.

    `mscoree,mshtml=` vira `mshtml=;winhttp=n,b`: tira so o mscoree da lista DESLIGADA
    (o resto continua como o .env do jogo decidiu) e poe o winhttp nativo.
    """
    groups = []
    for group in filter(None, (g.strip() for g in value.split(";"))):
        dlls, _, mode = group.partition("=")
        names = [d for d in (x.strip() for x in dlls.split(",")) if d and d != "winhttp"]
        if mode == "":
            names = [d for d in names if d != "mscoree"]
        if names:
            groups.append(f"{','.join(names)}={mode}")
    groups.append("winhttp=n,b")
    return ";".join(groups)


def overrides_ok(value: str) -> bool:
    return fix_overrides(value) == value


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


def _set_ini(path: str, section: str, key: str, value: str) -> None:
    """Troca `key = x` dentro de `[section]`; cria a secao se o arquivo nao a tem."""
    text = _read_text(path)
    pattern = re.compile(rf"(\[{re.escape(section)}\][^\[]*?\n{re.escape(key)}\s*=\s*)[^\n]*", re.S)
    if pattern.search(text):
        text = pattern.sub(lambda m: m.group(1) + value, text, count=1)
    else:
        text = text.rstrip("\n") + ("\n\n" if text else "") + f"[{section}]\n{key} = {value}\n"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def set_enabled(game_dir: str, enabled: bool) -> None:
    _set_ini(os.path.join(game_dir, DOORSTOP_CONFIG), "General", "enabled",
             "true" if enabled else "false")


# ------------------------------------------------------------------ servidor Linux nativo
# O Valheim (e todo Unity Linux) carrega o BepInEx pelo doorstop .so, por LD_PRELOAD, e nao por
# DLL do Wine. As variaveis sao as do start_server_bepinex.sh do BepInExPack_Valheim 5.4.2351,
# lidas do pacote; aqui elas vao num drop-in do systemd, com caminho ABSOLUTO (o script usa
# ./, relativo a pasta do jogo), para nao precisar trocar o wrapper de partida do jogo.
# Desligar e apagar o drop-in: o servidor sobe sem nenhum codigo do BepInEx.
# NAO TESTADO num servidor de verdade ainda.
SYSTEMD_DIR = "/etc/systemd/system"
DROPIN = "gamepanel-bepinex.conf"
UNIT = re.compile(r"[A-Za-z0-9_.@-]{1,120}\.service")


def dropin_path(unit: str, systemd_dir: str = SYSTEMD_DIR) -> str:
    if not UNIT.fullmatch(unit or ""):
        raise ValueError(f"servico invalido: {unit!r}")
    return posixpath.join(systemd_dir, f"{unit}.d", DROPIN)


def dropin_text(game_dir: str) -> str:
    libs = posixpath.join(game_dir, "doorstop_libs")
    preloader = posixpath.join(game_dir, "BepInEx", "core", "BepInEx.Preloader.dll")
    return ("[Service]\n"
            "Environment=DOORSTOP_ENABLED=1\n"
            f"Environment=DOORSTOP_TARGET_ASSEMBLY={preloader}\n"
            f"Environment=LD_LIBRARY_PATH={libs}:{posixpath.join(game_dir, 'linux64')}\n"
            f"Environment=LD_PRELOAD={posixpath.join(libs, 'libdoorstop_x64.so')}\n")


def set_linux_enabled(game_dir: str, unit: str, enabled: bool) -> None:
    # SYSTEMD_DIR e _daemon_reload lidos na hora, pelo nome do modulo: e o que deixa o teste
    # troca-los sem um parametro a mais em cada funcao do caminho.
    path = dropin_path(unit, SYSTEMD_DIR)
    if enabled:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(dropin_text(game_dir))
    else:
        with contextlib.suppress(FileNotFoundError):
            os.remove(path)
    # Sem o daemon-reload o systemd segue com o ambiente antigo ate o proximo boot.
    _daemon_reload()


def _daemon_reload() -> None:
    subprocess.run(["systemctl", "daemon-reload"], check=False)  # noqa: S607


def _extract_pack(z: zipfile.ZipFile, prefix: str, game_dir: str, created: set[str]) -> tuple[int, set[str]]:
    """Grava na raiz do jogo o que esta sob `prefix`; devolve (arquivos, nomes de raiz CRIADOS).

    So o que o pacote cria e anotado - e so isso o desinstalar apaga: o que ja existia antes da
    primeira instalacao e do jogo, e o que uma instalacao anterior criou (`created`) segue nosso.
    """
    created = set(created)
    count = 0
    for entry in z.namelist():
        rel = _safe_rel(entry[len(prefix):]) if entry.startswith(prefix) and not entry.endswith("/") else ""
        if not rel:
            continue
        top = rel.split("/", 1)[0]
        if not os.path.exists(os.path.join(game_dir, top)):
            created.add(top)
        dest = os.path.join(game_dir, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with z.open(entry) as src, open(dest, "wb") as out:
            shutil.copyfileobj(src, out)
        count += 1
    return count, created


def install_loader(game_dir: str, ns: str, name: str, fetcher=fetch, env_path: str = RUNTIME_ENV,
                   version: str = "", scan=_no_scan, unit: str = "") -> dict:
    meta = package_meta(ns, name, version, fetcher)
    print(f"baixando {meta['full_name']}")
    data = fetcher(meta["download_url"])
    scan([(meta["full_name"], data)])
    z = zipfile.ZipFile(io.BytesIO(data))
    # O pacote traz uma pasta (BepInExPack_V_Rising/) com o que vai na RAIZ do jogo: e a
    # que contem BepInEx/core. O resto do zip (icone, README) fica de fora.
    core = next((n for n in z.namelist() if "BepInEx/core/" in n), "")
    if not core:
        raise ValueError("o pacote nao tem BepInEx/core: nao e um carregador BepInEx")
    prefix = core[: core.index("BepInEx/core/")]
    previous = _read_json(os.path.join(game_dir, "BepInEx", MARK))
    count, created = _extract_pack(z, prefix, game_dir, set(previous.get("files", [])))
    set_enabled(game_dir, True)
    _set_ini(os.path.join(game_dir, "BepInEx", "config", "BepInEx.cfg"), "Logging.Console", "Enabled", "false")
    # O WINE_DLL_OVERRIDES de antes do BepInEx, para o desinstalar devolver (o fix_overrides tira
    # o mscoree da lista desligada, e isso nao se desfaz sem saber como estava).
    overrides_before = previous.get("overrides_before")
    if unit:
        # Linux nativo: nada de Wine; o carregador entra pelo drop-in do systemd.
        set_linux_enabled(game_dir, unit, True)
    else:
        old = _read_overrides(env_path)
        if os.path.exists(env_path):
            if overrides_before is None:
                overrides_before = old
            _write_overrides(env_path, fix_overrides(old))
    with open(os.path.join(game_dir, "BepInEx", MARK), "w", encoding="utf-8") as f:
        json.dump({"full_name": meta["full_name"], "version": meta["version_number"],
                   "pinned": bool(version), "files": sorted(created),
                   "overrides_before": overrides_before}, f)
    print(f"{count} arquivos do carregador em {game_dir}")
    return {"loader": meta["full_name"], "files": count}


# O que um pacote do BepInEx poe na raiz do jogo, para instalacao feita antes de o painel anotar
# a lista (o .gamepanel.json sem "files"). So nomes do proprio BepInEx/doorstop.
BEPINEX_ROOT = ("BepInEx", DOORSTOP_CONFIG, "winhttp.dll", ".doorstop_version", "doorstop_libs",
                "dotnet", "start_server_bepinex.sh")


def without_winhttp(value: str) -> str:
    return ";".join(g for g in (x.strip() for x in value.split(";")) if g and g != "winhttp=n,b")


def set_loader(game_dir: str, unit: str, enabled: bool) -> None:
    set_enabled(game_dir, enabled)
    if unit:
        set_linux_enabled(game_dir, unit, enabled)


def uninstall_loader(game_dir: str, env_path: str = RUNTIME_ENV, unit: str = "") -> dict:
    """Tira o BepInEx e o que ele mudou no jogo: o jogo volta a subir sem nenhum codigo dele.

    Os plugins moram dentro de BepInEx/ e saem junto (a tela avisa antes). O WINE_DLL_OVERRIDES
    volta ao de antes da instalacao; sem ele anotado, so o winhttp=n,b sai (o mscoree que o
    BepInEx religou fica - inofensivo sem o BepInEx).
    """
    mark = _read_json(os.path.join(game_dir, "BepInEx", MARK))
    names = mark.get("files") or BEPINEX_ROOT
    if unit:
        set_linux_enabled(game_dir, unit, False)
    elif os.path.exists(env_path):
        before = mark.get("overrides_before")
        _write_overrides(env_path, before if isinstance(before, str) else without_winhttp(_read_overrides(env_path)))
    removed = []
    for name in names:
        # So um nome da raiz, nunca um caminho: o que vem da marca nao pode sair da pasta do jogo.
        if not name or name in (".", "..") or "/" in name or "\\" in name:
            continue
        path = os.path.join(game_dir, name)
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        elif os.path.lexists(path):
            os.remove(path)
        else:
            continue
        removed.append(name)
    print(f"BepInEx desinstalado de {game_dir}: {', '.join(removed) or 'nada a apagar'}")
    return {"uninstalled": True, "removed": removed}


# ------------------------------------------------------------------ plugins

def _plugins_dir(game_dir: str) -> str:
    return os.path.join(game_dir, "BepInEx", "plugins")


def _plugin_rel(entry: str) -> tuple[str, str]:
    """Para onde vai um arquivo do zip de um plugin: ('plugins'|'config', caminho relativo)."""
    rel = _safe_rel(entry)
    if not rel or posixpath.basename(rel).lower() in SKIP:
        return "", ""
    for head, target in (("BepInEx/plugins/", "plugins"), ("plugins/", "plugins"),
                         ("BepInEx/config/", "config"), ("config/", "config")):
        if rel.startswith(head):
            return target, rel[len(head):]
    return "plugins", rel


def _install_one(game_dir: str, meta: dict, data: bytes, pinned: bool) -> int:
    ns, name = meta["full_name"].split("-")[0], meta["name"]
    target = os.path.join(_plugins_dir(game_dir), f"{check_part(ns)}-{check_part(name)}")
    shutil.rmtree(target, ignore_errors=True)  # versao nova substitui a velha por inteiro
    os.makedirs(target, exist_ok=True)
    z = zipfile.ZipFile(io.BytesIO(data))
    count = 0
    for entry in z.namelist():
        if entry.endswith("/"):
            continue
        kind, rel = _plugin_rel(entry)
        if not kind:
            continue
        base = target if kind == "plugins" else os.path.join(game_dir, "BepInEx", "config")
        dest = os.path.join(base, rel)
        # Config que ja existe e do dono do servidor: o pacote so traz o padrao.
        if kind == "config" and os.path.exists(dest):
            continue
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with z.open(entry) as src, open(dest, "wb") as out:
            shutil.copyfileobj(src, out)
        count += 1
    with open(os.path.join(target, MARK), "w", encoding="utf-8") as f:
        json.dump({"full_name": meta["full_name"], "version": meta["version_number"],
                   "dependencies": meta.get("dependencies", []), "pinned": pinned}, f)
    return count


def install_plugin(game_dir: str, ns: str, name: str, fetcher=fetch, loader_ns: str = "BepInEx",
                   version: str = "", scan=_no_scan) -> dict:
    """O pacote e as dependencias dele (menos o proprio BepInEx, que tem botao proprio).

    Com versao fixada, as dependencias vem na versao que AQUELA versao declara, e nao na mais
    nova: quem fixa uma versao quer o conjunto que o autor testou, e uma dependencia nova
    demais e justamente o tipo de coisa que quebra o mod que se quis segurar. A consequencia:
    uma dependencia dividida com outro mod pode voltar para uma versao mais velha.

    Baixa TUDO antes de gravar qualquer coisa: a verificacao e uma so, e uma dependencia
    recusada nao deixa o mod principal instalado pela metade.
    """
    pinned = bool(version)
    queue = [(check_part(ns), check_part(name), check_version(version) if pinned else "")]
    done: set[tuple[str, str]] = set()
    downloaded: list[tuple[dict, bytes]] = []
    while queue:
        pns, pname, pversion = queue.pop(0)
        if (pns, pname) in done:
            continue
        done.add((pns, pname))
        if len(done) > MAX_PACKAGES:
            raise ValueError(f"mais de {MAX_PACKAGES} pacotes na arvore de dependencias")
        meta = package_meta(pns, pname, pversion, fetcher)
        print(f"baixando {meta['full_name']}")
        downloaded.append((meta, fetcher(meta["download_url"])))
        for dep in meta.get("dependencies", []):
            dns, dname, dversion = _dependency(dep)
            if dns == loader_ns and dname.startswith("BepInExPack"):
                continue
            queue.append((dns, dname, dversion if pinned else ""))
    scan([(meta["full_name"], data) for meta, data in downloaded])
    installed = []
    for meta, data in downloaded:
        print(f"instalando {meta['full_name']}")
        installed.append({"full_name": meta["full_name"], "files": _install_one(game_dir, meta, data, pinned)})
    return {"installed": installed}


def remove_plugin(game_dir: str, ns: str, name: str) -> dict:
    target = os.path.join(_plugins_dir(game_dir), f"{check_part(ns)}-{check_part(name)}")
    existed = os.path.isdir(target)
    shutil.rmtree(target, ignore_errors=True)
    return {"removed": existed}


def status(game_dir: str, env_path: str = RUNTIME_ENV, unit: str = "") -> dict:
    plugins = []
    pdir = _plugins_dir(game_dir)
    for entry in sorted(os.listdir(pdir)) if os.path.isdir(pdir) else []:
        # Pasta posta a mao, sem a marca do instalador: aparece pelo nome.
        # Marca de antes da versao fixavel nao tem `pinned`: foi a mais nova, entao False.
        plugins.append({"dir": entry, "full_name": entry, "version": "", "pinned": False,
                        **_read_json(os.path.join(pdir, entry, MARK))})
    loader = _read_json(os.path.join(game_dir, "BepInEx", MARK))
    ini = _read_text(os.path.join(game_dir, DOORSTOP_CONFIG))
    if unit:
        enabled = os.path.exists(dropin_path(unit, SYSTEMD_DIR))
    else:
        enabled = re.search(r"(?m)^enabled\s*=\s*true", ini) is not None
    mem_kb = 0
    for line in _read_text("/proc/meminfo").splitlines():
        if line.startswith("MemTotal:") and line.split()[1].isdigit():
            mem_kb = int(line.split()[1])
    return {
        "loader_installed": os.path.isdir(os.path.join(game_dir, "BepInEx", "core")),
        "loader": loader.get("full_name", ""), "loader_version": loader.get("version", ""),
        "loader_pinned": bool(loader.get("pinned")),
        "enabled": enabled,
        # Linux nativo nao tem Wine: nao ha ajuste dele para conferir.
        "overrides_ok": bool(unit) or not os.path.exists(env_path) or overrides_ok(_read_overrides(env_path)),
        "memory_mb": mem_kb // 1024,
        "plugins": plugins,
    }


def _chown(path: str) -> None:
    """O jogo roda como 'steam' e precisa ler (e o BepInEx, escrever) o que entrou."""
    try:
        import pwd
        pw = pwd.getpwnam(OWNER)
    except (ImportError, KeyError):
        return
    for root, dirs, files in os.walk(path):
        for n in (root, *[os.path.join(root, d) for d in dirs], *[os.path.join(root, f) for f in files]):
            with contextlib.suppress(OSError):
                os.chown(n, pw.pw_uid, pw.pw_gid)


INSTALL_ACTIONS = ("loader-install", "plugin-install")


def run(action: str, game_dir: str, loader: tuple[str, str], rest: list[str], unit: str, scan) -> dict:
    """Executa uma acao; o `main` so le o argv e transforma erro em JSON."""
    loader_ns, loader_name = loader
    if action == "status":
        return status(game_dir, unit=unit)
    if action == "loader-install":
        return install_loader(game_dir, loader_ns, loader_name, version=rest[0] if rest else "", scan=scan,
                              unit=unit)
    if action in ("loader-enable", "loader-disable"):
        set_loader(game_dir, unit, action == "loader-enable")
        return {"enabled": action == "loader-enable"}
    if action == "loader-uninstall":
        return uninstall_loader(game_dir, unit=unit)
    if action == "plugin-install":
        return install_plugin(game_dir, rest[0], rest[1], loader_ns=loader_ns,
                              version=rest[2] if len(rest) > 2 else "", scan=scan)
    if action == "plugin-remove":
        return remove_plugin(game_dir, rest[0], rest[1])
    raise ValueError(f"acao desconhecida: {action}")


def main(argv: list[str]) -> int:
    script = unit = ""
    if argv[:1] == ["--scan"]:
        script, argv = argv[1], argv[2:]
    # Servidor Linux nativo (Valheim): o carregador entra por drop-in do systemd deste servico.
    if argv[:1] == ["--unit"]:
        unit, argv = argv[1], argv[2:]
    action, game_dir, loader_ns, loader_name, *rest = argv
    scan = scanner(script) if script else _no_scan
    try:
        if action in INSTALL_ACTIONS and not script:
            raise ValueError("instalar sem a verificacao do antivirus nao e caminho do painel")
        result = run(action, game_dir, (loader_ns, loader_name), rest, unit, scan)
        if action not in ("status", "loader-uninstall"):
            _chown(os.path.join(game_dir, "BepInEx"))
    except (ValueError, KeyError, OSError, zipfile.BadZipFile) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
