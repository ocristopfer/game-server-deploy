"""Catalogo em portugues (o idioma padrao do painel).

A chave e neutra e a mesma em todos os catalogos; ver o docstring do pacote. Chave nova
entra AQUI primeiro — e este arquivo que o teste usa como referencia para cobrar as
outras linguas.

Convencao da chave: `area.assunto`, tudo minusculo, em ingles (e identificador de
codigo, nao texto de tela).
"""
from __future__ import annotations

MENSAGENS: dict[str, str] = {
    # -------------------------------------------------------- navegacao
    "nav.servers": "Servidores",
    "nav.history": "Historico",
    "nav.alerts": "Alertas",
    "nav.account": "Conta",
    "nav.users": "Usuarios",
    "nav.instances": "Instancias",
    "nav.instances.help": "Instancias de jogo",
    "nav.catalog": "Catalogo",
    "nav.catalog.help": "Catalogo de jogos",
    "nav.add_server": "Adicionar servidor",
    "nav.ssh_key": "Acesso SSH",
    "nav.logout": "Sair",
    "nav.more": "Mais",
    "nav.main": "Navegacao principal",

    # ------------------------------------------------------------ papeis
    "role.admin": "Administrador",
    "role.operator": "Operador",

    # ------------------------------------------------ secoes do servidor
    "server.overview": "Visao geral",
    "server.overview.help": "Estado, jogadores, recursos e log",
    "server.config": "Configuracao",
    "server.config.help": "As chaves do jogo, campo a campo",
    "server.files": "Arquivos",
    "server.files.help": "Navegar, editar como texto, enviar e baixar",
    "server.charts": "Graficos",
    "server.charts.help": "CPU, memoria e jogadores ao longo do tempo",
    "server.backups": "Backups",
    "server.backups.help": "Copias do save, e como restaurar",
    "server.schedules": "Agendamentos",
    "server.schedules.help": "Reinicio e backup na hora marcada",
    "server.terminal": "Terminal",
    "server.terminal.help": "Linha de comando dentro do container",
    "server.console": "Console",
    "server.edit": "Editar",
    "server.edit.help": "Host, servico, portas e caminhos",

    # ------------------------------------------------------------ acoes
    "action.start": "Iniciar",
    "action.start.confirm": "Iniciar servidor",
    "action.stop": "Parar",
    "action.stop.confirm": "Parar servidor",
    "action.restart": "Reiniciar",
    "action.restart.confirm": "Reiniciar servidor",
    "action.update": "Atualizar",
    "action.update.confirm": "Atualizar jogo (SteamCMD)",
    "action.check_update": "Checar update",
    "action.save": "Salvar",

    # ------------------------------------------------- base e aviso de versao
    "app.name": "Painel de Jogos",
    "app.new_version": "Ha uma versao nova do painel.",
    "app.update_now": "Atualizar agora",
    "app.install": "Instalar",

    # ------------------------------------------------------------- login
    "login.title": "Entrar",
    "login.subtitle": "Entre para gerenciar os servidores.",
    "login.username": "Usuario",
    "login.password": "Senha",

    # ------------------------------------------------------------ idioma
    "account.language": "Idioma",
    "account.language.title": "Idioma da tela",
    "account.language.changed": "Idioma alterado.",
}
