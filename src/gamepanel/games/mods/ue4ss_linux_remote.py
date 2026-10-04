"""UE4SS de jogo Unreal LINUX nativo (o nosso fork do oficial) - roda DENTRO do CT do jogo.

Mesmo desenho dos outros instaladores remotos: o painel le este texto e o executa no
container com `python3 -c`, por SSH, como root. So stdlib e sem import do `gamepanel`.

O carregador e o UE4SS OFICIAL compilado para Linux (ocristopfer/RE-UE4SS, branch `linux`), e
nao mais um port: os mesmos mecanismos (varredura do patternsleuth, UE4SS_Signatures,
VTableLayout.ini, mods Lua), com o que o Linux pede e os layouts de cada versao do motor gerados
a partir do codigo da Epic. Provado em servidor de verdade (Docker) no Dragonwilds (UE 5.6.1) e no
Palworld (UE 5.1.1): Lua, FindFirstOf, RegisterHook de Blueprint e nativo, ExecuteInGameThread.
O antigo modo "fork" (ocristopfer/ue4ss-linux, UE4SS_Addresses.ini) e o port XarminaEu sairam:
os dois derrubavam o Palworld.

O que a instalacao faz, cada passo com o motivo:
- **Tag fixa do perfil** (`--release`), e cada arquivo conferido contra o SHA256SUMS do release
  ANTES do antivirus.
- **O layout oficial: `ue4ss/` ao lado do executavel** (libUE4SS.so, UE4SS-settings.ini, Mods/).
  O UE4SS acha a config, os mods e o log na pasta da propria biblioteca.
- **O .so e trocado ao lado e movido por cima** (`rename`): copiar sobre o arquivo com o servidor
  rodando corrompe o mapeamento na memoria.
- **Arquivos do .sym, quando o servidor traz um** (`--symfiles`, o texto do ue_sym_layout do
  painel): VTableLayout.ini e UE4SS_Signatures/*.lua deste executavel. Um motor modificado pelo
  estudio (o Dragonwilds acrescenta virtuais na AActor) so roda certo com eles. Sao refeitos a
  cada instalacao: um update do jogo muda os enderecos, e os velhos derrubariam o servidor.
- **Config e mods.txt do dono preservados**; o `Mods/shared` (as bibliotecas Lua que muitos mods
  pedem, UEHelpers) vem do release e e trocado por inteiro.
- **Migra a instalacao do fork antigo** (tudo ao lado do executavel): os mods Lua vao para
  `ue4ss/Mods`, e so os arquivos que o fork antigo escrevia saem.
- **LD_PRELOAD num drop-in do systemd**, sem trocar o script de partida do jogo. A biblioteca so
  inicia num processo cujo executavel tem `-Linux-` no nome: o script e o que ele chama ficam de
  fora. Desligar e apagar o drop-in (nenhum codigo do UE4SS roda, sem apagar mod nenhum).

Acoes (argv): [--scan SCRIPT] --unit SERVICO [--release TAG --engine X.Y --symfiles SCRIPT]
status|loader-install|loader-enable|loader-disable|loader-uninstall, seguidas da pasta do executavel
(Binaries/Linux). Termina com UMA linha JSON.
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
import tarfile
import tempfile
import urllib.request

RELEASE = "https://api.github.com/repos/ocristopfer/RE-UE4SS/releases/tags/{tag}"
RELEASE_TAG = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}")
ENGINE = re.compile(r"(\d{1,2})\.(\d{1,2})")
SHA256 = re.compile(r"[0-9a-f]{64}")
SUMS = "SHA256SUMS"
LIB = "libUE4SS.so"
SETTINGS = "UE4SS-settings.ini"
SHARED = "ue4ss-mods-shared.tar.gz"
TEMPLATES = "VTableLayoutTemplates.tar.gz"
RELEASE_FILES = (LIB, SETTINGS, SHARED, TEMPLATES)
UE4SS_DIR = "ue4ss"
LOG = "UE4SS.log"
MODS = "Mods"
MODS_TXT = "mods.txt"
SHARED_DIR = "shared"
VTABLE_INI = "VTableLayout.ini"
SIGNATURES_DIR = "UE4SS_Signatures"
# Cabecalho que o ue_sym_layout poe no ini: so o que tem ele e apagado ao reinstalar sem .sym.
GENERATED_MARK = "; Gerado pelo painel"
SIGNATURE_FILES = ("FName_ToString.lua", "FName_Constructor.lua", "StaticConstructObject.lua", "GNatives.lua")
MARK = ".gamepanel-ue4ss-linux.json"
# O que o fork antigo (ocristopfer/ue4ss-linux) deixava ao lado do executavel.
OLD_FILES = (LIB, SETTINGS, LOG, "UE4SS_Addresses.ini", VTABLE_INI, "MemberVariableLayout.ini", MARK)
SYSTEMD_DIR = "/etc/systemd/system"
DROPIN = "gamepanel-ue4ss.conf"
UNIT = re.compile(r"[A-Za-z0-9_.@-]{1,120}\.service")
OWNER = "steam"
TIMEOUT = 120
# Varrer o .sym (300 MB, ~12 milhoes de registros) e o executavel leva da ordem de um minuto.
SYMFILES_TIMEOUT = 900
LOG_TAIL = 15


def fetch(url: str) -> bytes:
    # So https do github.com chega aqui: a API e fixa (RELEASE) e o download vem da resposta
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


def _write(path: str, data: bytes) -> None:
    staged = path + ".new"
    with open(staged, "wb") as f:
        f.write(data)
    os.replace(staged, path)


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
            f.write(f"[Service]\nEnvironment=LD_PRELOAD={posixpath.join(exe_dir, UE4SS_DIR, LIB)}\n")
    else:
        with contextlib.suppress(FileNotFoundError):
            os.remove(path)
    # Sem o daemon-reload o systemd segue com o ambiente antigo ate o proximo boot.
    _daemon_reload()


# ------------------------------------------------------------------ o release

class Release:
    """O que a instalacao precisa saber do perfil: a tag do release, a versao do motor e o
    gerador dos arquivos do .sym."""

    def __init__(self, tag: str, engine: str, symfiles_script: str) -> None:
        if not RELEASE_TAG.fullmatch(tag or ""):
            raise ValueError(f"tag do release invalida: {tag!r}")
        if not ENGINE.fullmatch(engine or ""):
            raise ValueError(f"versao do motor invalida: {engine!r}")
        self.tag, self.engine, self.symfiles_script = tag, engine, symfiles_script

    @property
    def template_name(self) -> str:
        """VTableLayout_5_06_Template.ini para o motor 5.6 (o nome dos templates do UE4SS)."""
        found = ENGINE.fullmatch(self.engine)
        if not found:
            raise ValueError(f"versao do motor invalida: {self.engine!r}")
        major, minor = found.groups()
        return f"VTableLayout_{int(major)}_{int(minor):02d}_Template.ini"


def parse_sums(text: str) -> dict[str, str]:
    """`sha256sum` -> {nome: hash}. Linha torta e ignorada: arquivo sem hash e recusado depois."""
    sums = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and SHA256.fullmatch(parts[0]):
            sums[parts[1].lstrip("*")] = parts[0]
    return sums


def release_files(release: Release, fetcher=fetch) -> dict[str, bytes]:
    """Os arquivos do release, cada um conferido contra o SHA256SUMS dele."""
    data = json.loads(fetcher(RELEASE.format(tag=release.tag)))
    urls = {a.get("name", ""): a.get("browser_download_url", "") for a in data.get("assets", [])}
    for name in (SUMS, *RELEASE_FILES):
        if not urls.get(name, "").startswith("https://github.com/"):
            raise ValueError(f"o release {release.tag} nao traz {name}")
    sums = parse_sums(fetcher(urls[SUMS]).decode("utf-8", "replace"))
    files = {}
    for name in RELEASE_FILES:
        print(f"baixando {name}")
        blob = fetcher(urls[name])
        if hashlib.sha256(blob).hexdigest() != sums.get(name):
            raise ValueError(f"{name} nao confere com o SHA256SUMS do release: nada foi instalado")
        files[name] = blob
    return files


def _safe_members(tar: tarfile.TarFile, root: str) -> list[tarfile.TarInfo]:
    """So arquivo e pasta comuns, dentro de `root/`: nada de caminho absoluto, `..` ou link."""
    members = []
    for member in tar.getmembers():
        name = posixpath.normpath(member.name)
        if name.startswith(("/", "..")) or not (name == root or name.startswith(root + "/")):
            raise ValueError(f"o pacote traz um caminho inesperado: {member.name!r}")
        if not (member.isfile() or member.isdir()):
            raise ValueError(f"o pacote traz algo que nao e arquivo: {member.name!r}")
        members.append(member)
    return members


def install_shared(mods_dir: str, data: bytes) -> None:
    """Troca o Mods/shared inteiro pelo do release (as bibliotecas Lua; mod do dono nao mora ali)."""
    target = os.path.join(mods_dir, SHARED_DIR)
    staged = target + ".new"
    shutil.rmtree(staged, ignore_errors=True)
    os.makedirs(staged)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in _safe_members(tar, SHARED_DIR):
            src = tar.extractfile(member) if member.isfile() else None
            if src is None:
                continue
            path = os.path.join(staged, posixpath.relpath(posixpath.normpath(member.name), SHARED_DIR))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with src, open(path, "wb") as dst:
                shutil.copyfileobj(src, dst)
    shutil.rmtree(target, ignore_errors=True)
    os.replace(staged, target)


def template_text(release: Release, data: bytes) -> str:
    """O template de VTableLayout desta versao do motor, de dentro do pacote do release."""
    wanted = f"VTableLayoutTemplates/{release.template_name}"
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in _safe_members(tar, "VTableLayoutTemplates"):
            src = tar.extractfile(member) if member.isfile() else None
            if src is not None and posixpath.normpath(member.name) == wanted:
                return src.read().decode("utf-8", "replace")
    raise ValueError(f"o release nao tem o template {release.template_name}: motor {release.engine} nao suportado")


# ------------------------------------------------------------------ arquivos do .sym

def find_executable(exe_dir: str) -> str:
    """O executavel do servidor: o arquivo da pasta que tem um `.sym` ao lado ('' se nenhum)."""
    for name in sorted(os.listdir(exe_dir)):
        path = os.path.join(exe_dir, name)
        if os.path.isfile(path) and os.path.isfile(path + ".sym"):
            return path
    return ""


def generate_symfiles(executable: str, script: str, template: str) -> dict[str, str]:
    """{caminho relativo a ue4ss/: texto} pelo gerador do painel, a partir do .sym."""
    print(f"gerando VTableLayout.ini e UE4SS_Signatures a partir de {posixpath.basename(executable)}.sym")
    sys.stdout.flush()
    with tempfile.NamedTemporaryFile("w", suffix=".ini", encoding="utf-8", delete=False) as f:
        f.write(template)
        template_path = f.name
    try:
        # O script e o gerador do painel (texto fixo dele); o caminho foi achado nesta pasta.
        proc = subprocess.run(["python3", "-c", script, executable, template_path],  # noqa: S603, S607
                              capture_output=True, text=True, check=False, timeout=SYMFILES_TIMEOUT)
    finally:
        os.remove(template_path)
    if proc.returncode != 0:
        raise ValueError(f"o gerador dos arquivos do .sym falhou: {(proc.stderr or '').strip()[-300:]}")
    result = json.loads(proc.stdout.strip().splitlines()[-1])
    for line in result.get("report", []):
        print(f"  {line}")
    files = result.get("files", {})
    allowed = {VTABLE_INI} | {f"{SIGNATURES_DIR}/{n}" for n in SIGNATURE_FILES}
    if not isinstance(files, dict) or set(files) - allowed:
        raise ValueError("o gerador devolveu arquivos inesperados: nada foi gravado")
    return files


def remove_generated(ue4ss_dir: str) -> None:
    """Apaga o que um .sym gerou antes - so os arquivos do painel, nunca um ini escrito a mao."""
    ini = os.path.join(ue4ss_dir, VTABLE_INI)
    if _read_text(ini).startswith(GENERATED_MARK):
        os.remove(ini)
    for name in SIGNATURE_FILES:
        with contextlib.suppress(FileNotFoundError):
            os.remove(os.path.join(ue4ss_dir, SIGNATURES_DIR, name))


# ------------------------------------------------------------------ instalacao

def migrate_old_layout(exe_dir: str, ue4ss_dir: str) -> None:
    """O fork antigo deixava tudo ao lado do executavel: os mods Lua vem para ue4ss/Mods e os
    arquivos dele saem. So age se a marca dele estiver la (instalacao do proprio painel)."""
    if not os.path.exists(os.path.join(exe_dir, MARK)):
        return
    old_mods, new_mods = os.path.join(exe_dir, MODS), os.path.join(ue4ss_dir, MODS)
    if os.path.isdir(old_mods) and not os.path.exists(new_mods):
        print("movendo os mods Lua da instalacao antiga para ue4ss/Mods")
        os.replace(old_mods, new_mods)
    for name in OLD_FILES:
        with contextlib.suppress(FileNotFoundError):
            os.remove(os.path.join(exe_dir, name))


def install_loader(exe_dir: str, unit: str, release: Release, fetcher=fetch, scan=_no_scan) -> dict:
    if not os.path.isdir(exe_dir):
        raise ValueError(f"a pasta do executavel nao existe: {exe_dir}")
    dropin_path(unit)  # confere o servico antes de baixar qualquer coisa
    files = release_files(release, fetcher)
    scan(sorted(files.items()))
    executable = find_executable(exe_dir)
    symfiles: dict[str, str] = {}
    if executable:
        if not release.symfiles_script:
            raise ValueError("o servidor traz .sym, mas o painel nao mandou o gerador dos arquivos dele")
        # ANTES de mexer na pasta: um .sym que o gerador nao entende para tudo sem meia instalacao.
        symfiles = generate_symfiles(executable, release.symfiles_script, template_text(release, files[TEMPLATES]))
    ue4ss_dir = os.path.join(exe_dir, UE4SS_DIR)
    os.makedirs(ue4ss_dir, exist_ok=True)
    migrate_old_layout(exe_dir, ue4ss_dir)
    target = os.path.join(ue4ss_dir, LIB)
    staged = target + ".new"
    with open(staged, "wb") as f:
        f.write(files[LIB])
    os.chmod(staged, 0o755)  # noqa: S103
    # Por cima com rename: o servidor pode estar com o .so velho mapeado na memoria.
    os.replace(staged, target)
    settings = os.path.join(ue4ss_dir, SETTINGS)
    if not os.path.exists(settings):
        _write(settings, files[SETTINGS])
    mods_dir = os.path.join(ue4ss_dir, MODS)
    os.makedirs(mods_dir, exist_ok=True)
    install_shared(mods_dir, files[SHARED])
    mods_txt = os.path.join(mods_dir, MODS_TXT)
    if not os.path.exists(mods_txt):
        _write(mods_txt, b"")
    remove_generated(ue4ss_dir)
    for rel, text in symfiles.items():
        path = os.path.join(ue4ss_dir, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _write(path, text.encode("utf-8"))
    set_enabled(exe_dir, unit, True)
    with open(os.path.join(ue4ss_dir, MARK), "w", encoding="utf-8") as f:
        json.dump({"version": release.tag, "sym_files": sorted(symfiles)}, f)
    extra = f", {len(symfiles)} arquivo(s) do .sym" if symfiles else ", layouts embutidos (sem .sym)"
    print(f"UE4SS {release.tag} em {ue4ss_dir} (LD_PRELOAD no {unit}{extra})")
    return {"loader": "UE4SS Linux", "version": release.tag}


def uninstall_loader(exe_dir: str, unit: str) -> dict:
    """Tira o UE4SS: o drop-in (o jogo volta a subir sem LD_PRELOAD) e a pasta ue4ss/ inteira.

    Os mods Lua moram em ue4ss/Mods e saem junto (a tela avisa antes); os .pak do jogo nao sao
    do UE4SS e ficam. Sobra da instalacao do fork antigo (ao lado do executavel, com a marca
    dele) sai tambem, com o Mods/ dele - so os nomes que o fork escrevia.
    """
    set_enabled(exe_dir, unit, False)
    removed = []
    ue4ss_dir = os.path.join(exe_dir, UE4SS_DIR)
    if os.path.isdir(ue4ss_dir) and not os.path.islink(ue4ss_dir):
        shutil.rmtree(ue4ss_dir)
        removed.append(UE4SS_DIR)
    if os.path.exists(os.path.join(exe_dir, MARK)):
        for name in (*OLD_FILES, MODS):
            path = os.path.join(exe_dir, name)
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path)
            elif os.path.lexists(path):
                os.remove(path)
            else:
                continue
            removed.append(name)
    print(f"UE4SS desinstalado de {exe_dir}: {', '.join(removed) or 'nada a apagar'} (sem LD_PRELOAD no {unit})")
    return {"uninstalled": True, "removed": removed}


def enabled_mods(text: str) -> dict[str, bool]:
    result = {}
    for line in text.lstrip("﻿").splitlines():
        name, sep, flag = line.partition(":")
        if sep and not line.lstrip().startswith(";"):
            result[name.strip()] = flag.strip() == "1"
    return result


def status(exe_dir: str, unit: str) -> dict:
    ue4ss_dir = os.path.join(exe_dir, UE4SS_DIR)
    mods_dir = os.path.join(ue4ss_dir, MODS)
    flags = enabled_mods(_read_text(os.path.join(mods_dir, MODS_TXT)))
    mods = []
    for entry in sorted(os.listdir(mods_dir)) if os.path.isdir(mods_dir) else []:
        # `shared` e biblioteca, nao mod: nao entra na lista nem tem liga/desliga.
        if entry != SHARED_DIR and os.path.isdir(os.path.join(mods_dir, entry)):
            mods.append({"name": entry, "enabled": flags.get(
                entry, os.path.exists(os.path.join(mods_dir, entry, "enabled.txt")))})
    mark = _read_json(os.path.join(ue4ss_dir, MARK))
    return {
        "loader_installed": os.path.exists(os.path.join(ue4ss_dir, LIB)),
        "loader": "UE4SS Linux", "loader_version": mark.get("version", ""),
        "loader_pinned": False,
        "sym_files": mark.get("sym_files", []),
        "enabled": os.path.exists(dropin_path(unit)),
        # A instalacao do fork antigo ainda no lugar: reinstalar migra.
        "old_layout": os.path.exists(os.path.join(exe_dir, MARK)),
        "mods": mods,
        "log": _read_text(os.path.join(ue4ss_dir, LOG)).splitlines()[-LOG_TAIL:],
    }


def _chown(exe_dir: str) -> None:
    try:
        import pwd
        pw = pwd.getpwnam(OWNER)
    except (ImportError, KeyError):
        return
    # O jogo roda como steam e o UE4SS escreve o log e as configs dentro de ue4ss/.
    for root, dirs, files in os.walk(os.path.join(exe_dir, UE4SS_DIR)):
        for n in (root, *[os.path.join(root, d) for d in dirs], *[os.path.join(root, f) for f in files]):
            with contextlib.suppress(OSError):
                os.chown(n, pw.pw_uid, pw.pw_gid)


def main(argv: list[str]) -> int:
    script = unit = ""
    release_args: dict[str, str] = {}
    if argv[:1] == ["--scan"]:
        script, argv = argv[1], argv[2:]
    if argv[:1] == ["--unit"]:
        unit, argv = argv[1], argv[2:]
    while argv[:1] and argv[0] in ("--release", "--engine", "--symfiles"):
        release_args[argv[0][2:]], argv = argv[1], argv[2:]
    action, exe_dir, *_rest = argv
    try:
        if action == "loader-install" and not script:
            raise ValueError("instalar sem a verificacao do antivirus nao e caminho do painel")
        if action == "status":
            result = status(exe_dir, unit)
        elif action == "loader-install":
            release = Release(release_args.get("release", ""), release_args.get("engine", ""),
                              release_args.get("symfiles", ""))
            result = install_loader(exe_dir, unit, release, scan=scanner(script))
        elif action in ("loader-enable", "loader-disable"):
            set_enabled(exe_dir, unit, action == "loader-enable")
            result = {"enabled": action == "loader-enable"}
        elif action == "loader-uninstall":
            result = uninstall_loader(exe_dir, unit)
        else:
            raise ValueError(f"acao desconhecida: {action}")
        if action not in ("status", "loader-uninstall"):
            _chown(exe_dir)
    except (ValueError, KeyError, OSError, tarfile.TarError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
