"""Mods do Satisfactory (SML e o que roda nele) - roda DENTRO do CT do jogo, nao no painel.

Mesmo desenho dos outros instaladores remotos: o painel le este texto e o executa no
container com `python3 -c`, por SSH, como root. So stdlib e sem import do `gamepanel`.

Por que a API do ficsit.app, e nao o ficsit-cli: o ficsit-cli (v0.7.1, conferido) nao tem
comando para ADICIONAR mod - so a interface interativa ou editar o profiles.json dele a mao.
A API e a mesma que ele usa por baixo, publica e sem login, e diz para cada versao o pacote
de cada alvo (Windows, WindowsServer, LinuxServer), o sha256 e as dependencias.

Decisoes, cada uma com o motivo:
- **So o alvo `LinuxServer`.** O servidor daqui e o Linux nativo; versao sem esse alvo nao
  roda nele e e pulada.
- **O sha256 da API e conferido ANTES do antivirus.** Um pacote trocado no caminho nao chega
  nem a ser verificado.
- **Dependencias junto, na versao que a condicao do mod pede** (`^3.12.0`, `>=1.2.0`): a mais
  nova que satisfaz. Tudo e baixado e verificado de uma vez antes de qualquer arquivo entrar,
  como no Thunderstore: dependencia recusada nao deixa o mod pela metade.
- **Cada mod numa pasta propria, trocada por inteiro** (`FactoryGame/Mods/<referencia>`): a
  versao nova nao herda arquivo que a velha tinha e a nova nao tem.
- **O SML e um mod como os outros** (a referencia `SML`): instalar qualquer mod o traz como
  dependencia, e o botao do carregador so o instala sozinho.

NAO TESTADO num servidor de verdade ainda: o layout do pacote (a raiz do zip e a pasta do
plugin, com `SML.uplugin`) foi conferido baixando o SML 3.12.0 pela API, e mais nada.

Acoes (argv): [--scan SCRIPT] status | mod-install REF [VERSAO] | mod-remove REF, seguidas da
pasta do jogo (onde mora o FactoryServer.sh). Toda acao termina com UMA linha JSON.
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

API = "https://api.ficsit.app"
QUERY = API + "/v2/query"
TARGET = "LinuxServer"
# Referencia de mod do ficsit.app: vira nome de pasta e parte de consulta.
REF = re.compile(r"[A-Za-z0-9_]{1,64}")
VERSION = re.compile(r"\d{1,9}\.\d{1,9}\.\d{1,9}")
MODS = os.path.join("FactoryGame", "Mods")
MARK = ".gamepanel.json"
OWNER = "steam"
TIMEOUT = 120
MAX_PACKAGES = 25
VERSIONS_PER_MOD = 50
GRAPHQL = """query($ref: ModReference!, $limit: Int!) {
  getModByReference(modReference: $ref) {
    mod_reference
    name
    versions(filter: {limit: $limit, order_by: created_at, order: desc}) {
      id version game_version
      targets { targetName link hash }
      dependencies { mod_reference condition optional }
    }
  }
}"""


def fetch(url: str, body: bytes | None = None) -> bytes:
    # So o ficsit.app: a consulta e fixa (QUERY) e o link do pacote vem da resposta dela,
    # sempre relativo ao mesmo host.
    headers = {"User-Agent": "gamepanel"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers)  # noqa: S310
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


def check_ref(value: str) -> str:
    if not REF.fullmatch(value or ""):
        raise ValueError(f"referencia de mod invalida: {value!r}")
    return value


# ------------------------------------------------------------------ versoes

def _parse(version: str) -> tuple[int, int, int] | None:
    found = re.match(r"^\s*v?(\d+)\.(\d+)\.(\d+)", version or "")
    return (int(found[1]), int(found[2]), int(found[3])) if found else None


_COMPARE = {
    ">=": lambda have, want: have >= want,
    "<=": lambda have, want: have <= want,
    ">": lambda have, want: have > want,
    "<": lambda have, want: have < want,
    "=": lambda have, want: have == want,
    # ^ fixa o primeiro numero que nao e zero (semver): ^3.1.0 aceita 3.x, ^0.4.0 aceita 0.4.x.
    "^": lambda have, want: have >= want and (have[0] == want[0] if want[0] else have[:2] == want[:2]),
    "~": lambda have, want: have >= want and have[:2] == want[:2],
}


def _meets(have: tuple[int, int, int], part: str) -> bool:
    """Uma parte da condicao (`^3.12.0`, `>=1.2.0`, `1.0.0`)."""
    # O grupo e opcional: o match nunca falha, e sem operador vale a versao exata.
    found_op = re.match(r"^(\^|~|>=|<=|>|<|=)?", part)
    written = found_op.group(0) if found_op else ""
    # Corta o que estava ESCRITO: com o "=" implicito, cortar len("=") comia o primeiro digito.
    op = written or "="
    want = _parse(part[len(written):])
    return want is not None and _COMPARE[op](have, want)


def satisfies(version: str, condition: str) -> bool:
    """A versao atende a condicao de dependencia? (`^x.y.z`, `>=x.y.z`, `~x.y.z`, exata, vazia)."""
    have = _parse(version)
    if have is None:
        return False
    cond = (condition or "").strip()
    if cond in ("", "*"):
        return True
    return all(_meets(have, part) for part in cond.split())


def mod_versions(ref: str, fetcher=fetch) -> list[dict]:
    body = json.dumps({"query": GRAPHQL, "variables": {"ref": check_ref(ref), "limit": VERSIONS_PER_MOD}})
    data = json.loads(fetcher(QUERY, body.encode()))
    mod = (data.get("data") or {}).get("getModByReference")
    if not mod:
        raise ValueError(f"o ficsit.app nao conhece o mod {ref}")
    return mod.get("versions") or []


def _target(version: dict) -> dict | None:
    return next((t for t in version.get("targets") or [] if t.get("targetName") == TARGET), None)


def pick(versions: list[dict], condition: str = "", exact: str = "") -> dict:
    """A versao mais nova com pacote de servidor Linux que atende o pedido."""
    for v in versions:
        if not _target(v):
            continue
        if exact and v.get("version") != exact:
            continue
        if satisfies(v.get("version", ""), condition):
            return v
    wanted = exact or condition or "qualquer"
    raise ValueError(f"nenhuma versao ({wanted}) com pacote de servidor Linux")


def resolve(ref: str, version: str = "", fetcher=fetch) -> list[tuple[str, dict]]:
    """O mod e as dependencias obrigatorias: [(referencia, versao escolhida)]."""
    if version and not VERSION.fullmatch(version):
        raise ValueError(f"versao invalida: {version!r}")
    queue: list[tuple[str, str, str]] = [(check_ref(ref), "", version)]
    chosen: dict[str, dict] = {}
    while queue:
        name, condition, exact = queue.pop(0)
        if name in chosen:
            continue
        if len(chosen) >= MAX_PACKAGES:
            raise ValueError(f"mais de {MAX_PACKAGES} pacotes na arvore de dependencias")
        picked = pick(mod_versions(name, fetcher), condition, exact)
        chosen[name] = picked
        for dep in picked.get("dependencies") or []:
            if not dep.get("optional"):
                queue.append((check_ref(dep.get("mod_reference", "")), dep.get("condition", ""), ""))
    return list(chosen.items())


# ------------------------------------------------------------------ instalar

def _safe_rel(path: str) -> str:
    rel = posixpath.normpath(path.replace("\\", "/")).lstrip("/")
    if rel in (".", "") or rel.startswith("..") or "/../" in f"/{rel}/":
        return ""
    return rel


def _download(plan: list[tuple[str, dict]], fetcher) -> list[tuple[str, bytes]]:
    """O pacote de cada mod do plano, conferido contra o sha256 que a API publicou."""
    blobs: list[tuple[str, bytes]] = []
    for name, picked in plan:
        target = _target(picked) or {}
        link = target.get("link", "")
        if not link.startswith("/v1/version/"):
            raise ValueError(f"link de pacote inesperado para {name}")
        print(f"baixando {name} {picked.get('version')}")
        data = fetcher(API + link)
        if hashlib.sha256(data).hexdigest() != (target.get("hash") or "").lower():
            raise ValueError(f"o pacote de {name} nao confere com o sha256 do ficsit.app")
        blobs.append((f"{name}-{picked.get('version')}", data))
    return blobs


def _extract(dest: str, data: bytes) -> int:
    """Troca a pasta do mod por inteiro pelo conteudo do pacote. Devolve quantos arquivos."""
    shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest, exist_ok=True)
    count = 0
    z = zipfile.ZipFile(io.BytesIO(data))
    for entry in z.namelist():
        rel = _safe_rel(entry)
        if not rel or entry.endswith("/"):
            continue
        out_path = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with z.open(entry) as src, open(out_path, "wb") as out:
            shutil.copyfileobj(src, out)
        count += 1
    return count


def install(game_dir: str, ref: str, version: str = "", fetcher=fetch, scan=_no_scan) -> dict:
    if not os.path.isdir(game_dir):
        raise ValueError(f"a pasta do jogo nao existe: {game_dir}")
    plan = resolve(ref, version, fetcher)
    blobs = _download(plan, fetcher)
    # Tudo verificado de uma vez: dependencia recusada nao deixa o mod principal pela metade.
    scan(blobs)
    installed = []
    for (name, picked), (_, data) in zip(plan, blobs, strict=True):
        dest = os.path.join(game_dir, MODS, name)
        count = _extract(dest, data)
        with open(os.path.join(dest, MARK), "w", encoding="utf-8") as f:
            json.dump({"version": picked.get("version", ""), "pinned": bool(version) and name == ref,
                       "game_version": picked.get("game_version", "")}, f)
        installed.append({"mod": name, "version": picked.get("version", ""), "files": count})
        print(f"{name} {picked.get('version')} ({count} arquivos)")
    return {"installed": installed}


def remove(game_dir: str, ref: str) -> dict:
    dest = os.path.join(game_dir, MODS, check_ref(ref))
    existed = os.path.isdir(dest)
    shutil.rmtree(dest, ignore_errors=True)
    return {"removed": existed}


def _read_json(path: str) -> dict:
    with contextlib.suppress(OSError, ValueError):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    return {}


def status(game_dir: str) -> dict:
    mods_dir = os.path.join(game_dir, MODS)
    mods = []
    for entry in sorted(os.listdir(mods_dir)) if os.path.isdir(mods_dir) else []:
        path = os.path.join(mods_dir, entry)
        if not os.path.isdir(path):
            continue
        mark = _read_json(os.path.join(path, MARK))
        # Mod posto a mao (sem a marca): a versao sai do .uplugin, que todo plugin tem.
        version = mark.get("version") or _read_json(os.path.join(path, f"{entry}.uplugin")).get("VersionName", "")
        mods.append({"name": entry, "version": version, "pinned": bool(mark.get("pinned"))})
    sml = next((m for m in mods if m["name"] == "SML"), None)
    return {"loader_installed": sml is not None, "loader": "SML",
            "loader_version": sml["version"] if sml else "", "loader_pinned": bool(sml and sml["pinned"]),
            "enabled": sml is not None, "mods": [m for m in mods if m["name"] != "SML"]}


def _chown(game_dir: str) -> None:
    try:
        import pwd
        pw = pwd.getpwnam(OWNER)
    except (ImportError, KeyError):
        return
    for root, dirs, files in os.walk(os.path.join(game_dir, MODS)):
        for n in (root, *[os.path.join(root, d) for d in dirs], *[os.path.join(root, f) for f in files]):
            with contextlib.suppress(OSError):
                os.chown(n, pw.pw_uid, pw.pw_gid)


def main(argv: list[str]) -> int:
    script = ""
    if argv[:1] == ["--scan"]:
        script, argv = argv[1], argv[2:]
    action, game_dir, *rest = argv
    try:
        if action == "mod-install" and not script:
            raise ValueError("instalar sem a verificacao do antivirus nao e caminho do painel")
        if action == "status":
            result = status(game_dir)
        elif action == "mod-install":
            result = install(game_dir, rest[0], rest[1] if len(rest) > 1 else "", scan=scanner(script))
        elif action == "mod-remove":
            result = remove(game_dir, rest[0])
        else:
            raise ValueError(f"acao desconhecida: {action}")
        if action != "status":
            _chown(game_dir)
    except (ValueError, KeyError, OSError, IndexError, zipfile.BadZipFile) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
