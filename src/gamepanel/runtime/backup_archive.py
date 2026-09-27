"""A segunda copia do backup, guardada no PAINEL alem da que fica no container do jogo.

A copia de dentro do container morre com ele: remover uma instancia pelo broker apaga o
CT com os discos (`purge=1`), e o save ia junto. A daqui sobrevive a isso.

Ela e organizada pelo PREFIXO do backup (o nome do servico: `valheim`), e nao pelo id do
servidor no painel. O servidor recriado ganha outro id, mas o jogo do catalogo sobe com o
mesmo servico — e e so por isso que o Valheim novo enxerga o save do Valheim que foi
removido. Os caminhos dentro do tar sao absolutos (`-C /`), e o jogo recriado pelo mesmo
catalogo usa os mesmos, entao restaurar aqui e o mesmo `RESTORE_SCRIPT` de sempre.

So disco local e stdlib: nada aqui fala SSH. Quem puxa e quem devolve e o `app.py`,
que passa os pedacos (`stream_remote_file`) ou le o arquivo daqui para a entrada do ssh.
"""
from __future__ import annotations

import os
import posixpath
import re
import time
from collections.abc import Iterable

from gamepanel.runtime.backups import validate_backup_name

# A linha que o `BACKUP_SCRIPT` escreve ao terminar. E ela que diz ao painel QUAL arquivo
# puxar: o nome leva a hora do container, que o painel nao tem como adivinhar. Mudar a
# frase la sem mudar aqui deixa o backup sem segunda copia — o teste compara os dois.
DONE_RE = re.compile(r"^backup pronto: (.+) \((\d+) bytes\)$", re.MULTILINE)
PREFIX_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$", re.ASCII)
PARTIAL_SUFFIX = ".parcial"
SAFETY_SUFFIX = "-antes-de-restaurar.tar.gz"
_CHMOD_PRIVATE = 0o700
_CHMOD_FILE = 0o600


def created_file(output: str, backup_dir: str) -> tuple[str, int] | None:
    """Caminho e tamanho do ULTIMO backup que a saida anuncia, se ele mora na pasta certa.

    A pasta e conferida porque o caminho vem do texto de um comando remoto: sem isto, uma
    linha forjada na saida faria o painel puxar qualquer arquivo do container.
    """
    found = DONE_RE.findall(output or "")
    if not found:
        return None
    path, size = found[-1]
    if posixpath.dirname(path) != backup_dir.rstrip("/"):
        return None
    validate_backup_name(posixpath.basename(path))
    return path, int(size)


def _folder(root: str, prefix: str) -> str:
    if not PREFIX_RE.match(prefix or ""):
        raise ValueError(f"prefixo de backup invalido: {prefix!r}")
    return os.path.join(root, prefix)


def path_of(root: str, prefix: str, name: str) -> str:
    """O arquivo guardado, conferido. `FileNotFoundError` quando nao existe."""
    path = os.path.join(_folder(root, prefix), validate_backup_name(name))
    if not os.path.isfile(path):
        raise FileNotFoundError(name)
    return path


def store(root: str, prefix: str, name: str, chunks: Iterable[bytes],
          expected_size: int | None, keep: int) -> tuple[int, list[str]]:
    """Grava a copia e aplica a retencao. Devolve (bytes gravados, nomes apagados).

    Grava num `.parcial` e so renomeia no fim, com o tamanho conferido: o `cat` remoto
    que cai no meio NAO da erro para quem le os pedacos, so para de mandar — e uma copia
    truncada com o nome certo seria pior que nenhuma, porque ninguem desconfiaria dela.
    """
    folder = _folder(root, prefix)
    os.makedirs(folder, mode=_CHMOD_PRIVATE, exist_ok=True)
    final = os.path.join(folder, validate_backup_name(name))
    partial = final + PARTIAL_SUFFIX
    written = 0
    try:
        with open(partial, "wb") as out:
            for chunk in chunks:
                out.write(chunk)
                written += len(chunk)
            out.flush()
            os.fsync(out.fileno())
        if expected_size is not None and written != expected_size:
            raise OSError(f"copia incompleta: chegaram {written} de {expected_size} bytes")
        # Save e dado de quem joga, e o painel nao e o unico servico da maquina.
        os.chmod(partial, _CHMOD_FILE)
        os.replace(partial, final)
    finally:
        if os.path.exists(partial):
            os.remove(partial)
    return written, prune(root, prefix, keep)


def prune(root: str, prefix: str, keep: int) -> list[str]:
    """Mantem as `keep` copias mais novas deste prefixo. 0 = nunca apagar."""
    if keep <= 0:
        return []
    removed = []
    for item in list_copies(root, prefix)[keep:]:
        os.remove(os.path.join(_folder(root, prefix), item["name"]))
        removed.append(item["name"])
    return removed


def list_copies(root: str, prefix: str) -> list[dict]:
    """As copias deste prefixo, a mais nova primeiro (mesmo formato da lista do container)."""
    folder = _folder(root, prefix)
    try:
        entries = list(os.scandir(folder))
    except FileNotFoundError:
        return []
    copies = []
    for entry in entries:
        if not entry.is_file() or not entry.name.startswith(prefix + "-") or not entry.name.endswith(".tar.gz"):
            continue
        info = entry.stat()
        copies.append({
            "name": entry.name,
            "size": info.st_size,
            "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(info.st_mtime)),
            "seguranca": entry.name.endswith(SAFETY_SUFFIX),
            "_ts": info.st_mtime,
        })
    # Empate de mtime (duas copias no mesmo segundo) cai no nome, que comeca pela data.
    copies.sort(key=lambda c: (c["_ts"], c["name"]), reverse=True)
    for c in copies:
        del c["_ts"]
    return copies


def delete(root: str, prefix: str, name: str) -> int:
    """Apaga uma copia. Devolve o tamanho que ela tinha."""
    path = path_of(root, prefix, name)
    size = os.path.getsize(path)
    os.remove(path)
    return size


def list_games(root: str) -> list[str]:
    """Os prefixos (jogos) que tem copia no painel, com ou sem servidor cadastrado.

    E a lista que faltava: a aba Backups de um servidor so mostra o prefixo DELE, entao a
    copia de um jogo removido ficava guardada e sem tela nenhuma que a mostrasse.
    """
    try:
        entries = list(os.scandir(root))
    except FileNotFoundError:
        return []
    return sorted(
        e.name for e in entries
        if e.is_dir() and PREFIX_RE.match(e.name) and list_copies(root, e.name)
    )
