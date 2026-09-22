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

    # -------------------------------------------------------- painel
    "dashboard.no_servers": "Nenhum servidor cadastrado ainda.",
    "dashboard.ssh_access": "Acesso SSH",
    "dashboard.ask_an_admin": "Peca a um administrador do painel para cadastrar o servidor.",

    # ----------------------------------------------------- historico
    "history.server": "Servidor",
    "history.any_server": "todos",
    "history.action": "Acao",
    "history.any_action": "todas",
    "history.who": "Quem",
    "history.anyone": "qualquer um",
    "history.when": "Quando",
    "history.result": "Resultado",
    "history.auto": "auto",
    "history.running": "rodando",
    "history.empty": "Nada no historico com esses filtros.",
    "history.by_scheduler": "Disparado pelo relogio do painel",

    # ----------------------------------------------------------- job
    "job.target": "Destino",
    "job.started": "Iniciado",
    "job.by": "Por",
    "job.result": "Resultado",

    # ------------------------------------------------------- offline
    "offline.title": "Sem conexao — Painel de Jogos",
    "offline.heading": "Sem conexao",
    "offline.vpn_hint": "Se voce esta fora de casa, confira se a VPN esta ligada.",
    "offline.retry": "Tentar de novo",

    # ----------------------------------------------------- chave ssh
    "ssh_key.public_key": "Chave publica do painel",
    "ssh_key.not_found": "Chave nao encontrada. Rode o deploy do painel novamente.",
    "ssh_key.authorize": "Autorizar num container de jogo",
    "ssh_key.host_keys": "Host keys",

    # ------------------------------------------------------ graficos
    "charts.no_samples": "Ainda nao ha amostras deste periodo.",
    "charts.cpu_memory": "CPU e memoria",
    "charts.no_readings": "Sem leitura de medidores neste periodo.",
    "charts.players": "Jogadores",
    "charts.peak_of": "pico de",
    "charts.in_period": "no periodo",
    "charts.as_table": "Ver os numeros em tabela",
    "charts.when": "Quando",
    "charts.cpu": "CPU",
    "charts.memory": "Memoria",
    "charts.period": "Periodo",

    # ------------------------------------------------------- backups
    "backups.what_is_saved": "O que entra na copia",
    "backups.backup_paths": "caminhos de backup",
    "backups.nothing_to_save": "Este servidor nao tem o que guardar. Preencha a",
    "backups.config_folder": "pasta de configuracao",
    "backups.or_the": "ou os",
    "backups.in_settings": "no cadastro",
    "backups.stored_copies": "Copias guardadas",
    "backups.file": "Arquivo",
    "backups.when": "Quando",
    "backups.size": "Tamanho",
    "backups.before_restore": "antes de restaurar",
    "backups.admin_only": "baixar, restaurar e apagar sao de administrador",
    "backups.none_yet": "Nenhuma copia ainda.",
    "backups.pre_restore_copy": "Tirada pelo painel logo antes de uma restauracao",

    # -------------------------------------------------- agendamentos
    "schedules.tasks_here": "Tarefas deste servidor",
    "schedules.task": "Tarefa",
    "schedules.when": "Quando",
    "schedules.next_run": "Proxima",
    "schedules.last_run": "Ultima vez",
    "schedules.off": "desligada",
    "schedules.admin_only": "so administrador altera",
    "schedules.none_here": "Nada agendado para este servidor.",
    "schedules.clock_is": "O relogio e o do",
    "schedules.panel": "painel",
    "schedules.no_late_fire": "nao dispara atrasada",
    "schedules.new_task": "Agendar uma tarefa",
    "schedules.what_to_do": "O que fazer",
    "schedules.backup": "Backup",
    "schedules.update": "Atualizar",
    "schedules.daily": "Todo dia, numa hora fixa",
    "schedules.weekly": "Uma vez por semana",
    "schedules.every_n_hours": "A cada N horas",
    "schedules.hour": "Hora",
    "schedules.minute": "Minuto",
    "schedules.weekday": "Dia da semana",
    "schedules.every": "A cada",
    "schedules.hours_from_now": "horas, contadas a partir de agora",
    "schedules.runs_show_in": "Cada disparo aparece no",
    "schedules.history": "historico",

    # ---------------------------------------------------- instancias
    "instances.new": "Nova instancia",
    "instances.game": "Jogo",
    "instances.only_installable": "So aparecem os jogos que o broker sabe instalar sozinho.",
    "instances.name": "Nome",
    "instances.none_creatable": "Nenhum jogo criavel no catalogo (ou o broker nao respondeu).",
    "instances.instance": "Instancia",
    "instances.remove": "Remover",
    "instances.type_name_to_confirm": "Digite o nome para confirmar",
    "instances.forget_record_only": "Esquecer so o registro (o container ja nao existe mais no Proxmox)",
    "instances.none_yet": "Nenhuma instancia criada pelo broker ainda.",

    # ------------------------------------------------------- console
    "console.interactive": "Sessao interativa",
    "console.single_command": "Comando unico",
    "console.commands_run_as": "Os comandos rodam como",
    "console.interactive_lower": "sessao interativa",
    "console.history_hint": "Historico: &uarr; e &darr; percorrem os comandos anteriores.",
    "console.output": "Saida",
    "console.previous_commands": "Comandos anteriores",
    "console.when": "Quando",
    "console.command": "Comando",
    "console.by": "Por",
    "console.result": "Resultado",
    "console.view": "ver",
    "console.none_yet": "Nenhum comando executado neste servidor ainda.",
    "console.terminal_mode": "Modo do terminal",

    # ------------------------------------------------------ arquivos
    "files.download": "baixar",
    "files.delete": "apagar",
    "files.empty_folder": "pasta vazia",
    "files.listing_truncated": "Listagem cortada nos primeiros itens desta pasta.",
    "files.binary": "Arquivo binario.",
    "files.read_only": "Somente leitura:",
    "files.opens_as_form": "abre este arquivo como formulario e o fixa na tela",
    "files.configuration": "Configuracao",
    "files.editor": "Editor",
    "files.any_file_downloadable": "Qualquer arquivo pode ser baixado pelo link",
    "files.config_folder_hint": "Dica: preencha a \"Pasta de configuracao\" em",
    "files.edit_server": "Editar servidor",
    "files.path_lower": "caminho",
    "files.file_to_upload": "arquivo para enviar",
    "files.path": "Caminho",

    # ------------------------------------------------- segundo fator
    "login_2fa.title": "Verificacao",
    "login_2fa.hint": "Digite o codigo de 6 digitos do aplicativo autenticador.",
    "login_2fa.code": "Codigo",
    "account_2fa.add_account": "adicionar conta",
    "account_2fa.scan_qr": "escanear codigo QR",
    "account_2fa.with_text_below": "com o texto abaixo do codigo.",
    "account_2fa.copy_key": "Copiar chave",
    "account_2fa.type": "Tipo",
    "account_2fa.time_based": "baseado em tempo",
    "account_2fa.six_digit_code": "Codigo de 6 digitos",
    "account_2fa_codes.save_them_now": "Guarde estes codigos agora.",
    "account_2fa_codes.copy_codes": "Copiar codigos",
}
