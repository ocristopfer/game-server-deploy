"""Backup do container de jogo: tar.gz das pastas que valem a pena guardar, por SSH.

O backup mora DENTRO do container do jogo, nao no painel — e por isso que criar,
listar e apagar sao so um script remoto cada. Download e restauracao reaproveitam,
respectivamente, `runtime.files.stream_remote_file` e o comando que `comando_de_backup`
monta aqui (o painel encadeia com o `RESTORE_SCRIPT` e o `systemctl stop/start` do
proprio servico - isso e orquestracao de job, fica em app.py).
"""
from __future__ import annotations

import re
import subprocess
from collections.abc import Callable

from gamepanel.i18n import Message
from gamepanel.runtime.ssh import RemoteError, ServerLike, quote_command

SshRun = Callable[..., subprocess.CompletedProcess]

# $1 = pasta dos backups, $2 = prefixo do servidor, $3 = quantas copias manter,
# $4 = sufixo do nome (a copia de seguranca do restore usa isto), $5.. = o que guardar.
BACKUP_SCRIPT = r"""
set -e
dir=$1
nome=$2
manter=$3
sufixo=$4
shift 4
[ $# -gt 0 ] || { echo "nenhuma pasta para guardar" >&2; exit 3; }

# Caminho que ainda nao existe NAO e erro: a pasta de save so nasce quando alguem entra
# no servidor pela primeira vez, e o cadastro do jogo ja aponta para ela. Cada ausente
# vira um aviso e os demais continuam entrando; so para se nao sobrar nenhum.
# (Roda os argumentos: tira o primeiro, e se ele existir devolve no fim da lista.)
n=$#
i=0
while [ "$i" -lt "$n" ]; do
  p=$1
  shift
  i=$((i + 1))
  if [ -e "$p" ]; then
    set -- "$@" "$p"
  else
    echo "ignorado (ainda nao existe): $p"
  fi
done
[ $# -gt 0 ] || { echo "nada a guardar: nenhum dos caminhos existe no container" >&2; exit 3; }
mkdir -p -- "$dir"

# Espaco livre x tamanho do alvo. O .tar.gz sai bem menor que o original, entao esta
# margem e folgada de proposito: encher o disco do container derruba o jogo junto.
precisa=$(du -sk -- "$@" 2>/dev/null | awk '{ t += $1 } END { print t+0 }')
livre=$(df -Pk -- "$dir" | awk 'NR>1 { print $4; exit }')
if [ "${livre:-0}" -lt "${precisa:-0}" ]; then
  echo "sem espaco em $dir: o alvo ocupa ${precisa}KB e sobram ${livre}KB" >&2
  exit 4
fi

alvo="$dir/$nome-$(date +%Y%m%d-%H%M%S)$sufixo.tar.gz"
tmp="$alvo.parcial"
lista=$(mktemp)
trap 'rm -f "$tmp" "$lista"' EXIT
# Caminho absoluto vira relativo dentro do tar (-C /): e o que faz o restore devolver
# cada arquivo exatamente de onde ele saiu.
for p in "$@"; do printf '%s\n' "${p#/}" >> "$lista"; done

# tar sai com 1 quando um arquivo muda durante a leitura — normal com o servidor ligado,
# e nao invalida o backup. So o codigo 2 (erro de verdade) aborta.
set +e
tar -czf "$tmp" --warning=no-file-changed -C / -T "$lista"
rc=$?
set -e
[ "$rc" -le 1 ] || { echo "tar falhou (codigo $rc)" >&2; exit 5; }
[ "$rc" -eq 1 ] && echo "aviso: arquivo mudou durante a copia; pare o servidor para uma copia mais fiel"

mv -- "$tmp" "$alvo"
echo "backup pronto: $alvo ($(stat -Lc %s -- "$alvo") bytes)"

# Retencao: mantem as N copias mais novas DESTE servidor e apaga o resto.
if [ "$manter" -gt 0 ]; then
  ls -1t -- "$dir/$nome-"*.tar.gz 2>/dev/null | tail -n +$((manter + 1)) | while IFS= read -r velho; do
    rm -f -- "$velho" && echo "retencao: apagado $(basename -- "$velho")"
  done
fi
"""

# $1 = pasta dos backups, $2 = prefixo do servidor.
BACKUP_LIST_SCRIPT = r"""
set -e
dir=$1
nome=$2
[ -d "$dir" ] || exit 0
# Nome primeiro: como ele comeca com a data, o sort reverso ja poe o mais novo em cima.
find "$dir" -maxdepth 1 -type f -name "$nome-*.tar.gz" \
  -printf '%f\t%s\t%TY-%Tm-%Td %TH:%TM\n' 2>/dev/null | LC_ALL=C sort -r | head -n "$3"
"""

# $1 = pasta dos backups, $2 = nome do arquivo, $3 = unidade systemd do jogo.
RESTORE_SCRIPT = r"""
set -e
dir=$1
arq=$2
unit=$3
# O nome vem da tela: barra aqui deixaria escolher qualquer .tar.gz do container.
case "$arq" in
  ''|*/*|*..*) echo "nome de backup invalido" >&2; exit 3 ;;
esac
f="$dir/$arq"
[ -f "$f" ] || { echo "backup nao encontrado: $arq" >&2; exit 3; }
# Confere ANTES de parar o servidor: descobrir que o arquivo esta corrompido com o jogo
# ja parado e a pior hora possivel.
gzip -t -- "$f" 2>/dev/null || { echo "arquivo corrompido (gzip nao le): $arq" >&2; exit 4; }
tar -tzf "$f" >/dev/null 2>&1 || { echo "arquivo corrompido (tar nao le): $arq" >&2; exit 4; }

estava=$(systemctl is-active "$unit" 2>/dev/null || true)
if [ "$estava" = active ]; then
  systemctl stop "$unit"
  echo "servidor parado para a restauracao"
fi

tar -xzf "$f" -C /
echo "restaurado: $arq"

# Servidor que ja estava parado continua parado: restaurar nao e ligar.
if [ "$estava" = active ]; then
  systemctl start "$unit"
  echo "servidor religado"
fi
"""

# $1 = pasta dos backups, $2 = nome do arquivo.
BACKUP_DELETE_SCRIPT = r"""
set -e
dir=$1
arq=$2
case "$arq" in
  ''|*/*|*..*) echo "nome de backup invalido" >&2; exit 3 ;;
esac
f="$dir/$arq"
[ -f "$f" ] || { echo "backup nao encontrado: $arq" >&2; exit 3; }
sz=$(stat -Lc %s -- "$f")
rm -f -- "$f"
echo "backup apagado: $arq ($sz bytes)"
"""

BACKUP_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,120}\.tar\.gz$")


def validate_backup_name(raw: str) -> str:
    """Confere o nome que voltou da tela antes de ele entrar num comando remoto."""
    name = (raw or "").strip()
    if not BACKUP_NAME_RE.match(name) or ".." in name:
        raise ValueError(Message("backup.bad_name"))
    return name


def backup_paths(server: ServerLike, max_paths: int) -> list[str]:
    """O que entra no backup deste servidor.

    Sem nada cadastrado vale a pasta de configuracao, que e onde o save costuma morar —
    e o padrao que evita cadastrar servidor nenhum so para ter backup.
    """
    escolhidos = [ln.strip() for ln in (server["backup_paths"] or "").splitlines() if ln.strip()]
    if escolhidos:
        return escolhidos[:max_paths]
    padrao = (server["config_path"] or "").strip()
    return [padrao] if padrao else []


def backup_prefix(server: ServerLike) -> str:
    """Prefixo dos arquivos deste servidor: e ele que separa (e limita) as copias.

    Sai do nome da unidade systemd, que ja e unica por container. O saneamento importa
    porque o prefixo entra num glob de shell la do outro lado.
    """
    bruto = (server["service"] or "jogo").rsplit(".service", 1)[0]
    limpo = re.sub(r"[^A-Za-z0-9_-]", "-", bruto).strip("-")
    return limpo or "jogo"


def backup_command(
    server: ServerLike, backup_dir: str, keep: int, paths: list[str], suffix: str = "",
) -> str:
    """Monta o comando remoto do backup. Usado pela tela, pelo restore e pelo agendador."""
    return quote_command(
        "bash", "-lc", BACKUP_SCRIPT, "gp", backup_dir, backup_prefix(server), str(keep), suffix, *paths,
    )


_LIST_LINE_FIELDS = 3


def list_backups(ssh_run: SshRun, server: ServerLike, backup_dir: str, limit: int) -> list[dict]:
    proc = ssh_run(
        server,
        quote_command("bash", "-lc", BACKUP_LIST_SCRIPT, "gp", backup_dir, backup_prefix(server), str(limit)),
        timeout=40,
    )
    if proc.returncode != 0:
        raise RemoteError((proc.stderr or proc.stdout).strip() or "falha ao listar os backups")
    copias: list[dict] = []
    for linha in proc.stdout.splitlines():
        partes = linha.split("\t", 2)
        if len(partes) != _LIST_LINE_FIELDS:
            continue
        copias.append({
            "name": partes[0],
            "size": int(partes[1]) if partes[1].isdigit() else 0,
            "mtime": partes[2],
            # A copia que o proprio painel tira antes de restaurar: some no meio das
            # outras se nao for marcada, e e justamente a que salva quem restaurou errado.
            "seguranca": partes[0].endswith("-antes-de-restaurar.tar.gz"),
        })
    return copias


def delete_backup(ssh_run: SshRun, server: ServerLike, backup_dir: str, name: str) -> str:
    proc = ssh_run(server, quote_command("bash", "-lc", BACKUP_DELETE_SCRIPT, "gp", backup_dir, name), timeout=40)
    if proc.returncode != 0:
        raise RemoteError((proc.stderr or proc.stdout).strip() or "falha ao apagar o backup")
    return proc.stdout.strip()
