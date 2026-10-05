"""Mods da Workshop pela CONFIG do jogo - roda DENTRO do CT do jogo.

Mesmo desenho dos outros instaladores remotos: o painel le este texto e o executa no
container com `python3 -c`, por SSH, como root. So stdlib e sem import do `gamepanel`.

Aqui ninguem baixa nada: quem baixa e o PROPRIO servidor do jogo, na subida, a partir da lista
de IDs da config dele. O script so le e escreve essa lista, no formato de cada jogo - e cada um
foi provado num servidor de verdade (Docker, 2026-10-05), com o mod baixado e carregado no log:

- **dst** (Don't Starve Together): `ServerModSetup("<id>")` no `mods/dedicated_server_mods_setup.lua`
  da pasta do jogo (e o que manda BAIXAR) e `["workshop-<id>"] = { enabled = true }` no
  `modoverrides.lua` de cada shard (e o que manda CARREGAR). Sem o primeiro o mod nao chega; sem
  o segundo ele chega e fica desligado. Um update do jogo pela Steam devolve o setup ao original:
  o status acusa (`setup_missing`) e salvar de novo reescreve.
- **zomboid** (Project Zomboid): `WorkshopItems=` (IDs da Workshop, o que baixa) e `Mods=` (os
  IDs de mod do `mod.info`, o que carrega) no `<servername>.ini`. Sao listas diferentes: um item
  da Workshop pode trazer varios mods, e ligar todos e justo o que quebra servidor.
- **unturned**: `File_IDs` do `Servers/<nome>/WorkshopDownloadConfig.json`. O servidor baixa
  tambem as dependencias (um mapa e os assets dele).
- **reforger** (Arma Reforger): `game.mods` do JSON do `-config`, com o GUID do workshop da
  Bohemia (nao e Steam) e um nome.

O que vale para os quatro, cada um com o motivo:
- **O que a pessoa ja configurou fica.** As opcoes de cada mod no `modoverrides.lua` (o bloco
  inteiro do mod, copiado como texto), as outras chaves do JSON e as outras linhas do .ini: o
  painel so troca a LISTA. Mod que saiu da lista perde o bloco dele, e e isso que "remover" quer.
- **Escrita atomica com copia de antes** (`<arquivo>.gamepanel.bak`): um arquivo escrito pela
  metade e um servidor que nao sobe, e a copia e o caminho de volta a mao.
- **O dono continua o do arquivo** (ou o `User=` do servico, para arquivo novo): o servidor roda
  como steam, e um arquivo de root que ele nao consegue reescrever trava a proxima subida.
- **Onde fica a config sai do ExecStart do servico** (`-servername`, `-cachedir`, `-config`,
  `+InternetServer/`), e nao de um palpite: e o mesmo comando que o jogo recebe.
- **Nada passa pelo antivirus antes de entrar**, porque quem baixa e o jogo, na subida. O
  "Verificar mods instalados" do painel passa o ClamAV na pasta onde cada jogo os guarda.

Acoes (argv): --unit SERVICO FORMATO status|set PASTA_DO_JOGO [ITENS...] [--mods LISTA]
ITEM e o ID (Steam) ou `GUID=Nome` (reforger). Termina com UMA linha JSON.
"""
from __future__ import annotations

import contextlib
import glob
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

FORMATS = ("dst", "zomboid", "unturned", "reforger")
OWNER = "steam"
BACKUP_SUFFIX = ".gamepanel.bak"

STEAM_ID = re.compile(r"^\d{6,20}$", re.ASCII)
GUID = re.compile(r"^[0-9A-F]{16}$", re.ASCII)
# O nome do mod do Reforger vai para o JSON e para o log do servidor: texto curto e imprimivel.
REFORGER_NAME = re.compile(r"^[^\x00-\x1f\x7f]{1,80}$")
# Mods= do Zomboid: IDs de mod separados por ';'. A barra invertida e o prefixo que o Build 42
# aceita em alguns guias (`\BB_CommonSense`); sem ela tambem carrega (medido).
ZOMBOID_MODS = re.compile(r"^[A-Za-z0-9_.\-\\ ;]{0,4000}$", re.ASCII)

DST_SETUP = "mods/dedicated_server_mods_setup.lua"
DST_SETUP_LINE = re.compile(r'^\s*ServerModSetup\(\s*"(?:workshop-)?(\d+)"\s*\)', re.MULTILINE)
DST_KEY = re.compile(r'\[\s*"([^"]+)"\s*\]\s*=\s*\{')


# --- servico e dono ---------------------------------------------------------------------------

def unit_text(unit: str) -> str:
    """O texto da unit (com os drop-ins), ou vazio se o systemctl nao responde."""
    if not unit:
        return ""
    # O nome da unit vem do painel (o servico do proprio servidor), e vai como argumento, sem shell.
    try:
        proc = subprocess.run(["systemctl", "cat", unit], capture_output=True, text=True,  # noqa: S603, S607
                              timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return proc.stdout or ""


def exec_args(text: str) -> list[str]:
    """As palavras do ULTIMO ExecStart (um drop-in que o troca vem depois do original)."""
    lines = [ln.split("=", 1)[1] for ln in text.splitlines() if ln.strip().startswith("ExecStart=")]
    lines = [ln for ln in lines if ln.strip()]
    if not lines:
        return []
    try:
        return shlex.split(lines[-1].lstrip("@-:+!"))
    except ValueError:
        return lines[-1].split()


def unit_value(text: str, key: str) -> str:
    found = [ln.split("=", 1)[1].strip() for ln in text.splitlines() if ln.strip().startswith(key + "=")]
    return found[-1] if found else ""


def arg_after(args: list[str], flag: str) -> str:
    """O valor de `-flag valor` ou `-flag=valor`, ignorando a caixa (o Zomboid aceita as duas)."""
    low = flag.lower()
    for i, a in enumerate(args):
        if a.lower() == low and i + 1 < len(args):
            return args[i + 1]
        if a.lower().startswith(low + "="):
            return a.split("=", 1)[1]
    return ""


def home_of(user: str) -> str:
    try:
        import pwd
        return pwd.getpwnam(user).pw_dir
    except (ImportError, KeyError):
        return f"/home/{user}"


def _ids_of(user: str) -> tuple[int, int] | None:
    try:
        import pwd
        pw = pwd.getpwnam(user)
    except (ImportError, KeyError):
        return None
    return pw.pw_uid, pw.pw_gid


def _chown(path: str, owner: tuple[int, int] | None) -> None:
    # Sem chown (o Windows dos testes) ou sem permissao, o arquivo fica com o dono que tiver.
    chown = getattr(os, "chown", None)
    if owner and chown:
        with contextlib.suppress(OSError):
            chown(path, *owner)


def write_atomic(path: str, text: str, user: str) -> None:
    """Grava ao lado e move por cima, guardando a copia de antes e o dono de antes."""
    owner = None
    if os.path.exists(path):
        st = os.stat(path)
        owner = (st.st_uid, st.st_gid)
        shutil.copy2(path, path + BACKUP_SUFFIX)
        _chown(path + BACKUP_SUFFIX, owner)
    else:
        owner = _ids_of(user)
        os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".gamepanel-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        _chown(tmp, owner)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def read_text(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


# --- Don't Starve Together --------------------------------------------------------------------

LUA_LONG = re.compile(r"(--)?\[(=*)\[")


def _lua_skip(text: str, i: int) -> int:
    """Se em `i` comeca comentario ou string, a posicao logo depois dele; senao, o proprio `i`.

    Chave dentro de string (`scale = "1}"`) ou de comentario nao conta: e assim que o bloco de
    opcoes de cada mod sai inteiro, e nao cortado no primeiro `}` que aparece.
    """
    n = len(text)
    long = LUA_LONG.match(text, i)
    if long:
        close = "]" + long.group(2) + "]"
        j = text.find(close, long.end())
        return n if j < 0 else j + len(close)
    if text.startswith("--", i):
        j = text.find("\n", i)
        return n if j < 0 else j + 1
    if text[i] in "\"'":
        j = i + 1
        while j < n and text[j] != text[i]:
            j += 2 if text[j] == "\\" else 1
        return j + 1
    return i


def _lua_block_end(text: str, start: int) -> int:
    """Posicao logo depois do `}` que fecha o `{` em `start`."""
    depth, i = 0, start
    while i < len(text):
        j = _lua_skip(text, i)
        if j != i:
            i = j
            continue
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ValueError("modoverrides.lua com chaves sem fechar")


def lua_entries(text: str) -> dict[str, str]:
    """`["chave"] = { ... }` do nivel de cima da tabela, como TEXTO (as opcoes vao inteiras)."""
    i, start = 0, -1
    while i < len(text):
        j = _lua_skip(text, i)
        if j != i:
            i = j
            continue
        if text[i] == "{":
            start = i
            break
        i += 1
    if start < 0:
        return {}
    end = _lua_block_end(text, start)
    entries: dict[str, str] = {}
    i = start + 1
    while i < end - 1:
        j = _lua_skip(text, i)
        if j != i:
            i = j
            continue
        m = DST_KEY.match(text, i)
        if m:
            close = _lua_block_end(text, m.end() - 1)
            entries[m.group(1)] = text[m.end() - 1:close]
            i = close
            continue
        i += 1
    return entries


def render_overrides(entries: dict[str, str]) -> str:
    lines = ["return {"]
    lines += [f'  ["{key}"] = {block},' for key, block in entries.items()]
    lines.append("}")
    return "\n".join(lines) + "\n"


def dst_shards(ctx: dict) -> list[str]:
    """As pastas de shard (as que tem server.ini) do cluster deste servidor.

    O cluster sai do comando do jogo (-persistent_storage_root, -conf_dir, -cluster, com os
    padroes do DST): o cluster.ini so existe depois de alguem configurar o cluster, e o primeiro
    start so cria <shard>/server.ini. A varredura e o recurso de quem nao passa nada disso.
    """
    args = ctx["args"]
    root = arg_after(args, "-persistent_storage_root") or os.path.join(ctx["home"], ".klei")
    cluster = os.path.join(root, arg_after(args, "-conf_dir") or "DoNotStarveTogether",
                           arg_after(args, "-cluster") or "Cluster_1")
    found = sorted(os.path.dirname(s) for s in glob.glob(os.path.join(cluster, "*", "server.ini")))
    if found:
        return found
    # Profundidade fixa, e nao `**`: na pasta do jogo seriam gigas de arquivo a cada abertura da
    # tela. O egg do Pterodactyl usa /opt/game/DoNotStarveTogether/config/server.
    for base in (os.path.join(ctx["home"], ".klei"), ctx["game_dir"]):
        for depth in range(1, 5):
            for ini in sorted(glob.glob(os.path.join(base, *["*"] * depth, "cluster.ini"))):
                shards = glob.glob(os.path.join(os.path.dirname(ini), "*", "server.ini"))
                found += sorted(os.path.dirname(s) for s in shards)
    return list(dict.fromkeys(found))


def dst_status(ctx: dict) -> dict:
    shards = dst_shards(ctx)
    setup = set(DST_SETUP_LINE.findall(read_text(os.path.join(ctx["game_dir"], DST_SETUP))))
    ids: list[str] = []
    for shard in shards:
        for key in lua_entries(read_text(os.path.join(shard, "modoverrides.lua"))):
            if key.startswith("workshop-") and key[9:] not in ids:
                ids.append(key[9:])
    # O DST atual baixa para ugc_mods/<cluster>/<shard>/content/322330/<id>; o antigo, mods/workshop-<id>.
    installed = [i for i in ids
                 if glob.glob(os.path.join(ctx["game_dir"], "ugc_mods", "*", "*", "content", "*", i))
                 or os.path.isdir(os.path.join(ctx["game_dir"], "mods", f"workshop-{i}"))]
    return {"config": ", ".join(shards), "ids": ids, "installed": installed,
            "setup_missing": [i for i in ids if i not in setup],
            "problem": "" if shards else "no_cluster"}


def dst_set(ctx: dict, items: list[str]) -> dict:
    shards = dst_shards(ctx)
    if not shards:
        raise ValueError("nenhum cluster do DST com server.ini: suba o servidor uma vez antes")
    setup_path = os.path.join(ctx["game_dir"], DST_SETUP)
    old = read_text(setup_path)
    # Tira as linhas ServerModSetup de antes e poe as da lista; comentario e o resto ficam.
    kept = [ln for ln in old.splitlines() if not DST_SETUP_LINE.match(ln)]
    new_setup = "\n".join([*kept, *[f'ServerModSetup("{i}")' for i in items]]) + "\n"
    write_atomic(setup_path, new_setup, ctx["user"])
    for shard in shards:
        path = os.path.join(shard, "modoverrides.lua")
        current = lua_entries(read_text(path))
        entries = {k: v for k, v in current.items() if not k.startswith("workshop-")}
        for i in items:
            entries[f"workshop-{i}"] = current.get(f"workshop-{i}", "{ enabled = true }")
        write_atomic(path, render_overrides(entries), ctx["user"])
    return {"ids": items, "shards": shards}


# --- Project Zomboid --------------------------------------------------------------------------

def zomboid_ini(ctx: dict) -> str:
    name = arg_after(ctx["args"], "-servername") or "servertest"
    base = arg_after(ctx["args"], "-cachedir") or os.path.join(ctx["home"], "Zomboid")
    return os.path.join(base, "Server", f"{name}.ini")


def ini_value(text: str, key: str) -> str:
    m = re.search(rf"^{key}=(.*)$", text, re.MULTILINE)
    return m.group(1).strip() if m else ""


def ini_set(text: str, key: str, value: str) -> str:
    line = f"{key}={value}"
    pattern = re.compile(rf"^{key}=.*$", re.MULTILINE)
    if pattern.search(text):
        return pattern.sub(lambda _m: line, text, count=1)
    return text.rstrip("\n") + "\n" + line + "\n"


def zomboid_mod_ids(game_dir: str, workshop_id: str) -> list[str]:
    """Os `id=` dos mod.info que o item da Workshop trouxe: o que pode ir no `Mods=`."""
    root = os.path.join(game_dir, "steamapps", "workshop", "content", "108600", workshop_id)
    found: list[str] = []
    for info in sorted(glob.glob(os.path.join(root, "mods", "*", "**", "mod.info"), recursive=True)):
        mod_id = ini_value(read_text(info), "id")
        if mod_id and mod_id not in found:
            found.append(mod_id)
    return found


def zomboid_status(ctx: dict) -> dict:
    path = zomboid_ini(ctx)
    text = read_text(path)
    ids = [i for i in re.split(r"[;,\s]+", ini_value(text, "WorkshopItems")) if i]
    available = {i: zomboid_mod_ids(ctx["game_dir"], i) for i in ids}
    return {"config": path, "ids": ids, "mods": ini_value(text, "Mods"),
            "installed": [i for i, mods in available.items() if mods], "available": available,
            "problem": "" if text else "no_config"}


def zomboid_set(ctx: dict, items: list[str], mods: str) -> dict:
    path = zomboid_ini(ctx)
    text = read_text(path)
    if not text:
        raise ValueError(f"{path} nao existe: suba o servidor uma vez antes")
    text = ini_set(text, "WorkshopItems", ";".join(items))
    text = ini_set(text, "Mods", mods)
    write_atomic(path, text, ctx["user"])
    return {"ids": items, "mods": mods, "config": path}


# --- Unturned ---------------------------------------------------------------------------------

def unturned_dir(ctx: dict) -> str:
    """A pasta do servidor: a do `+InternetServer/<nome>`, ou a unica que existe."""
    for a in ctx["args"]:
        m = re.match(r"^\+(?:Internet|Lan)Server/(.+)$", a, re.IGNORECASE)
        if m:
            return os.path.join(ctx["game_dir"], "Servers", m.group(1))
    configs = glob.glob(os.path.join(ctx["game_dir"], "Servers", "*", "Config.txt"))
    existing = sorted(os.path.dirname(c) for c in configs)
    return existing[0] if len(existing) == 1 else ""


def unturned_status(ctx: dict) -> dict:
    folder = unturned_dir(ctx)
    if not folder:
        return {"config": "", "ids": [], "installed": [], "problem": "no_server_name"}
    path = os.path.join(folder, "WorkshopDownloadConfig.json")
    try:
        ids = [str(i) for i in json.loads(read_text(path) or "{}").get("File_IDs", [])]
    except ValueError:
        return {"config": path, "ids": [], "installed": [], "problem": "bad_json"}
    content = os.path.join(folder, "Workshop", "Steam", "content", "304930")
    return {"config": path, "ids": ids, "installed": [i for i in ids if os.path.isdir(os.path.join(content, i))],
            "problem": ""}


def unturned_set(ctx: dict, items: list[str]) -> dict:
    folder = unturned_dir(ctx)
    if not folder:
        raise ValueError("sem o nome do servidor: ponha +InternetServer/<nome> no comando do jogo")
    path = os.path.join(folder, "WorkshopDownloadConfig.json")
    data = json.loads(read_text(path) or "{}")
    if not isinstance(data, dict):
        raise ValueError(f"{path} nao e um objeto JSON")
    data["File_IDs"] = [int(i) for i in items]
    write_atomic(path, json.dumps(data, indent=2) + "\n", ctx["user"])
    return {"ids": items, "config": path}


# --- Arma Reforger ----------------------------------------------------------------------------

def reforger_config(ctx: dict) -> str:
    path = arg_after(ctx["args"], "-config")
    if path and not os.path.isabs(path):
        path = os.path.join(ctx["workdir"] or ctx["game_dir"], path)
    return path


def reforger_status(ctx: dict) -> dict:
    path = reforger_config(ctx)
    if not path:
        return {"config": "", "ids": [], "installed": [], "problem": "no_config_arg"}
    try:
        data = json.loads(read_text(path) or "null")
    except ValueError:
        return {"config": path, "ids": [], "installed": [], "problem": "bad_json"}
    if not isinstance(data, dict):
        return {"config": path, "ids": [], "installed": [], "problem": "no_config"}
    mods = (data.get("game") or {}).get("mods") or []
    ids = [str(m.get("modId", "")).upper() for m in mods if isinstance(m, dict)]
    names = {str(m.get("modId", "")).upper(): str(m.get("name", "")) for m in mods if isinstance(m, dict)}
    profile = arg_after(ctx["args"], "-profile")
    addons = os.path.join(profile, "addons") if profile else ""
    installed = [i for i in ids if addons and glob.glob(os.path.join(addons, f"*_{i}"))]
    return {"config": path, "ids": ids, "names": names, "installed": installed, "problem": ""}


def reforger_set(ctx: dict, items: list[tuple[str, str]]) -> dict:
    path = reforger_config(ctx)
    if not path:
        raise ValueError("o servidor nao recebe -config no comando: sem ele nao ha onde por os mods")
    data = json.loads(read_text(path) or "null")
    if not isinstance(data, dict) or not isinstance(data.get("game"), dict):
        raise ValueError(f"{path} nao tem o objeto game: crie a config do servidor antes")
    # Versao fixada e o que mais a pessoa tenha posto em cada mod fica; so a lista muda.
    before = {str(m.get("modId", "")).upper(): m for m in data["game"].get("mods") or [] if isinstance(m, dict)}
    mods = []
    for guid, name in items:
        entry = dict(before.get(guid, {}))
        entry["modId"] = guid
        entry["name"] = name or entry.get("name") or guid
        mods.append(entry)
    data["game"]["mods"] = mods
    write_atomic(path, json.dumps(data, indent=2) + "\n", ctx["user"])
    return {"ids": [g for g, _ in items], "config": path}


# --- entrada ----------------------------------------------------------------------------------

def parse_items(fmt: str, raw: list[str]) -> list:
    """Os itens do argv, conferidos de novo aqui: o painel confere, e o CT nao confia."""
    if fmt == "reforger":
        out: list[tuple[str, str]] = []
        for item in raw:
            guid, _, name = item.partition("=")
            guid = guid.upper()
            if not GUID.match(guid) or (name and not REFORGER_NAME.match(name)):
                raise ValueError(f"mod do Reforger invalido: {item!r}")
            out.append((guid, name))
        return list(dict((g, (g, n)) for g, n in out).values())
    for item in raw:
        if not STEAM_ID.match(item):
            raise ValueError(f"ID da Workshop invalido: {item!r}")
    return list(dict.fromkeys(raw))


def context(unit: str, game_dir: str) -> dict:
    text = unit_text(unit)
    user = unit_value(text, "User") or OWNER
    return {"game_dir": game_dir, "args": exec_args(text), "user": user, "home": home_of(user),
            "workdir": unit_value(text, "WorkingDirectory")}


STATUS = {"dst": dst_status, "zomboid": zomboid_status, "unturned": unturned_status, "reforger": reforger_status}


def run(fmt: str, action: str, ctx: dict, raw: list[str], mods: str) -> dict:
    if fmt not in FORMATS:
        raise ValueError(f"formato desconhecido: {fmt}")
    if action == "status":
        return {"format": fmt, **STATUS[fmt](ctx)}
    if action != "set":
        raise ValueError(f"acao desconhecida: {action}")
    items = parse_items(fmt, raw)
    if fmt == "dst":
        return dst_set(ctx, items)
    if fmt == "zomboid":
        if not ZOMBOID_MODS.match(mods):
            raise ValueError("lista Mods= invalida")
        return zomboid_set(ctx, items, mods)
    if fmt == "unturned":
        return unturned_set(ctx, items)
    return reforger_set(ctx, items)


def main(argv: list[str]) -> int:
    unit = mods = ""
    if argv[:1] == ["--unit"]:
        unit, argv = argv[1], argv[2:]
    if "--mods" in argv:
        i = argv.index("--mods")
        mods, argv = argv[i + 1] if i + 1 < len(argv) else "", argv[:i] + argv[i + 2:]
    try:
        fmt, action, game_dir, *items = argv
        result = run(fmt, action, context(unit, game_dir), items, mods)
    except (ValueError, KeyError, OSError, TypeError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
