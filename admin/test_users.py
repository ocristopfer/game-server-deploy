#!/usr/bin/env python3
"""Testes dos papeis (admin/operador) e da tela de usuarios.

    docker compose exec panel python3 /opt/gamepanel/test_users.py

O que estes testes garantem: um operador consegue operar os servidores ja cadastrados e
NAO consegue chegar em nada que da shell de root no container (terminal, console,
navegador de arquivos) nem em quem tem acesso ao painel. E que o painel nunca fica sem
nenhum administrador.
"""
import os
import tempfile

# Banco descartavel, e aqui e atribuicao — nao `setdefault` como nos outros testes.
# Estes criam, promovem e APAGAM usuarios: no container de dev o GAMEPANEL_DB ja vem
# apontado para o banco do painel, e um setdefault deixaria os testes mexerem nas contas
# de verdade (foi o que aconteceu na primeira versao deste arquivo).
os.environ["GAMEPANEL_DB"] = os.path.join(tempfile.mkdtemp(), "teste.db")

import app as panel  # noqa: E402

falhas = []


def check(nome, condicao, detalhe=""):
    if condicao:
        print(f"  ok   {nome}")
    else:
        print(f"  FALHOU {nome} {detalhe}")
        falhas.append(nome)


def igual(nome, obtido, esperado):
    check(nome, obtido == esperado, f"(obtido {obtido!r}, esperado {esperado!r})")


def conexao():
    return panel._connect()


def papel(username: str) -> str:
    conn = conexao()
    try:
        row = conn.execute("SELECT role FROM users WHERE username = ?", (username,)).fetchone()
        return row["role"] if row else ""
    finally:
        conn.close()


def existe(username: str) -> bool:
    conn = conexao()
    try:
        return conn.execute(
            "SELECT 1 FROM users WHERE username = ?", (username,)
        ).fetchone() is not None
    finally:
        conn.close()


def cliente():
    return panel.app.test_client()


def token(cli) -> str:
    """O token de CSRF nasce no primeiro render; pega-se ele da propria sessao."""
    cli.get("/login")
    with cli.session_transaction() as sess:
        return sess.get("csrf", "")


def entrar(username: str, senha: str):
    cli = cliente()
    resp = cli.post(
        "/login",
        data={"username": username, "password": senha, "csrf": token(cli)},
        follow_redirects=False,
    )
    if resp.status_code != 302:
        raise SystemExit(f"login de {username} falhou (status {resp.status_code})")
    return cli


def postar(cli, url, dados=None):
    dados = dict(dados or {})
    with cli.session_transaction() as sess:
        dados["csrf"] = sess.get("csrf", "")
    return cli.post(url, data=dados, follow_redirects=False)


# Cada teste roda com a lista de tentativas de login zerada: sao varias entradas
# seguidas do mesmo IP e o bloqueio por forca bruta dispararia no meio.
panel._login_fails.clear()

print("Bootstrap pela linha de comando")
panel.ensure_admin_user("chefe", "senha-do-chefe")
igual("usuario criado pela CLI e admin", papel("chefe"), panel.ROLE_ADMIN)
panel.ensure_admin_user("chefe", "senha-do-chefe")  # so redefine a senha
igual("redefinir senha nao mexe no papel", papel("chefe"), panel.ROLE_ADMIN)
panel.ensure_admin_user("peao", "senha-do-peao", panel.ROLE_OPERADOR)
igual("papel escolhido na CLI vale", papel("peao"), panel.ROLE_OPERADOR)


print("Operador nao chega no que da root no container")
peao = entrar("peao", "senha-do-peao")
igual("dashboard abre", peao.get("/").status_code, 200)
igual("acesso ssh abre", peao.get("/ssh-key").status_code, 200)
igual("conta abre", peao.get("/account").status_code, 200)
for rota in ("/usuarios", "/servers/new", "/servers/1/edit", "/servers/1/terminal",
             "/servers/1/console", "/servers/1/files", "/servers/1/players/descobrir"):
    igual(f"403 em {rota}", peao.get(rota).status_code, 403)
igual("nao cria usuario", postar(peao, "/usuarios",
                                 {"username": "invasor", "new": "senha12345",
                                  "confirm": "senha12345", "role": "admin"}).status_code, 403)
check("usuario nao foi criado", not existe("invasor"))
igual("nao remove servidor", postar(peao, "/servers/1/delete").status_code, 403)


print("Admin gerencia usuarios pela tela")
chefe = entrar("chefe", "senha-do-chefe")
igual("tela de usuarios abre", chefe.get("/usuarios").status_code, 200)
postar(chefe, "/usuarios", {"username": "ana", "new": "senha12345",
                            "confirm": "senha12345", "role": "operador"})
igual("usuario criado pela tela", papel("ana"), panel.ROLE_OPERADOR)

postar(chefe, "/usuarios", {"username": "bob", "new": "curta",
                            "confirm": "curta", "role": "operador"})
check("senha curta nao cria", not existe("bob"))
postar(chefe, "/usuarios", {"username": "bob", "new": "senha12345",
                            "confirm": "outra12345", "role": "operador"})
check("confirmacao errada nao cria", not existe("bob"))
postar(chefe, "/usuarios", {"username": "Bob Silva", "new": "senha12345",
                            "confirm": "senha12345", "role": "operador"})
check("nome invalido nao cria", not existe("Bob Silva"))
postar(chefe, "/usuarios", {"username": "ana", "new": "senha12345",
                            "confirm": "senha12345", "role": "admin"})
igual("nome repetido nao sobrescreve o papel de quem ja existe",
      papel("ana"), panel.ROLE_OPERADOR)

ana_id = None
conn = conexao()
ana_id = conn.execute("SELECT id FROM users WHERE username = 'ana'").fetchone()["id"]
chefe_id = conn.execute("SELECT id FROM users WHERE username = 'chefe'").fetchone()["id"]
conn.close()

postar(chefe, f"/usuarios/{ana_id}/papel", {"role": "admin"})
igual("promover funciona", papel("ana"), panel.ROLE_ADMIN)
postar(chefe, f"/usuarios/{chefe_id}/papel", {"role": "operador"})
igual("ninguem rebaixa a si mesmo", papel("chefe"), panel.ROLE_ADMIN)
postar(chefe, f"/usuarios/{ana_id}/papel", {"role": "operador"})
igual("rebaixar outro admin funciona quando sobra admin", papel("ana"), panel.ROLE_OPERADOR)

postar(chefe, f"/usuarios/{chefe_id}/remover")
check("ninguem remove a propria conta", existe("chefe"))

postar(chefe, f"/usuarios/{ana_id}/senha", {"new": "senha-nova-1", "confirm": "senha-nova-1"})
panel._login_fails.clear()
entrar("ana", "senha-nova-1")  # levanta SystemExit se a senha nao tiver valido
check("reset de senha pelo admin funciona", True)


print("Ultimo administrador nao pode sumir")
conn = conexao()
with conn:
    conn.execute("UPDATE users SET role = ? WHERE username <> 'chefe'", (panel.ROLE_OPERADOR,))
conn.close()
peao_id = None
conn = conexao()
peao_id = conn.execute("SELECT id FROM users WHERE username = 'peao'").fetchone()["id"]
conn.close()
postar(chefe, f"/usuarios/{peao_id}/papel", {"role": "admin"})
igual("promover para poder rebaixar o outro", papel("peao"), panel.ROLE_ADMIN)
postar(chefe, f"/usuarios/{peao_id}/papel", {"role": "operador"})
igual("agora rebaixa", papel("peao"), panel.ROLE_OPERADOR)
# So sobrou o chefe: ele nao pode ser removido nem por outro admin (nem por ele mesmo).
conn = conexao()
with conn:
    conn.execute("UPDATE users SET role = ? WHERE username = 'peao'", (panel.ROLE_ADMIN,))
conn.close()
panel._login_fails.clear()
peao_admin = entrar("peao", "senha-do-peao")
postar(peao_admin, f"/usuarios/{peao_id}/papel", {"role": "operador"})
postar(peao_admin, f"/usuarios/{chefe_id}/papel", {"role": "operador"})
igual("promovido enxerga a tela", peao_admin.get("/usuarios").status_code, 200)
conn = conexao()
sobraram = conn.execute(
    "SELECT COUNT(*) FROM users WHERE role = ?", (panel.ROLE_ADMIN,)
).fetchone()[0]
conn.close()
check("o painel nunca fica sem administrador", sobraram >= 1, f"(sobraram {sobraram})")


print("Sessao morre junto com a conta")
panel._login_fails.clear()
conn = conexao()
with conn:
    conn.execute("UPDATE users SET role = ? WHERE username = 'chefe'", (panel.ROLE_ADMIN,))
conn.close()
descartavel = entrar("ana", "senha-nova-1")
igual("logada, ve o painel", descartavel.get("/").status_code, 200)
chefe2 = entrar("chefe", "senha-do-chefe")
postar(chefe2, f"/usuarios/{ana_id}/remover")
check("conta removida", not existe("ana"))
igual("a sessao dela cai no proximo clique",
      descartavel.get("/").status_code, 302)


print("Historico de jobs respeita o papel")
# O job guarda a saida inteira do que rodou. Como o operador leva 403 no console e no
# editor de arquivos, ele tambem nao pode ler o RESULTADO deles — nem abrindo o job pelo
# id, nem de relance no historico da tela do servidor.
SEGREDO = "SENHA-QUE-SO-O-ADMIN-PODE-VER"
ROTINA = "acao-de-rotina-do-operador"

panel._login_fails.clear()
conn = conexao()
with conn:
    conn.execute("UPDATE users SET role = ? WHERE username = 'chefe'", (panel.ROLE_ADMIN,))
    conn.execute("UPDATE users SET role = ? WHERE username = 'peao'", (panel.ROLE_OPERADOR,))
    # Host que nao resolve: a tela do servidor tenta SSH e volta rapido com "inacessivel",
    # que e o suficiente — o que se testa aqui e o historico, nao a conexao.
    conn.execute(
        "INSERT INTO servers (name, host, ssh_port, ssh_user, service, created_at)"
        " VALUES ('alvo', 'nao-existe-de-proposito.invalid', 22, 'root', 'jogo.service', ?)",
        (panel.now_iso(),),
    )
alvo_id = conn.execute("SELECT id FROM servers WHERE name = 'alvo'").fetchone()["id"]
jobs_por_acao = {}
with conn:
    for acao in ("shell", "terminal", "edit-file", "delete-file", "download-file",
                 "start", "edit-config"):
        restrito = acao in panel.JOB_ACTIONS_ADMIN
        marca = SEGREDO if restrito else ROTINA
        cur = conn.execute(
            "INSERT INTO jobs (server_id, target, action, status, exit_code, output,"
            " command, username, created_at, finished_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (alvo_id, "root@alvo", acao, "ok", 0, marca, marca, "chefe",
             panel.now_iso(), panel.now_iso()),
        )
        jobs_por_acao[acao] = int(cur.lastrowid)
conn.close()

panel._login_fails.clear()
peao2 = entrar("peao", "senha-do-peao")
chefe3 = entrar("chefe", "senha-do-chefe")

for acao, jid in jobs_por_acao.items():
    restrito = acao in panel.JOB_ACTIONS_ADMIN
    esperado = 403 if restrito else 200
    igual(f"operador em /jobs/{acao}", peao2.get(f"/jobs/{jid}").status_code, esperado)
    igual(f"operador em /api/jobs/{acao}", peao2.get(f"/api/jobs/{jid}").status_code, esperado)
    igual(f"admin em /jobs/{acao}", chefe3.get(f"/jobs/{jid}").status_code, 200)

corpo_admin = chefe3.get(f"/jobs/{jobs_por_acao['shell']}").get_data(as_text=True)
check("admin continua lendo a saida do console", SEGREDO in corpo_admin)

detalhe = peao2.get(f"/servers/{alvo_id}")
igual("operador abre a tela do servidor", detalhe.status_code, 200)
pagina = detalhe.get_data(as_text=True)
check("o comando do console nao aparece no historico do operador", SEGREDO not in pagina)
check("o que ele pode fazer continua no historico", ROTINA in pagina)

pagina_admin = chefe3.get(f"/servers/{alvo_id}").get_data(as_text=True)
check("o historico completo continua na tela do admin", SEGREDO in pagina_admin)


print("Backup e upload seguem o mesmo corte de papel")
# Criar copia e operacao (o operador pode). Restaurar, apagar e baixar destroem dado ou
# tiram o save do container — sao de administrador, como o console e o editor.
conn = conexao()
with conn:
    conn.execute("UPDATE servers SET config_path = '/opt/game/Saved' WHERE id = ?", (alvo_id,))
alvo = conn.execute("SELECT * FROM servers WHERE id = ?", (alvo_id,)).fetchone()
conn.close()

igual("sem backup_paths, vale a pasta de configuracao",
      panel.backup_paths(alvo), ["/opt/game/Saved"])
igual("o prefixo sai da unidade systemd", panel.backup_prefix(alvo), "jogo")

conn = conexao()
with conn:
    conn.execute(
        "UPDATE servers SET backup_paths = ? WHERE id = ?",
        ("/opt/game/Saved/SaveGames\n/opt/game/config.ini", alvo_id),
    )
escolhidos = conn.execute("SELECT * FROM servers WHERE id = ?", (alvo_id,)).fetchone()
conn.close()
igual("backup_paths preenchido manda no config_path", panel.backup_paths(escolhidos),
      ["/opt/game/Saved/SaveGames", "/opt/game/config.ini"])

igual("operador ve a tela de backups", peao2.get(f"/servers/{alvo_id}/backups").status_code, 200)
igual("operador dispara o backup",
      postar(peao2, f"/servers/{alvo_id}/backups/criar").status_code, 302)
igual("operador nao restaura",
      postar(peao2, f"/servers/{alvo_id}/backups/restaurar",
             {"nome": "jogo-20260101-000000.tar.gz"}).status_code, 403)
igual("operador nao apaga copia",
      postar(peao2, f"/servers/{alvo_id}/backups/remover",
             {"nome": "jogo-20260101-000000.tar.gz"}).status_code, 403)
igual("operador nao baixa copia",
      peao2.get(f"/servers/{alvo_id}/backups/baixar?nome=jogo-20260101-000000.tar.gz").status_code,
      403)
igual("operador nao envia arquivo",
      postar(peao2, f"/servers/{alvo_id}/files/upload").status_code, 403)

# O nome do backup volta da tela e entra num comando remoto: o que nao casar com
# "<algo>.tar.gz" tem de morrer no painel, antes de chegar no shell do container.
for ruim in ("../../etc/passwd", "/etc/shadow", "x.tar.gz; rm -rf /", "sem-extensao",
             "..-..tar.gz", ""):
    igual(f"admin tambem nao passa {ruim!r}",
          postar(chefe3, f"/servers/{alvo_id}/backups/remover", {"nome": ruim}).status_code, 400)


print("Volta do login so aceita destino interno")
# "/" no comeco nao basta: para o navegador "//host" e "/\\host" sao enderecos absolutos,
# e mandariam quem acabou de digitar a senha para outro site.
for bruto in ("//evil.example.com/x", "/\\evil.example.com", "https://evil.example.com",
              "http://evil.example.com", "evil", "", "/conta\r\nSet-Cookie: x=1"):
    igual(f"recusa {bruto!r}", panel.destino_seguro(bruto), "")
for bruto in ("/servers/1/config", "/usuarios", "/"):
    igual(f"aceita {bruto!r}", panel.destino_seguro(bruto), bruto)


print()
if falhas:
    print(f"{len(falhas)} teste(s) falharam: {', '.join(falhas)}")
    raise SystemExit(1)
print("todos os testes passaram")
