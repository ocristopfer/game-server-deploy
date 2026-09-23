#!/usr/bin/env python3
"""Empacota um release: um tar.gz, um sha256, e nada mais.

    python tools/build-release.py gamepanel
    python tools/build-release.py gamebroker --out dist

O que sai e o que o deploy manda pela rede: `dist/gamepanel-0.1.0+abc1234.tar.gz` mais o
`.sha256` ao lado. Do outro lado ele vira `/opt/gamepanel/releases/<versao>/`, e o
symlink `current` passa a apontar para a pasta nova — trocar de versao (ou voltar) e
mover um symlink, nao copiar arquivo por cima de arquivo.

Tres decisoes que parecem detalhe e nao sao:

- **`tarfile`, da stdlib, e nao um pacote Python de verdade.** Producao so tem stdlib e o
  `python3-flask` do apt: nao ha pip para instalar um wheel, e um binario de PyInstaller
  traria Python e Flask proprios, jogando fora justamente essa garantia.
- **Um arquivo so, com hash.** O envio antigo copiava a arvore inteira arquivo a arquivo,
  com uma lista escrita a mao de quais pastas apagar antes — lista que ficou para tras a
  cada pasta nova do pacote, deixando modulo renomeado vivo no container. Aqui nao existe
  o que sobrar: release nova e pasta nova.
- **Byte a byte.** O envio antigo passava cada arquivo por um normalizador de fim de
  linha, e um PNG que caisse nessa peneira chegava corrompido do outro lado (o icone do
  PWA ja chegou). Um tar nao interpreta conteudo.

O conteudo e determinista: nomes ordenados, dono/grupo zerados e a data do commit no
lugar do mtime de cada arquivo. Duas chamadas no mesmo commit dao o MESMO sha256, o que
faz o hash responder "o CT esta com este codigo?" e nao so "o arquivo chegou inteiro?".
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import subprocess
import sys
import tarfile
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = ("gamepanel", "gamebroker")
SKIPPED_DIRS = ("__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache")
SKIPPED_SUFFIXES = (".pyc", ".pyo")
# O que NAO vai para producao: dobres de teste e o broker de brinquedo que o docker
# compose sobe. `dev.py` e o caso que importa — ele cria instancia contra backends falsos,
# e no CT de verdade seria um jeito de fazer o broker mentir sobre o que existe.
SKIPPED_NAMES = ("dev.py", "conftest.py", "fakes.py", "http_falso.py")
SKIPPED_PREFIXES = ("test_",)
FILE_MODE = 0o644
READ_BLOCK = 1 << 20

BUILD_TEMPLATE = '''"""GERADO por tools/build-release.py ao empacotar. Nao edite, nao commite."""
VERSION = {version!r}
COMMIT = {commit!r}
BUILT_AT = {built_at!r}
'''


def _git(*args: str) -> str:
    """Roda um git na raiz do repositorio; devolve vazio se nao der (arvore sem .git)."""
    try:
        # Argumentos fixos, nenhum vem de fora; e `git` pelo PATH de proposito, porque
        # esta e ferramenta de desenvolvimento e o caminho muda em cada maquina.
        done = subprocess.run(("git", *args), cwd=ROOT, capture_output=True,  # noqa: S603, S607
                              text=True, check=False)
    except OSError:
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


class Release(NamedTuple):
    """Versao, commit e data — o que vai para dentro do pacote e para o nome do arquivo."""

    version: str
    commit: str
    built_at: str
    dirty: bool


def describe() -> Release:
    """`0.1.0+abc1234`, ou `0.1.0+abc1234.dirty` se ha mudanca nao commitada.

    O `.dirty` e de proposito visivel no nome do arquivo e na tela: um release que nao
    corresponde a nenhum commit nao pode ser confundido com um que corresponde, senao
    "voltei para a 0.1.0" um dia devolve outro codigo.
    """
    base = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    commit = _git("rev-parse", "--short=7", "HEAD")
    if not commit:
        # Sem git nao ha commit nem data de commit. Cair no relogio aqui custaria o
        # determinismo — a data entra no carimbo E no mtime de cada arquivo do tar, entao
        # dois empacotamentos do mesmo codigo dariam sha256 diferentes e o hash deixaria
        # de responder "o CT esta com este codigo?". Sem data e a resposta honesta.
        return Release(base, "", "", False)
    dirty = bool(_git("status", "--porcelain"))
    built_at = _git("show", "-s", "--format=%cI", "HEAD")
    version = f"{base}+{commit}" + (".dirty" if dirty else "")
    return Release(version, commit, built_at, dirty)


def _keep(path: Path) -> bool:
    return (
        not any(part in SKIPPED_DIRS for part in path.parts)
        and path.suffix not in SKIPPED_SUFFIXES
        and path.name not in SKIPPED_NAMES
        and not path.name.startswith(SKIPPED_PREFIXES)
    )


def _files_of(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*") if p.is_file() and _keep(p))


def _entry(name: str, data: bytes, when: int) -> tarfile.TarInfo:
    """Cabecalho sem dono, sem grupo e com data fixa: dois builds iguais, hash igual."""
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mtime = when
    info.mode = FILE_MODE
    info.uid = info.gid = 0
    info.uname = info.gname = "root"
    return info


def build(package: str, out_dir: Path, release: Release) -> Path:
    source = ROOT / "src" / package
    if not source.is_dir():
        raise SystemExit(f"pacote nao encontrado: {source}")
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{package}-{release.version}.tar.gz"
    when = int(datetime.fromisoformat(release.built_at).timestamp()) if release.built_at else 0

    # O gzip e montado a mao so por causa do `mtime=0`: o `mode="w:gz"` do tarfile carimba
    # a hora do empacotamento no cabecalho do gzip, e o mesmo commit daria um sha256
    # diferente a cada chamada — o hash deixaria de responder "o CT esta com este codigo?".
    with target.open("wb") as raw, gzip.GzipFile(
        fileobj=raw, mode="wb", mtime=0, compresslevel=9,
    ) as packed, tarfile.open(
        fileobj=packed, mode="w", format=tarfile.PAX_FORMAT,
    ) as tar:
        for path in _files_of(source):
            name = path.relative_to(source).as_posix()
            data = path.read_bytes()
            tar.addfile(_entry(f"{package}/{name}", data, when), io.BytesIO(data))
        stamp = BUILD_TEMPLATE.format(
            version=release.version, commit=release.commit, built_at=release.built_at,
        ).encode("utf-8")
        tar.addfile(_entry(f"{package}/_build.py", stamp, when), io.BytesIO(stamp))
    return target


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(READ_BLOCK), b""):
            digest.update(block)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Empacota um release de gamepanel ou gamebroker.")
    parser.add_argument("package", choices=PACKAGES)
    parser.add_argument("--out", default="dist", help="pasta de saida (padrao: dist/)")
    args = parser.parse_args(argv)

    release = describe()
    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    target = build(args.package, out_dir, release)
    checksum = _sha256(target)
    # O formato e o que o `sha256sum -c` do outro lado espera ler.
    (target.parent / (target.name + ".sha256")).write_text(
        f"{checksum}  {target.name}\n", encoding="utf-8", newline="\n",
    )

    print(f"{target.name}  {target.stat().st_size // 1024} KiB")
    print(f"sha256 {checksum}")
    if release.dirty:
        print("AVISO: a arvore tem mudanca nao commitada; o release saiu marcado .dirty",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
