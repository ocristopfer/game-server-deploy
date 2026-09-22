#!/usr/bin/env python3
"""Gera `admin/sugestoes_de_jogos.py` a partir do catalogo do LinuxGSM.

O LinuxGSM (MIT, https://github.com/GameServerManagers/LinuxGSM) mantem, para ~140 jogos, o
App ID do servidor dedicado, as portas padrao, o executavel e os parametros de start. O painel
usa isso como SUGESTAO no formulario "Adicionar jogo": a pessoa escolhe o jogo, confere e
envia — quem decide o que e valido continua sendo o broker.

Roda na maquina de desenvolvimento (precisa de internet); o painel em producao NAO baixa nada:
le o arquivo gerado, que vai no repositorio.

    python tools/importar-linuxgsm.py                    # baixa do GitHub
    python tools/importar-linuxgsm.py --de PASTA         # usa uma copia local (serverlist.csv + <jogo>.cfg)

Regras de seguranca (cada uma tem teste em broker/test_importar_linuxgsm.py):

- So sai sugestao que o broker aceitaria: o filtro final e o proprio `validar_dinamico`.
- Porta de RCON, telnet, HTTP e SourceTV NUNCA vira porta exposta: o valor padrao vai so nos
  argumentos, para o jogo subir, e ela continua atras do firewall.
- Variavel de senha, nome do servidor, IP e token NUNCA e resolvida: o argumento que a usa e
  removido e a sugestao avisa. Nada de "CHANGE_ME" do LinuxGSM indo parar num servidor real.
- O que nao cabe no charset de argumentos do broker (aspas, `$`, `;`...) e removido, nunca escapado.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import datetime
import io
import pathlib
import posixpath
import pprint
import re
import shlex
import sys
import time
import unicodedata
import urllib.request

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from broker.catalogo import CHAVE_RE, NOME_RE, validar_dinamico  # noqa: E402
from broker.erros import ErroDeValidacao  # noqa: E402

FONTE_URL = "https://raw.githubusercontent.com/GameServerManagers/LinuxGSM/master/"
PASTA_DO_JOGO = "/opt/game"

# Portas que o jogo anuncia para o cliente e por isso precisam existir no NAT.
PORTAS_EXPOSTAS = ("clientport", "beaconport", "reliableport", "modserverport")
# Portas de administracao: o numero vai nos argumentos, mas NUNCA sai do container.
PORTAS_INTERNAS = ("rconport", "telnetport", "httpport", "sourcetvport", "appport")
# Protocolo que nao e UDP. O resto e presumido UDP (e o aviso da sugestao diz isso).
PROTOCOLO_DA_VARIAVEL = {"reliableport": "tcp", "httpport": "tcp"}
# Variavel cujo nome contem qualquer um destes trechos nunca e resolvida.
SEGREDOS = ("pass", "gslt", "token", "key", "secret", "servername", "selfname", "ip", "rcon")

_ATRIBUICAO = re.compile(r"""^([a-z_][a-z0-9_]*)=(?:"(.*)"|'(.*)'|([^\s#"']*))\s*(?:#.*)?$""", re.M)
_VARIAVEL = re.compile(r"\$\{([a-z_][a-z0-9_]*)\}")
_CHARSET_ARGS = re.compile(r"[A-Za-z0-9._=:,/+@?{}-]+")
_ENCADEAMENTO = re.compile(r"[;|&`<>]|\$\(")


def ler_atribuicoes(texto: str) -> dict[str, str]:
    """`nome="valor"` de um _default.cfg. A ultima atribuicao vence, como no shell."""
    valores: dict[str, str] = {}
    for m in _ATRIBUICAO.finditer(texto):
        valores[m.group(1)] = next(g for g in m.groups()[1:] if g is not None)
    return valores


def _e_segredo(nome: str) -> bool:
    return any(trecho in nome for trecho in SEGREDOS)


def resolver(valor: str, variaveis: dict[str, str], extras: dict[str, str] | None = None,
             fundo: int = 6) -> str:
    """Troca ${nome} pelo que der; o que sobra fica como esta (e depois vira aviso).

    `extras` (portas e pastas) vence `variaveis`. Variavel de segredo nunca e trocada.
    """
    extras = extras or {}
    for _ in range(fundo):
        def troca(m: re.Match) -> str:
            nome = m.group(1)
            if nome in extras:
                return extras[nome]
            if nome in variaveis and not _e_segredo(nome):
                # Valor vazio ("+server.seed ${seed}" com seed="") deixaria a opcao sem valor, e
                # ela engoliria a proxima da linha. Fica marcado como nao resolvido: sai junto.
                return variaveis[nome] or "${vazio}"
            return m.group(0)
        novo = _VARIAVEL.sub(troca, valor)
        if novo == valor:
            break
        valor = novo
    return valor


def _numero(texto: str) -> int | None:
    return int(texto) if re.fullmatch(r"\d{1,5}", texto or "") and 1 <= int(texto) <= 65535 else None


def _ascii(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()


def nome_de_exibicao(gamename: str) -> str:
    limpo = re.sub(r"[^A-Za-z0-9 ._-]+", " ", _ascii(gamename))
    limpo = re.sub(r"\s+", " ", limpo).strip(" .-_")
    return limpo[:40].rstrip(" .-_")


def chave_do_jogo(gamename: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", _ascii(gamename).lower()).strip("-")
    if not slug or not slug[0].isalpha():
        slug = f"g-{slug}"
    return slug[:24].rstrip("-")


def _dividir(args: str) -> list[str]:
    try:
        return shlex.split(args, posix=True)
    except ValueError:
        return args.split()


def _limpar_argumentos(args: str) -> tuple[str, list[str]]:
    """Fica so com o que o broker aceita. Devolve (argumentos, nomes do que foi removido)."""
    # `;`, `|`, `&`, crase, `$(` e redirecionamento encadeiam OUTRO comando no shell: o que vem
    # depois nao e argumento do jogo e nao entra, nem como palavras soltas.
    corte = _ENCADEAMENTO.search(args)
    encadeado = corte is not None
    if corte:
        args = args[:corte.start()]
    tokens = _dividir(args)
    manter = [bool(_CHARSET_ARGS.fullmatch(t)) and "${" not in t for t in tokens]
    # Sem o valor, a opcao que o pedia ("-name") engoliria a proxima opcao da linha: sai junto.
    for i, ok in enumerate(manter):
        if not ok and i > 0 and manter[i - 1] and tokens[i - 1][0] in "-+" \
                and "=" not in tokens[i - 1] and tokens[i][:1] not in ("-", "+"):
            manter[i - 1] = False
    fica = [t for t, ok in zip(tokens, manter) if ok]
    saiu = [t.split("=", 1)[0].lstrip("-+") for t, ok in zip(tokens, manter) if not ok and t[:1] in "-+"]
    if encadeado:
        saiu.append("comando encadeado")
    return " ".join(fica), saiu


def sugerir(gamename: str, texto_do_cfg: str) -> dict | None:
    """Uma sugestao de jogo, ou None se nao da para montar uma que o broker aceite."""
    v = ler_atribuicoes(texto_do_cfg)
    appid = int(v["appid"]) if v.get("appid", "").isdigit() else 0
    if not appid:
        return None
    # Uns 30 jogos guardam a porta no arquivo de config do PROPRIO jogo, nao no LinuxGSM. Mesmo
    # assim o App ID (a parte que ninguem sabe de cor) vale a sugestao: fica sem porta e avisa.
    porta = _numero(v.get("port", "")) or 0
    avisos: list[str] = []
    if not porta:
        avisos.append("Este jogo guarda as portas no proprio arquivo de configuracao: preencha "
                      "as portas depois de instalar e ver o que ele abre.")
    args_brutos = v.get("startparameters", "")

    var_query = next((n for n in ("queryport", "steamport")
                      if _numero(v.get(n, "")) and f"${{{n}}}" in args_brutos), "")
    extras_da_rede = [n for n in PORTAS_EXPOSTAS
                      if _numero(v.get(n, "")) and f"${{{n}}}" in args_brutos]

    trocas = {"serverfiles": PASTA_DO_JOGO}
    if porta:
        trocas["port"] = "{PORT}"
    if var_query:
        trocas[var_query] = "{QUERY_PORT}"
    # O broker avisa ao jogo UMA porta extra. Com duas ou mais (Satisfactory antigo tem beacon e
    # confiavel) elas ficam com o numero padrao e o jogo nao anda de porta.
    var_extra = extras_da_rede[0] if len(extras_da_rede) == 1 else ""
    if var_extra:
        trocas[var_extra] = "{EXTRA_PORT}"
    # Toda outra porta vira o NUMERO padrao: o jogo sobe com ela, e so as expostas vao ao NAT.
    for nome in PORTAS_EXPOSTAS + PORTAS_INTERNAS + ("queryport", "steamport", "clientport"):
        if nome not in trocas and _numero(v.get(nome, "")):
            trocas[nome] = v[nome]
    argumentos, removidos = _limpar_argumentos(resolver(args_brutos, v, trocas))
    if removidos:
        avisos.append("Removi do comando o que o painel nao passa (" + ", ".join(dict.fromkeys(removidos))
                      + "): nome do servidor, senha, IP e caminhos de config. Acrescente o que faltar.")

    portas = [f"{porta}/udp"] if porta else []
    if var_query:
        portas.append(f"{_numero(v[var_query])}/udp")
    portas += [f"{_numero(v[n])}/{PROTOCOLO_DA_VARIAVEL.get(n, 'udp')}" for n in extras_da_rede]
    portas = list(dict.fromkeys(portas))
    escondidas = [n for n in PORTAS_INTERNAS if _numero(v.get(n, "")) and f"${{{n}}}" in args_brutos]
    if escondidas:
        avisos.append("Portas de administracao (" + ", ".join(escondidas)
                      + ") ficam so dentro do container, de proposito: nao entram no firewall.")
    avisos.append("Protocolo UDP presumido em todas as portas: confira (query e TCP em alguns jogos).")

    script = ""
    executavel = resolver(v.get("executable", ""), v, {"serverfiles": PASTA_DO_JOGO})
    pasta = resolver(v.get("executabledir", "${serverfiles}"), v, {"serverfiles": PASTA_DO_JOGO})
    caminho = posixpath.normpath(posixpath.join(pasta, executavel)) if executavel else ""
    if caminho.startswith(PASTA_DO_JOGO + "/") and "${" not in caminho:
        script = caminho[len(PASTA_DO_JOGO) + 1:]
        avisos.append("O executavel e o do LinuxGSM (binario direto). Se o servidor nao subir, "
                      "use o script .sh que vem na pasta do jogo.")
    elif executavel:
        avisos.append("Nao consegui deduzir o executavel: preencha o script de start.")

    deslocavel = (porta and len(extras_da_rede) <= 1 and "{PORT}" in argumentos
                  and (not var_query or "{QUERY_PORT}" in argumentos)
                  and (not var_extra or "{EXTRA_PORT}" in argumentos))
    sugestao = {
        "appid": appid, "nome": nome_de_exibicao(gamename), "chave": chave_do_jogo(gamename),
        "portas": " ".join(portas), "porta_jogo": porta,
        "porta_query": _numero(v[var_query]) if var_query else 0,
        "porta_extra": _numero(v[var_extra]) if var_extra else 0,
        "start_script": script, "start_args": argumentos,
        "deslocavel": bool(deslocavel), "avisos": avisos,
    }
    return _passar_pelo_broker(sugestao)


def _como_dados_do_painel(s: dict) -> dict:
    # Sem porta (sugestao parcial) o validador recebe uma qualquer: o que se confere aqui e o resto.
    dados: dict = {"chave": s["chave"], "nome": s["nome"], "app_id": s["appid"],
                   "portas": s["portas"].split() or ["27015/udp"], "porta_jogo": s["porta_jogo"] or 27015,
                   "receitas": [], "config_files": [], "backup_paths": [],
                   "deslocavel": s["deslocavel"]}
    for campo in ("start_script", "start_args"):
        if s[campo]:
            dados[campo] = s[campo]
    if s["porta_query"]:
        dados["porta_query"] = s["porta_query"]
    if s.get("porta_extra"):
        dados["porta_extra"] = s["porta_extra"]
    return dados


def _passar_pelo_broker(s: dict) -> dict | None:
    """Filtro final: o validador do broker. Campo opcional recusado e removido (com aviso);
    identidade ou porta recusada derruba a sugestao inteira."""
    for _ in range(4):
        try:
            validar_dinamico(_como_dados_do_painel(s))
            return s
        except ErroDeValidacao as erro:
            campo = getattr(erro, "campo", "")
            if campo in ("start_script", "start_args"):
                s = {**s, campo: "", "deslocavel": False,
                     "avisos": s["avisos"] + [f"O broker recusaria {campo}; deixei em branco."]}
            elif campo == "deslocavel":
                s = {**s, "deslocavel": False}
            else:
                return None
    return None


# ---------------------------------------------------------------- download e escrita

def _baixar(url: str, tentativas: int = 3) -> str | None:
    for i in range(tentativas):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "gamepanel-importador"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            time.sleep(1 + i)
    return None


def _ler_da_pasta(pasta: pathlib.Path, servidor: str) -> str | None:
    arquivo = pasta / f"{servidor}.cfg"
    return arquivo.read_text(encoding="utf-8") if arquivo.exists() else None


def coletar(pasta_local: pathlib.Path | None) -> tuple[list[dict], list[str]]:
    if pasta_local:
        lista = (pasta_local / "serverlist.csv").read_text(encoding="utf-8")
        obter = lambda n: _ler_da_pasta(pasta_local, n)  # noqa: E731
    else:
        lista = _baixar(FONTE_URL + "lgsm/data/serverlist.csv") or ""
        obter = lambda n: _baixar(FONTE_URL + f"lgsm/config-default/config-lgsm/{n}/_default.cfg")  # noqa: E731
    jogos = list(csv.DictReader(io.StringIO(lista)))
    if not jogos:
        raise SystemExit("serverlist.csv vazio ou inacessivel")
    with concurrent.futures.ThreadPoolExecutor(6) as pool:
        textos = list(pool.map(lambda j: obter(j["gameservername"]), jogos))
    sugestoes, pulados = [], []
    for j, texto in zip(jogos, textos):
        s = sugerir(j["gamename"], texto) if texto else None
        (sugestoes if s else pulados).append(s or j["gamename"])
    # Dois jogos com o mesmo nome (ou chave) tornariam a busca ambigua: fica o primeiro.
    vistos: set[str] = set()
    unicas = []
    for s in sorted(sugestoes, key=lambda s: s["nome"].lower()):
        if s["chave"] in vistos:
            pulados.append(s["nome"])
            continue
        vistos.add(s["chave"])
        unicas.append(s)
    return unicas, pulados


def escrever(sugestoes: list[dict], saida: pathlib.Path) -> None:
    corpo = "".join(f"    {pprint.pformat(s, width=110, sort_dicts=False).replace(chr(10), chr(10) + '    ')},\n"
                    for s in sugestoes)
    texto = (
        '"""Sugestoes de jogo para o formulario "Adicionar jogo" — GERADO, NAO EDITE.\n\n'
        "Gerado por tools/importar-linuxgsm.py a partir do LinuxGSM (MIT). Para atualizar, rode\n"
        "o script e revise o diff: cada linha aqui e uma sugestao que o broker valida de novo.\n"
        '"""\n'
        f'FONTE = "LinuxGSM (MIT), gerado em {datetime.date.today().isoformat()}"\n\n'
        f"SUGESTOES = (\n{corpo})\n"
    )
    saida.write_bytes(texto.encode("utf-8"))  # bytes: no Windows o modo texto trocaria \n por \r\n


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--de", type=pathlib.Path, help="pasta local com serverlist.csv e <servidor>.cfg")
    ap.add_argument("--saida", type=pathlib.Path, default=RAIZ / "admin" / "sugestoes_de_jogos.py")
    opts = ap.parse_args()
    sugestoes, pulados = coletar(opts.de)
    escrever(sugestoes, opts.saida)
    print(f"{len(sugestoes)} sugestoes em {opts.saida} ({len(pulados)} jogos sem app id/porta ou repetidos)")


if __name__ == "__main__":
    main()
