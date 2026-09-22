"""Editor de arquivos e upload/download do container de jogo - tudo por SSH.

Nao ha SFTP nem biblioteca de transferencia: cada operacao e um script POSIX pequeno
(`bash -lc`) executado no destino, com o conteudo indo e vindo pela entrada/saida
padrao (texto em base64 para caber num comando; bytes crus, em streaming, para upload
e download - ver `ssh_stream_in`/`stream_remote_file`).
"""
from __future__ import annotations

import base64
import contextlib
import shlex
import subprocess
from collections.abc import Callable, Iterable, Iterator
from typing import Any

from gamepanel.runtime.ssh import RemoteError, ServerLike, quote_command

SshRun = Callable[..., subprocess.CompletedProcess]
SshArgv = Callable[..., list[str]]

# ------------------------------------------------------------- caminho

FILE_PATH_MAX = 400


def _resolve_segments(path: str) -> str:
    """Resolve '..' e '.' sem tocar no destino (nao segue link nem consulta o disco)."""
    parts: list[str] = []
    for seg in path.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if parts:
                parts.pop()
            continue
        parts.append(seg)
    return "/" + "/".join(parts)


def _check_roots(path: str, roots: tuple[str, ...]) -> None:
    if not roots or "/" in roots:  # "/" configurado = sem restricao
        return
    # rstrip + "/" para /opt/game nao liberar /opt/gamex sem querer.
    if any(path == r or path.startswith(r.rstrip("/") + "/") for r in roots):
        return
    raise ValueError(f"fora das pastas permitidas ({', '.join(roots)})")


def clean_path(raw: str, roots: tuple[str, ...]) -> str:
    """Normaliza um caminho absoluto vindo da tela (resolve '..' de forma lexica)."""
    path = (raw or "").strip()
    if not path.startswith("/"):
        raise ValueError("use um caminho absoluto (comecando com /)")
    if "\x00" in path or "\n" in path or "\r" in path:
        raise ValueError("caractere invalido no caminho")
    if len(path) > FILE_PATH_MAX:
        raise ValueError("caminho longo demais")
    cleaned = _resolve_segments(path)
    _check_roots(cleaned, roots)
    return cleaned


def parent_of(path: str) -> str:
    return path.rsplit("/", 1)[0] or "/"


# ------------------------------------------------------- scripts remotos

LIST_SCRIPT = r"""
set -e
d=$1
[ -d "$d" ] || { echo "pasta nao encontrada: $d" >&2; exit 3; }
find "$d" -maxdepth 1 -mindepth 1 -printf '%y\t%Y\t%s\t%TY-%Tm-%Td %TH:%TM\t%M\t%f\n' \
  2>/dev/null | head -n "$2"
"""

# $2 = limite de edicao, $3 = quanto trazer do fim quando o arquivo passa do limite.
# Arquivo grande nao e mais um erro: vem so o fim dele, marcado como 'tail'.
READ_SCRIPT = r"""
set -e
f=$1
[ -e "$f" ] || { echo "arquivo nao encontrado" >&2; exit 3; }
[ -f "$f" ] || { echo "nao e um arquivo comum" >&2; exit 4; }
sz=$(stat -Lc %s -- "$f")
if [ "$sz" -le "$2" ]; then kind=full; else kind=tail; fi
stat -Lc "META|%s|%y|%a|%U|%G|$kind" -- "$f"
if [ "$kind" = full ]; then
  base64 -w0 -- "$f"
else
  tail -c "$3" -- "$f" | base64 -w0
fi
"""

# Usado antes do download: confere que da para baixar e quanto tem para vir.
STAT_SCRIPT = r"""
set -e
f=$1
[ -e "$f" ] || { echo "arquivo nao encontrado" >&2; exit 3; }
[ -f "$f" ] || { echo "nao e um arquivo comum (pastas nao sao baixaveis)" >&2; exit 4; }
[ -r "$f" ] || { echo "sem permissao de leitura" >&2; exit 5; }
stat -Lc 'META|%s|%y|%a|%U|%G' -- "$f"
"""

# Grava por cima do arquivo existente (cat >) em vez de trocar o inode: assim dono,
# grupo e permissao continuam os do jogo — o servidor roda como 'steam', nao root.
WRITE_SCRIPT = r"""
set -e
f=$1
d=$(dirname "$f")
[ -d "$d" ] || { echo "pasta nao existe: $d" >&2; exit 3; }
t=$(mktemp "$d/.gamepanel-XXXXXX")
trap 'rm -f "$t"' EXIT
base64 -d > "$t"
if [ -e "$f" ]; then
  [ -f "$f" ] || { echo "nao e um arquivo comum" >&2; exit 4; }
  cp -a -- "$f" "$f.$(date +%Y%m%d-%H%M%S).bak"
  cat "$t" > "$f"
else
  cat "$t" > "$f"
  chmod 0644 "$f"
  # Arquivo novo herda o dono da pasta: o jogo roda como 'steam' e precisa continuar
  # conseguindo reescrever o proprio config.
  chown --reference="$d" "$f" 2>/dev/null || true
fi
echo "gravado: $(stat -Lc %s -- "$f") bytes"
"""

# Apagar nao tem .bak: um save de varios GB nao cabe numa copia de seguranca, e quem
# manda apagar quer o espaco de volta. Por isso o escopo e estreito: arquivo comum,
# link, ou pasta VAZIA (rmdir) — nada de remocao recursiva a partir da tela.
DELETE_SCRIPT = r"""
set -e
f=$1
[ -e "$f" ] || [ -L "$f" ] || { echo "arquivo nao encontrado" >&2; exit 3; }
if [ -d "$f" ] && [ ! -L "$f" ]; then
  rmdir -- "$f" 2>/dev/null || { echo "a pasta nao esta vazia (esvazie antes de apagar)" >&2; exit 4; }
  echo "pasta apagada: $f"
else
  sz=$(stat -Lc %s -- "$f" 2>/dev/null || echo 0)
  # -f para o rm nunca parar perguntando por arquivo sem permissao de escrita; o erro
  # que importa (pasta somente leitura) continua vindo.
  rm -f -- "$f"
  echo "apagado: $f ($sz bytes)"
fi
"""

# $1 = destino final. O conteudo vem CRU pela entrada padrao (sem base64: o arquivo pode
# ter gigabytes, e codificar inflaria 33% a toa).
UPLOAD_SCRIPT = r"""
set -e
f=$1
d=$(dirname -- "$f")
[ -d "$d" ] || { echo "pasta nao existe: $d" >&2; exit 3; }
[ -d "$f" ] && { echo "ja existe uma PASTA com esse nome" >&2; exit 4; }
t=$(mktemp "$d/.gamepanel-XXXXXX")
trap 'rm -f "$t"' EXIT
cat > "$t"
if [ -e "$f" ]; then
  [ -f "$f" ] || { echo "o destino nao e um arquivo comum" >&2; exit 4; }
  cp -a -- "$f" "$f.$(date +%Y%m%d-%H%M%S).bak"
  # cat > por cima em vez de mv: preserva dono e permissao do arquivo que ja estava la.
  cat "$t" > "$f"
else
  cat "$t" > "$f"
  chmod 0644 -- "$f"
  # Arquivo novo herda o dono da pasta: o jogo roda como 'steam' e precisa poder ler.
  chown --reference="$d" -- "$f" 2>/dev/null || true
fi
echo "enviado: $f ($(stat -Lc %s -- "$f") bytes)"
"""


# --------------------------------------------------------------- listar

_LIST_LINE_FIELDS = 6


def list_dir(ssh_run: SshRun, server: ServerLike, path: str, limit: int) -> tuple[list[dict], bool]:
    proc = ssh_run(server, quote_command("bash", "-lc", LIST_SCRIPT, "gp", path, str(limit)), timeout=40)
    if proc.returncode != 0:
        raise RemoteError((proc.stderr or proc.stdout).strip() or "falha ao listar a pasta")
    entries: list[dict] = []
    for line in proc.stdout.splitlines():
        parts = line.split("\t", 5)
        if len(parts) != _LIST_LINE_FIELDS:
            continue
        kind, target_kind, size, mtime, mode, name = parts
        real = target_kind if kind == "l" else kind
        entries.append({
            "name": name,
            "dir": real == "d",
            "link": kind == "l",
            "size": int(size) if size.isdigit() else 0,
            "mtime": mtime,
            "mode": mode,
            "path": (path.rstrip("/") + "/" + name) if path != "/" else "/" + name,
        })
    entries.sort(key=lambda e: (not e["dir"], e["name"].lower()))
    return entries, len(entries) >= limit


_FIND_LINE_FIELDS = 3


def find_config_files(ssh_run: SshRun, server: ServerLike, root: str, globs: Iterable[str]) -> list[dict]:
    """Varre a pasta do jogo atras dos arquivos de configuracao mais provaveis."""
    names = " -o ".join(f"-name {shlex.quote(g)}" for g in globs)
    script = (
        "set -e\n"
        'd=$1\n'
        '[ -d "$d" ] || { echo "pasta nao encontrada: $d" >&2; exit 3; }\n'
        f'find "$d" -maxdepth 5 -type f \\( {names} \\) '
        r"-printf '%s\t%TY-%Tm-%Td %TH:%TM\t%p\n' 2>/dev/null | LC_ALL=C sort -k3 | head -n 300"
        "\n"
    )
    proc = ssh_run(server, quote_command("bash", "-lc", script, "gp", root), timeout=90)
    if proc.returncode != 0:
        raise RemoteError((proc.stderr or proc.stdout).strip() or "falha na busca")
    achados: list[dict] = []
    for line in proc.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != _FIND_LINE_FIELDS:
            continue
        achados.append({
            "size": int(parts[0]) if parts[0].isdigit() else 0,
            "mtime": parts[1],
            "path": parts[2],
        })
    return achados


# ----------------------------------------------------------- ler/gravar

def _parse_meta(head: str, campos: int) -> list[str]:
    meta = head.split("|")
    if meta[0] != "META" or len(meta) < campos:
        raise RemoteError("resposta inesperada do container ao ler o arquivo")
    return meta


def stat_file(ssh_run: SshRun, server: ServerLike, path: str) -> dict:
    """Metadados sem trazer o conteudo — usado antes de comecar um download."""
    proc = ssh_run(server, quote_command("bash", "-lc", STAT_SCRIPT, "gp", path), timeout=40)
    if proc.returncode != 0:
        raise RemoteError((proc.stderr or proc.stdout).strip() or "falha ao ler o arquivo")
    meta = _parse_meta(proc.stdout.strip(), 6)
    return {
        "path": path,
        "name": path.rsplit("/", 1)[-1] or "arquivo",
        "size": int(meta[1]) if meta[1].isdigit() else 0,
        "mtime": meta[2][:19],
        "mode": meta[3],
        "owner": f"{meta[4]}:{meta[5]}",
    }


def read_file(
    ssh_run: SshRun, server: ServerLike, path: str, max_bytes: int, preview_bytes: int,
) -> dict:
    """Le o arquivo para o editor.

    Arquivo dentro do limite vem inteiro e editavel. Acima do limite vem so o fim
    (somente leitura) — quem precisa do arquivo completo usa o download.
    """
    proc = ssh_run(
        server,
        quote_command("bash", "-lc", READ_SCRIPT, "gp", path, str(max_bytes), str(preview_bytes)),
        timeout=180,
    )
    if proc.returncode != 0:
        raise RemoteError((proc.stderr or proc.stdout).strip() or "falha ao ler o arquivo")
    head, _, payload = proc.stdout.partition("\n")
    meta = _parse_meta(head, 7)
    try:
        raw = base64.b64decode(payload.strip() or "", validate=True)
    except ValueError as exc:  # binascii.Error e uma subclasse de ValueError
        raise RemoteError("conteudo do arquivo chegou corrompido") from exc
    binary = b"\x00" in raw
    truncated = meta[6] == "tail"
    text = "" if binary else raw.decode("utf-8", "replace")
    return {
        "path": path,
        "name": path.rsplit("/", 1)[-1] or "arquivo",
        "size": int(meta[1]) if meta[1].isdigit() else len(raw),
        "mtime": meta[2][:19],
        "mode": meta[3],
        "owner": f"{meta[4]}:{meta[5]}",
        "binary": binary,
        # Fim do arquivo apenas: editar e salvar daqui apagaria todo o resto.
        "truncated": truncated,
        "shown": len(raw),
        "editable": not binary and not truncated,
        "text": text,
        # \r\n vira \n no textarea; guardamos para devolver o arquivo como estava.
        "crlf": b"\r\n" in raw,
    }


def write_file(ssh_run: SshRun, server: ServerLike, path: str, data: bytes) -> str:
    """Grava o arquivo no container (com .bak, dono e permissao preservados)."""
    proc = ssh_run(
        server, quote_command("bash", "-lc", WRITE_SCRIPT, "gp", path), timeout=120,
        stdin_data=base64.b64encode(data),
    )
    if proc.returncode != 0:
        raise RemoteError((proc.stderr or proc.stdout).strip() or "falha ao gravar")
    return proc.stdout.strip()


def delete_file(ssh_run: SshRun, server: ServerLike, path: str) -> str:
    """Apaga um arquivo (ou pasta vazia) no container. Nao tem volta."""
    proc = ssh_run(server, quote_command("bash", "-lc", DELETE_SCRIPT, "gp", path), timeout=60)
    if proc.returncode != 0:
        raise RemoteError((proc.stderr or proc.stdout).strip() or "falha ao apagar")
    return proc.stdout.strip()


# --------------------------------------------------------- streaming

def ssh_stream_in(
    ssh_argv: SshArgv, server: ServerLike, remote_cmd: str, origem: Any, timeout: int, chunk_size: int,
) -> str:
    """Executa um comando remoto alimentando a entrada dele a partir de `origem`.

    Diferente de rodar com o conteudo todo na memoria: aqui os bytes passam em
    pedacos, do arquivo que o navegador enviou direto para o `cat` do outro lado. E o
    que permite subir um mod ou um save de varios GB.
    """
    argv = [*ssh_argv(server, connect_timeout=10), remote_cmd]
    try:
        proc = subprocess.Popen(  # noqa: S603  # NOSONAR - argv vem do SshClient, nunca cru de formulario
            argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
    except OSError as exc:
        raise RemoteError(f"falha ao executar ssh: {exc}") from exc

    # Numa variavel local porque `Popen.stdin` e Optional no tipo (Popen sem PIPE nao
    # tem entrada) e porque ela e zerada no `finally` la embaixo - o `close()` de la
    # precisa falar do MESMO objeto que o laco usou.
    entrada = proc.stdin
    if entrada is None:
        raise RemoteError("nao consegui abrir a entrada do ssh")

    try:
        while True:
            chunk = origem.read(chunk_size)
            if not chunk:
                break
            entrada.write(chunk)
    except OSError:
        # O outro lado desistiu (sem espaco, sem permissao): o motivo esta no stderr,
        # entao nao adianta reclamar do cano quebrado aqui. BrokenPipeError - o caso
        # tipico - ja e um OSError, entao listar os dois nao pegava nada a mais.
        pass
    finally:
        # Fechar a entrada e o que faz o `cat` remoto terminar. A referencia tem de ir
        # junto: o communicate() abaixo daria flush num arquivo ja fechado e estouraria
        # ValueError com o arquivo JA gravado do outro lado — erro na tela, upload feito.
        with contextlib.suppress(OSError):
            entrada.close()
        proc.stdin = None

    try:
        saida, erro = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise RemoteError(f"tempo esgotado ({timeout}s) enviando para {server['host']}") from None
    if proc.returncode != 0:
        detalhe = (erro or saida or b"").decode("utf-8", "replace").strip()
        raise RemoteError(detalhe or f"falha ao enviar (exit {proc.returncode})")
    return saida.decode("utf-8", "replace").strip()


def stream_remote_file(
    ssh_argv: SshArgv, server: ServerLike, path: str, chunk_size: int,
) -> Iterator[bytes]:
    """Joga o arquivo do container direto para o navegador, sem passar por disco.

    E `cat` na outra ponta lido em pedacos: um save de varios GB desce sem o painel
    guardar nada em memoria.
    """
    argv = [*ssh_argv(server), quote_command("cat", "--", path)]
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)  # noqa: S603  # NOSONAR - argv vem do SshClient
    # `Popen.stdout` e Optional no tipo; aqui ele existe porque o PIPE foi pedido acima.
    saida = proc.stdout
    if saida is None:
        raise RemoteError("nao consegui abrir a saida do ssh")

    def gerar() -> Iterator[bytes]:
        try:
            while True:
                chunk = saida.read(chunk_size)
                if not chunk:
                    break
                yield chunk
        finally:
            # Navegador que cancela no meio nao pode deixar um ssh orfao segurando fd.
            if proc.poll() is None:
                proc.kill()
            for pipe in (proc.stdout, proc.stderr):
                if pipe:
                    pipe.close()
            proc.wait()

    return gerar()
