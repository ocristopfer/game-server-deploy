"""Catalogo em portugues (o idioma padrao do painel).

A chave e neutra e a mesma em todos os catalogos; ver o docstring do pacote. Chave nova
entra AQUI primeiro — e este arquivo que o teste usa como referencia para cobrar as
outras linguas.

Convencao da chave: `area.assunto`, tudo minusculo, em ingles (e identificador de
codigo, nao texto de tela).
"""
from __future__ import annotations

MESSAGES: dict[str, str] = {
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

    # ------------------------------------------------------ usuarios
    "users.user": "Usuario",
    "users.role": "Papel",
    "users.created_at": "Criado em",
    "users.you": "voce",
    "users.reset_password": "Redefinir senha",
    "users.new_user": "Novo usuario",
    "users.initial_password": "Senha inicial",
    "users.confirm_password": "Confirmar senha",
    "users.password_handoff": "Voce define a senha e passa para a pessoa; ela troca depois em",
    "users.what_each_role_opens": "O que cada papel abre",
    "users.screen": "Tela",
    "users.perm_overview": "Servidores, status, jogadores, log",
    "users.yes": "sim",
    "users.no": "nao",
    "users.perm_actions": "Start / stop / restart / update",
    "users.perm_config": "Configuracao (arquivos ja registrados)",
    "users.perm_charts": "Graficos, backups e agendamentos",
    "users.perm_manage_servers": "Cadastrar / editar / remover servidor",
    "users.perm_register_config": "Registrar novo arquivo de config",
    "users.perm_terminal": "Terminal e navegador de arquivos",
    "users.two_factor_on": "Verificacao em duas etapas ativada",
    "users.new_password_lower": "nova senha",
    "users.confirm_lower": "confirmar",

    # ------------------------------------------ configuracao do jogo
    "config.edit_as_text": "editar como texto",
    "config.unpin": "tirar da lista",
    "config.found_in_container": "Arquivos de configuracao encontrados no container",
    "config.pin_here": "fixar aqui",
    "config.empty_block": "Bloco vazio &mdash; use &quot;adicionar configuracao&quot; abaixo.",
    "config.no_match": "Nenhuma configuracao com esse nome.",
    "config.add_setting": "Adicionar configuracao",
    "config.new_setting_block": "Bloco da configuracao nova",
    "config.restart_after_save": "reiniciar o servidor depois de salvar",
    "config.edit_as_text_title": "Edite como texto",
    "config.file_path": "caminho do arquivo de configuracao",
    "config.filter_placeholder": "filtrar por nome...",
    "config.filter_label": "filtrar configuracoes",
    "config.name_example": "Nome (ex.: ServerPassword)",
    "config.new_setting_name": "nome da configuracao nova",
    "config.value": "Valor",
    "config.new_setting_value": "valor da configuracao nova",

    # ------------------------------------------------------ terminal
    "terminal.ssh_session_as": "Sessao SSH interativa como",
    "terminal.starting": "iniciando...",
    "terminal.clear": "Limpar",
    "terminal.fullscreen": "Tela cheia",
    "terminal.end_session": "Encerrar",
    "terminal.reconnect": "Reconectar",
    "terminal.interrupt_sigint": "Interromper (SIGINT)",
    "terminal.eof": "Fim de entrada (EOF)",
    "terminal.suspend": "Suspender",
    "terminal.special_keys": "Teclas especiais",
    "terminal.open_keyboard": "Abrir o teclado",
    "terminal.interrupt": "Interromper",
    "terminal.arrow_up": "seta para cima",
    "terminal.arrow_down": "seta para baixo",
    "terminal.arrow_left": "seta para a esquerda",
    "terminal.arrow_right": "seta para a direita",

    # --------------------------------------------------------- conta
    "account.role": "Papel",
    "account.change_password": "Trocar senha",
    "account.current_password": "Senha atual",
    "account.new_password": "Nova senha",
    "account.min_length": "Minimo de 8 caracteres.",
    "account.confirm_new_password": "Confirmar nova senha",
    "account.two_factor": "Verificacao em duas etapas",
    "account.on": "ativada",
    "account.off": "desativada",
    "account.two_factor_on_hint": "Alem da senha, o login pede o codigo do aplicativo autenticador.",
    "account.new_recovery_codes": "Gerar codigos de recuperacao novos",
    "account.app_code": "Codigo do aplicativo",
    "account.old_codes_expire": "Os codigos antigos deixam de valer.",
    "account.disable": "Desativar",
    "account.app_or_recovery_code": "Codigo do aplicativo (ou de recuperacao)",
    "account.two_factor_required": "Este painel exige o segundo fator: nao da para desativar.",
    "account.two_factor_broker_hint": "Este painel cria e apaga containers pelo broker: ative.",
    "account.sign_out": "Sair",
    "account.sign_out_hint": "Encerra a sessao neste aparelho.",

    # ---------------------------------------------- tela do servidor
    "server_detail.host": "Host",
    "server_detail.ssh_port": "Porta SSH",
    "server_detail.service": "Servico",
    "server_detail.game_ports": "Portas do jogo",
    "server_detail.config_folder": "Pasta de config",
    "server_detail.server": "Servidor",
    "server_detail.maintenance": "Manutencao",
    "server_detail.count_off": "Contagem desligada. Use o",
    "server_detail.wizard": "assistente",
    "server_detail.published_name": "Nome publicado",
    "server_detail.world": "Mundo",
    "server_detail.online": "Online",
    "server_detail.player": "Jogador",
    "server_detail.connected_for": "Conectado ha",
    "server_detail.score": "Pontos",
    "server_detail.no_identifier": "sem identificador",
    "server_detail.count": "contagem",
    "server_detail.count_right_names_wrong": "esta certa, mas os",
    "server_detail.names": "nomes",
    "server_detail.resources": "Recursos",
    "server_detail.swap": "Swap",
    "server_detail.network": "Rede",
    "server_detail.uptime": "Uptime",
    "server_detail.game_process": "Processo do jogo",
    "server_detail.recent_actions": "Acoes recentes",
    "server_detail.no_actions_yet": "Nenhuma acao executada por aqui ainda.",
    "server_detail.service_log": "Log do servico",
    "server_detail.live": "ao vivo",
    "server_detail.follow_log": "Seguir log",
    "server_detail.lines": "linhas",
    "server_detail.broadcast": "Aviso para todo mundo no servidor",
    "server_detail.broadcast_message": "mensagem do aviso",

    # --------------------------------------------- alertas: destinos
    "alerts.destinations_on_one": "{n} destino ligado",
    "alerts.destinations_on_many": "{n} destinos ligados",
    "alerts.no_destination_on": "nenhum destino ligado",
    "alerts.intro":
        "O painel avisa por <strong>webhook</strong> quando algo acontece sem ninguem estar "
        "olhando. Cada destino tem a sua propria lista de eventos &mdash; da para mandar tudo para "
        "o canal da equipe e so as quedas para o canal geral. Serve para <strong>Discord</strong> "
        "(Editar canal &rarr; Integracoes &rarr; Webhooks &rarr; Copiar URL), "
        "<strong>Slack</strong> (Incoming Webhook) ou qualquer endereco que aceite um "
        "<code>POST</code> de JSON &mdash; a chamada leva os campos <code>content</code> e "
        "<code>text</code>, entao cada um le o seu.",
    "alerts.destinations": "Destinos",
    "alerts.no_destination_yet": "Nenhum destino cadastrado — os alertas estao desligados. Adicione o primeiro abaixo.",
    "alerts.pending_intro":
        "<strong>Ligado, mas sem onde olhar.</strong> Estes eventos nunca vao disparar do jeito "
        "que o painel esta hoje &mdash; e canal em silencio parece \"esta tudo bem\":",
    "alerts.pending_item": "<em>{event}</em>: nenhum servidor tem {missing}.",
    "alerts.pending_fix": "Ajuste no <a href=\"{url}\">cadastro de cada servidor</a>.",
    "alerts.destination_name": "Nome do destino",
    "alerts.team_channel": "Canal da equipe",
    "alerts.on": "Ligado",
    "alerts.off": "Desligado",
    "alerts.url_is_a_secret": "A URL fica escondida: e uma credencial",
    "alerts.change_url": "Trocar a URL",
    "alerts.leave_blank_to_keep": "deixe em branco para manter a atual",
    "alerts.notify_about": "Avisar sobre",
    "alerts.no_event_checked": "Sem nenhum evento marcado este destino nunca recebe nada.",
    "alerts.test": "Testar",
    "alerts.remove": "Remover",
    "alerts.remove_confirm": "Remover o destino {name}?",
    "alerts.limit_reached": "Limite de {n} destinos atingido — remova um para cadastrar outro.",
    "alerts.add_destination": "Adicionar destino",
    "alerts.name": "Nome",
    "alerts.name_hint": "So para voce se achar nesta lista.",
    "alerts.webhook_url": "URL do webhook",
    "alerts.webhook_url_hint": "E um segredo: quem a tiver escreve no seu canal.",
    "alerts.add": "Adicionar",
    "alerts.came_from_env":
        "O deploy trouxe uma URL em <code>GAMEPANEL_WEBHOOK_URL</code>; ela virou o primeiro "
        "destino desta lista e a partir daqui so vale o que estiver cadastrado.",

    # ----------------------------------------- alertas: preferencias
    "alerts.preferences": "Preferencias",
    "alerts.warn_disk_over": "Avisar quando o disco passar de",
    "alerts.disk_hint":
        "No disco mais cheio do container. Avisa uma vez, na virada: um disco a 95% continua a 95% "
        "na volta seguinte e ninguem merece o mesmo alerta a cada minuto.",
    "alerts.warn_memory_over": "Avisar quando a memoria passar de",
    "alerts.memory_hint":
        "Memoria do container, contra o limite dele (nao o da maquina inteira). Avisa uma vez, na "
        "virada, do mesmo jeito que o disco.",
    "alerts.warn_cpu_over": "Avisar quando a CPU passar de",
    "alerts.cpu_hint":
        "Uso do container sobre os nucleos que ele tem, medido junto com o disco (a cada {n} min). "
        "Como e uma amostra curta de vez em quando, serve para pegar CPU presa no teto, nao pico "
        "de um segundo.",

    # ----------------------------------------------- alertas: diario
    "alerts.journal": "Diario de alertas",
    "alerts.journal_empty":
        "Nada registrado ainda. Cada alerta que o painel decidir mandar aparece aqui &mdash; "
        "inclusive os que <strong>nao</strong> sairam.",
    "alerts.when_utc": "Quando (UTC)",
    "alerts.event": "Evento",
    "alerts.what": "O que",
    "alerts.destination": "Destino",
    "alerts.outcome": "Saida",
    "alerts.sent": "enviado",
    "alerts.failed": "falhou",
    "alerts.no_destination": "sem destino",
    "alerts.internal_error": "erro interno",
    "alerts.journal_legend":
        "<strong>sem destino</strong> quer dizer que o alerta aconteceu de verdade e nenhum "
        "destino ativo tinha esse evento marcado &mdash; o canal fica mudo por escolha, nao por "
        "defeito. <strong>erro interno</strong> e uma tarefa do relogio que quebrou: enquanto ela "
        "aparecer aqui, os alertas dela nao estao sendo checados.",

    # ---------------------------------------- alertas: como funciona
    "alerts.how_it_works": "Como funciona",
    "alerts.rule_rhythm":
        "O painel confere o estado de cada servidor a cada <strong>{monitor}s</strong> e disco, "
        "memoria e CPU a cada <strong>{meter} min</strong> (o medidor custa bem mais caro que o "
        "status, e as tres leituras saem de uma vez so).",
    "alerts.rule_joining":
        "<strong>Jogador entrando e a excecao:</strong> esse o painel confere a cada "
        "<strong>{n}s</strong>, porque quem recebe o aviso costuma querer entrar junto e um minuto "
        "depois ja e tarde. Essa volta curta pergunta direto ao jogo, sem SSH &mdash; por isso ela "
        "cabe sem encarecer o resto. Vale para quem conta por <strong>A2S ou API HTTP</strong>.",
    "alerts.streams_now": "<strong>{n}</strong> agora",
    "alerts.streams_none": "nenhuma no momento",
    "alerts.rule_log_listen":
        "Quem conta por <strong>log</strong> nao e perguntado: o painel deixa uma conexao aberta "
        "<em>ouvindo</em> o log ({listening}) e reage a linha no segundo em que ela sai. Perguntar "
        "de 15 em 15 segundos custaria uma leitura do log inteiro a cada vez; assim so se le "
        "quando alguem de fato entrou ou saiu. Se a conexao cair, o aviso volta a sair pela volta "
        "de {monitor}s ate ela se restabelecer.",
    "alerts.rule_on_change":
        "Ele avisa na <strong>mudanca</strong>, nunca em repeticao: o alerta sai quando o servidor "
        "cai, nao a cada volta enquanto ele estiver caido.",
    "alerts.rule_all_destinations":
        "Cada evento vai para <strong>todos os destinos</strong> que o marcaram. Um destino fora "
        "do ar nao impede os outros de receber.",
    "alerts.rule_service_up_is_not_game_up":
        "<strong>Servico de pe nao quer dizer jogo de pe.</strong> Alem da queda, o painel olha "
        "tres coisas que passariam batido:",
    "alerts.rule_game_failed":
        "<em>Jogo quebrou</em> &mdash; o systemd marcou o servico como <code>failed</code>. E "
        "diferente de \"parou\": alguem parar pelo painel nao gera este alerta, e este aqui sai "
        "mesmo dentro da janela de silencio.",
    "alerts.rule_restart_loop":
        "<em>Loop de restart</em> &mdash; o jogo morre e o systemd levanta de novo, sem parar. "
        "Entre uma queda e outra o servico responde <code>active</code>, e o alerta de queda nunca "
        "dispara. Sai uma vez por episodio.",
    "alerts.rule_game_mute":
        "<em>Jogo nao responde</em> &mdash; o processo esta vivo mas mudo na consulta do proprio "
        "jogo, por {n} verificacoes seguidas. So vale para quem conta jogadores por <strong>A2S ou "
        "API HTTP</strong>: contagem por log nao pergunta nada ao jogo.",
    "alerts.rule_log_error":
        "<em>Erro no log do jogo</em> le o fim do log a cada <strong>{n}s</strong> e procura a "
        "expressao cadastrada em cada servidor. Sem expressao, nem a leitura acontece. A mesma "
        "linha nao avisa duas vezes.",
    "alerts.rule_quiet_window":
        "Parar, reiniciar, atualizar ou restaurar <strong>pelo painel</strong> nao vira alerta "
        "&mdash; nos {n}s seguintes a uma dessas acoes a queda e esperada.",
    "alerts.rule_on_boot":
        "Ao subir, o painel so <strong>anota</strong> o estado de todo mundo. Reiniciar o painel "
        "nao dispara um alerta por servidor que ja estava parado.",
    "alerts.rule_scheduled_only":
        "De tarefa que falha, so a <strong>agendada</strong> vira alerta: quem clicou o botao ja "
        "esta com o erro na tela.",
    "alerts.rule_editing_resets":
        "Mexer nesta tela zera a linha de base do monitor, para a volta seguinte nao avisar sobre "
        "o que ja estava assim antes da mudanca.",

    # --------------------------------------------- catalogo de jogos
    "catalog.title": "Catalogo de jogos",
    "catalog.game": "Jogo",
    "catalog.creatable": "criavel",
    "catalog.manual": "manual",
    "catalog.ports": "Portas",
    "catalog.shifted_port": "porta sorteada",
    "catalog.shifted_port_help":
        "O broker sorteia as portas numa faixa propria dele; as listadas aqui sao so as padrao do "
        "jogo",
    "catalog.empty": "Catalogo vazio (ou o broker nao respondeu).",
    "catalog.curated_vs_dynamic":
        "<strong>curado</strong>: vem dos arquivos <code>games/*.env</code> do repositorio. "
        "<strong>dinamico</strong>: adicionado por aqui. Jogo que exige conta Steam ou instalador "
        "proprio (TeamSpeak) continua sendo criado pelo <code>deploy-game.ps1</code>.",
    "catalog.add_game": "Adicionar jogo",
    "catalog.data_only":
        "So dados: o broker <strong>nao aceita comandos</strong>. O que precisa de instalacao "
        "especial (Wine, Proton, symlink do Steam) entra pelas receitas abaixo.",
    "catalog.search_game": "Buscar jogo",
    "catalog.by_name_or_app_id": "(nome ou App ID)",
    "catalog.search_hint":
        "Preenche App ID, portas e comando de start a partir do catalogo do LinuxGSM. E so "
        "sugestao: confira antes de enviar.",
    "catalog.start_from_template": "Comecar de um modelo",
    "catalog.blank": "Em branco",
    "catalog.template_hint": "Preenche portas, caminhos, argumentos e o padrao do log de uma vez.",
    "catalog.key": "Chave",
    "catalog.key_example": "meujogo",
    "catalog.key_hint": "Minusculas, numeros e hifen. Vira o nome do container e do servico.",
    "catalog.name": "Nome",
    "catalog.name_example": "Meu Jogo",
    "catalog.app_id": "App ID do servidor dedicado (Steam)",
    "catalog.app_id_hint": "O do <strong>servidor dedicado</strong>, nao o do jogo. Consulte o SteamDB.",
    "catalog.ports_hint": "Porta/protocolo, separadas por espaco. Abaixo de 1024 nao e permitido.",
    "catalog.game_port": "Porta do jogo",
    "catalog.query_port": "Porta de consulta",
    "catalog.extra_port": "Porta extra",
    "catalog.optional": "(opcional)",
    "catalog.start_script": "Script de start",
    "catalog.start_args": "Argumentos",
    "catalog.start_args_hint":
        "Use <code>{PORT}</code>, <code>{QUERY_PORT}</code> e <code>{EXTRA_PORT}</code>. Nada de "
        "<code>; | &amp; $</code>.",
    "catalog.memory_mb": "Memoria (MB)",
    "catalog.cpus": "CPUs",
    "catalog.disk_gb": "Disco (GB)",
    "catalog.config_folder": "Pasta de configuracao",
    "catalog.config_folder_hint": "Caminho absoluto sob <code>/opt/game</code> ou <code>/home/steam</code>.",
    "catalog.config_files": "Arquivos de configuracao",
    "catalog.one_per_line": "(um por linha)",
    "catalog.one_per_line_f": "(uma por linha)",
    "catalog.backup_paths": "Pastas de backup",
    "catalog.player_count": "Contagem de jogadores",
    "catalog.by_server_log": "Pelo log do servidor",
    "catalog.by_steam_query": "Consulta Steam (A2S)",
    "catalog.platform": "Plataforma",
    "catalog.linux_default": "Linux (padrao)",
    "catalog.windows_needs_wine": "Windows (exige Wine ou Proton)",
    "catalog.log_join_line": "Log: linha de entrada",
    "catalog.log_leave_line": "Log: linha de saida",
    "catalog.install_recipes": "Receitas de instalacao",
    "catalog.broker_picks_ports": "O broker sorteia as portas (varias instancias do mesmo jogo)",
    "catalog.broker_picks_ports_hint":
        "So marque se o jogo aceita as portas pelos argumentos: os argumentos de start precisam "
        "ter {PORT} (e {QUERY_PORT} e {EXTRA_PORT}, se houver porta de consulta e porta extra) e o "
        "jogo so pode ter essas tres portas.",
    "catalog.add_to_catalog": "Adicionar ao catalogo",

    # ------------------------------------------ cadastro de servidor
    "server_form.title_new": "Adicionar servidor",
    "server_form.title_edit": "Editar servidor",
    "server_form.optional": "(opcional)",
    "server_form.one_per_line": "(um por linha)",
    "server_form.one_per_line_optional": "(um por linha, opcional)",
    "server_form.name": "Nome",
    "server_form.name_hint": "Como o servidor aparece no painel. Ex.: <code>Dragonwilds</code>",
    "server_form.host": "Host",
    "server_form.host_hint": "IP ou hostname do container do jogo. O painel se conecta nele por SSH.",
    "server_form.ssh_user": "Usuario SSH",
    "server_form.ssh_port": "Porta SSH",
    "server_form.systemd_service": "Servico systemd",
    "server_form.service_hint":
        "Normalmente <code>&lt;nome-do-jogo&gt;.service</code>. O <code>.service</code> e "
        "adicionado se faltar.",
    "server_form.game_ports": "Portas do jogo",
    "server_form.game_ports_hint": "Apenas informativo, para lembrar o que redirecionar no roteador.",
    "server_form.query_port": "Porta de consulta",
    "server_form.query_port_hint": "Porta de query Steam (A2S). Palworld: <code>27015</code>.",
    "server_form.player_count": "Contagem de jogadores",
    "server_form.count_off": "Desligada",
    "server_form.count_a2s": "Consulta Steam (A2S) na porta acima",
    "server_form.count_http": "API HTTP do jogo (da os nomes)",
    "server_form.count_log": "Pelo log do servidor",
    "server_form.player_count_hint":
        "Jogo que nao publica nada na rede (RuneScape Dragonwilds, por exemplo) so da para contar "
        "pelo log.",
    "server_form.player_count_wizard":
        "O <a href=\"{url}\">assistente</a> testa as portas UDP e TCP, monta a chamada da API e "
        "acha os padroes do log para voce.",
    "server_form.log_join": "Log: linha de entrada",
    "server_form.log_leave": "Log: linha de saida",
    "server_form.log_file": "Log: arquivo",
    "server_form.log_file_hint":
        "Em branco le a saida do servico. Preenchido, le esse arquivo &mdash; e como se alcanca o "
        "nome do jogador em jogos que so o escrevem em log proprio (DayZ).",
    "server_form.log_error": "Log: linha de erro",
    "server_form.log_error_hint":
        "Liga o alerta <strong>Erro no log do jogo</strong> em <a href=\"{url}\">Alertas</a>: o "
        "painel procura esta expressao no fim do log e avisa quando ela aparece. Em branco, nem a "
        "leitura acontece. Comece estreito &mdash; um padrao largo demais transforma o canal em "
        "copia do log.",
    "server_form.api_url": "API: URL",
    "server_form.api_url_hint": "Chamada de dentro do container, por SSH. Palworld: porta <code>8212</code>.",
    "server_form.api_auth": "API: autenticacao",
    "server_form.api_auth_hint":
        "<code>basic:usuario:senha</code>, <code>bearer:token</code> ou <code>header:Nome: "
        "valor</code> (TeamSpeak: <code>header:x-api-key: SUA-CHAVE</code>). Fica em texto puro no "
        "banco.",
    "server_form.api_body": "API: corpo JSON",
    "server_form.api_body_hint": "Preenchido vira <code>POST</code>; vazio e <code>GET</code>.",
    "server_form.api_paths": "API: caminho da lista / da contagem",
    "server_form.api_paths_hint": "Vazios: o painel procura sozinho na resposta.",
    "server_form.config_folder": "Pasta de configuracao",
    "server_form.config_folder_hint":
        "Onde a tela <strong>Arquivos</strong> abre por padrao. Ex.: "
        "<code>/opt/game/Pal/Saved/Config/LinuxServer</code>",
    "server_form.config_files": "Arquivos de configuracao",
    "server_form.config_files_hint":
        "Informe aqui o arquivo que voce edita de verdade: a tela <strong>Config</strong> abre ele "
        "direto como formulario (um campo por chave, com botao para acrescentar chave nova) "
        "&mdash; sem navegar por pastas. Em branco, a propria tela ajuda a procurar os candidatos "
        "no container.",
    "server_form.config_files_hint_link":
        "Informe aqui o arquivo que voce edita de verdade: a tela <a "
        "href=\"{url}\"><strong>Config</strong></a> abre ele direto como formulario (um campo por "
        "chave, com botao para acrescentar chave nova) &mdash; sem navegar por pastas. Em branco, "
        "a propria tela ajuda a procurar os candidatos no container.",
    "server_form.backup_paths": "Caminhos de backup",
    "server_form.backup_paths_hint":
        "O que a tela <strong>Backups</strong> guarda no <code>.tar.gz</code>. Em branco vale a "
        "<strong>pasta de configuracao</strong> acima. Aponte a pasta do <strong>save</strong>, "
        "nao a raiz do jogo: <code>/opt/game</code> inteiro leva dezenas de GB de binario que o "
        "SteamCMD rebaixa de graca.",
    "server_form.backup_paths_hint_link":
        "O que a tela <a href=\"{url}\"><strong>Backups</strong></a> guarda no "
        "<code>.tar.gz</code>. Em branco vale a <strong>pasta de configuracao</strong> acima. "
        "Aponte a pasta do <strong>save</strong>, nao a raiz do jogo: <code>/opt/game</code> "
        "inteiro leva dezenas de GB de binario que o SteamCMD rebaixa de graca.",
    "server_form.notes": "Notas",
    "server_form.cancel": "Cancelar",
    "server_form.sshd_note":
        "O container precisa ter <code>sshd</code> rodando e a chave do painel autorizada — veja "
        "<a href=\"{url}\">Acesso SSH</a>.",
    "server_form.remove": "Remover do painel",
    "server_form.remove_hint": "Apaga apenas o cadastro. O container e os arquivos do jogo nao sao tocados.",
    "server_form.remove_confirm": "Remover este servidor do painel?",

    # ------------------------------------------ titulos e componente
    "error.title": "Erro {code}",
    "job.title": "Acao #{id}",
    "account_2fa_codes.title": "Codigos de recuperacao",
    "players_setup.title": "Contagem de jogadores",
    "server.sections_of_this_server": "Telas deste servidor",
    "server.measuring": "medindo recursos...",
    "server.server": "Servidor",

    # -------------------------------- rotulos de botao e confirmacao
    "account.generate": "Gerar",
    "account.enable": "Ativar",
    "account.disable_confirm": "Desativar a verificacao em duas etapas? O login volta a pedir so a senha.",
    "account.sign_out_of_panel": "Sair do painel",
    "account_2fa.open_in_app": "Abrir no aplicativo",
    "account_2fa_codes.saved_them": "Ja guardei",
    "backups.back_up_now": "Fazer backup agora",
    "backups.restore": "restaurar",
    "backups.restore_confirm":
        "Restaurar {file} em {server}?\n\nO servidor sera PARADO, os arquivos de agora serao "
        "substituidos e ele volta a subir. Uma copia do estado atual e guardada antes.",
    "backups.delete_confirm": "Apagar {file}? Nao tem volta.",
    "config.use_this_file": "Usar este arquivo",
    "config.search_container": "Procurar no container",
    "config.another_line": "outra linha",
    "console.run": "Executar",
    "dashboard.add_the_first": "Adicionar o primeiro",
    "error.back_to_panel": "Voltar ao painel",
    "files.go": "Ir",
    "files.upload_here": "Enviar para esta pasta",
    "files.discard": "Descartar",
    "files.download_title": "Baixar",
    "files.edit_field_by_field": "Editar campo a campo",
    "files.delete_file": "Apagar arquivo",
    "files.delete_confirm": "Apagar {path}? Isto nao tem volta.",
    "history.filter": "Filtrar",
    "history.clear": "limpar",
    "history.newer": "mais recentes",
    "history.older": "mais antigas",
    "instances.create": "Criar instancia",
    "instances.create_confirm":
        "Criar o container, instalar o jogo e abrir as portas no firewall? Isso pode levar varios "
        "minutos.",
    "instances.deactivate_confirm": "Desativar {name}? O servidor sera PARADO e as portas fecham no firewall.",
    "instances.remove_confirm": "Remover {name}? O container e o jogo serao APAGADOS.",
    "login_2fa.confirm": "Confirmar",
    "login_2fa.back": "Voltar",
    "schedules.run_now": "rodar agora",
    "schedules.run_now_help": "Roda agora, sem esperar a hora",
    "schedules.turn_on": "ligar",
    "schedules.turn_off": "desligar",
    "schedules.delete": "remover",
    "schedules.delete_confirm": "Remover: {task}?",
    "schedules.schedule_it": "Agendar",
    "schedules.never": "nunca",
    "server_detail.configure": "Configurar",
    "server_detail.how_counting_works": "Como o painel conta os jogadores deste servidor",
    "server_detail.announce": "Avisar",
    "server_detail.reload": "Recarregar",
    "users.change": "Trocar",
    "users.two_factor_off": "Desligar 2FA",
    "users.two_factor_off_confirm":
        "Desligar a verificacao em duas etapas de {user}? Ele entra so com a senha ate ativar "
        "de novo.",
    "users.remove_confirm": "Remover o usuario {user}?",
    "users.create": "Criar",

    # ---------------------------------------- contagem de jogadores
    "players_setup.intro":
        "Tres formas de saber quantos estao jogando, da melhor para a ultima: a <strong>API do "
        "jogo</strong> (da os nomes), a <strong>consulta direta</strong> que o navegador de "
        "servidores usa (da a contagem) e, quando o jogo nao publica nada na rede, o <strong>log "
        "do servidor</strong>.",
    "players_setup.how_to_count": "Como contar",
    "players_setup.tab_udp": "1. Consulta direta (UDP)",
    "players_setup.tab_http": "2. API HTTP (TCP)",
    "players_setup.tab_log": "3. Pelo log",
    "players_setup.ports_tested": "Portas testadas",
    "players_setup.ports_tested_hint":
        "O painel leu de <code>/proc</code> quais portas UDP estao abertas dentro do container e "
        "<strong>qual processo abriu cada uma</strong>, e mandou um <code>A2S_INFO</code> em "
        "todas. As detectadas vem primeiro; as marcadas como <em>chute</em> nao estavam abertas e "
        "so servem para quando o servidor esta parado.",
    "players_setup.port": "Porta",
    "players_setup.opened_by": "Aberta por",
    "players_setup.answer": "Resposta",
    "players_setup.server": "Servidor",
    "players_setup.address": "Endereco",
    "players_setup.status": "Status",
    "players_setup.kind": "Tipo",
    "players_setup.infra_not_the_game": "infra, nao e o jogo",
    "players_setup.open_no_owner": "aberta, sem processo dono neste container",
    "players_setup.was_not_open": "nao estava aberta (chute)",
    "players_setup.no_answer": "sem resposta",
    "players_setup.use_this": "Usar esta",
    "players_setup.no_port_to_test": "Nenhuma porta para testar.",
    "players_setup.no_udp_query_one":
        "<strong>Este jogo nao publica consulta UDP.</strong> O processo do servidor abriu {n} "
        "porta UDP e ela nao respondeu ao <code>A2S_INFO</code> &mdash; nao e porta errada nem "
        "firewall: e porta do proprio jogo, e ela nao fala o protocolo. A contagem que aparece no "
        "navegador do jogo, quando existe, vem do servico da Steam/Epic e nao do servidor. Confira "
        "a aba <a href=\"{url_http}\">API HTTP</a> (varios jogos trocaram a query UDP por uma API "
        "em TCP) e, se ali tambem nao houver nada, a contagem so pode sair do <a "
        "href=\"{url_log}\">log</a>.",
    "players_setup.no_udp_query_many":
        "<strong>Este jogo nao publica consulta UDP.</strong> O processo do servidor abriu {n} "
        "portas UDP e nenhuma respondeu ao <code>A2S_INFO</code> &mdash; nao e porta errada nem "
        "firewall: sao as portas do proprio jogo, e elas nao falam o protocolo. A contagem que "
        "aparece no navegador do jogo, quando existe, vem do servico da Steam/Epic e nao do "
        "servidor. Confira a aba <a href=\"{url_http}\">API HTTP</a> (varios jogos trocaram a "
        "query UDP por uma API em TCP) e, se ali tambem nao houver nada, a contagem so pode sair "
        "do <a href=\"{url_log}\">log</a>.",
    "players_setup.none_answered":
        "Nenhuma respondeu? Veja a aba <a href=\"{url}\">API HTTP</a> &mdash; varios jogos "
        "trocaram a query UDP por uma API de administracao em TCP.",
    "players_setup.tcp_answered_http": "Portas TCP que responderam HTTP",
    "players_setup.tcp_hint":
        "O painel leu de <code>/proc</code> as portas TCP em <code>LISTEN</code> dentro do "
        "container e <strong>qual processo abriu cada uma</strong>, e bateu nelas por HTTP "
        "<strong>de dentro do proprio container</strong> &mdash; essas APIs costumam escutar so em "
        "<code>127.0.0.1</code>, e e assim que elas devem continuar. Um <code>401</code> tambem e "
        "um bom sinal: existe API ali, ela so quer senha. Confira a coluna &quot;Aberta por&quot;: "
        "se nao for o processo do jogo, nao e a API dele.",
    "players_setup.same_on_everything": "{status} em tudo",
    "players_setup.asks_for_password": "{status} pede senha",
    "players_setup.http_but_not_a_game_api": "fala HTTP, mas nao e API de jogo",
    "players_setup.use_this_url": "Usar esta URL",
    "players_setup.no_tcp_answered_http": "Nenhuma porta TCP respondeu HTTP.",
    "players_setup.no_http_answer_on": "Sem resposta HTTP em:",
    "players_setup.no_game_api":
        "<strong>Nenhuma API de jogo respondeu.</strong> Quase sempre e porque ela vem "
        "<em>desligada</em> de fabrica e precisa ser ligada na configuracao do servidor &mdash; a "
        "porta so passa a existir depois disso. No <strong>Palworld</strong>, no "
        "<code>PalWorldSettings.ini</code> (dentro de <code>OptionSettings=(...)</code>): "
        "<code>RESTAPIEnabled=True</code>, <code>RESTAPIPort=8212</code> e uma "
        "<code>AdminPassword</code> forte. Pare o servidor, edite, suba de novo e recarregue esta "
        "pagina. Se o jogo simplesmente nao tem API (RuneScape Dragonwilds nao tem), use a aba <a "
        "href=\"{url}\">Pelo log</a>.",
    "players_setup.test_the_call": "Testar a chamada",
    "players_setup.url": "URL",
    "players_setup.url_hint":
        "Sempre <code>127.0.0.1</code>: a chamada sai de dentro do container, pelo mesmo SSH do "
        "resto do painel. Nao precisa abrir nada no roteador.",
    "players_setup.auth": "Autenticacao",
    "players_setup.auth_hint":
        "<code>basic:usuario:senha</code>, <code>bearer:token</code> ou um cabecalho "
        "<code>Authorization</code> pronto. Palworld: <code>basic:admin:</code> + a "
        "<code>AdminPassword</code> do <code>PalWorldSettings.ini</code>. Para API que autentica "
        "por outro cabecalho, use <code>header:Nome: valor</code> &mdash; o TeamSpeak pede "
        "<code>header:x-api-key: SUA-CHAVE</code>.",
    "players_setup.json_body": "Corpo JSON",
    "players_setup.json_body_hint": "Preenchido, a chamada vira <code>POST</code>. Vazio, e um <code>GET</code>.",
    "players_setup.list_path": "Caminho da lista",
    "players_setup.count_path": "Caminho da contagem",
    "players_setup.auto_login": "Login automatico",
    "players_setup.auto_login_hint":
        "Para APIs cujo token <strong>expira</strong> — a do Satisfactory e assim. Preenchendo "
        "estes tres campos, o painel troca a senha por um token sozinho, guarda, e quando a API "
        "responder <code>401</code> ele refaz o login e repete a consulta. Deixe a "
        "<em>Autenticacao</em> acima vazia: quem manda o cabecalho passa a ser o token obtido "
        "aqui.",
    "players_setup.login_url": "URL de login",
    "players_setup.token_path": "Caminho do token",
    "players_setup.login_json_body": "Corpo JSON do login",
    "players_setup.login_json_body_hint":
        "Satisfactory: a senha e a de <strong>admin</strong> definida no cliente ao reivindicar o "
        "servidor. O corpo vai para a mesma API, sem cabecalho de autenticacao.",
    "players_setup.leave_paths_empty":
        "Deixe os dois caminhos vazios primeiro: o painel procura sozinho uma lista de jogadores "
        "e, se nao achar, um numero em chaves conhecidas (<code>currentplayernum</code>, "
        "<code>numPlayers</code>, ...). So preencha se ele errar &mdash; a resposta crua aparece "
        "abaixo para voce ver o nome certo do campo.",
    "players_setup.test": "Testar",
    "players_setup.result": "Resultado:",
    "players_setup.players_count": "jogador(es)",
    "players_setup.players_online_now": "jogador(es) online agora",
    "players_setup.raw_api_answer": "Resposta crua da API",
    "players_setup.use_this_api": "Usar esta API",
    "players_setup.password_in_plain_text":
        "A senha da API fica guardada no banco do painel em texto puro (e ela precisa ir no "
        "cabecalho de cada chamada). Trate <code>panel.db</code> como segredo.",
    "players_setup.log_lines_that_look_like": "Linhas do log que parecem de entrada/saida",
    "players_setup.find_the_lines":
        "Ache a linha que aparece quando alguem entra e a que aparece quando alguem sai, e escreva "
        "os padroes abaixo. Use <code>(?P&lt;name&gt;.+)</code> onde estiver o nome do jogador "
        "&mdash; com o nome nos dois padroes o painel lista quem esta online; sem ele, mostra so a "
        "contagem.",
    "players_setup.no_join_leave_lines": "Nenhuma linha com palavras de entrada/saida no log desta execucao.",
    "players_setup.test_the_pattern": "Testar o padrao",
    "players_setup.log_file": "Arquivo de log",
    "players_setup.log_file_hint":
        "Em branco, o painel le a saida do servico (<code>journalctl</code>) &mdash; e onde a "
        "maioria dos jogos anuncia. Alguns so escrevem o <strong>nome</strong> de quem entra num "
        "arquivo proprio: o <strong>DayZ</strong> e assim (<code>/opt/game/profiles/*.ADM</code>, "
        "ja ligado pelo <code>-adminlog</code> do nosso deploy). O <code>*</code> vale, e o painel "
        "pega sempre o arquivo mais novo.",
    "players_setup.join_line": "Linha de entrada",
    "players_setup.leave_line": "Linha de saida",
    "players_setup.last_matching_lines": "Ultimas linhas que casaram com os padroes:",
    "players_setup.no_line_matched": "Nenhuma linha casou com os padroes — confira a grafia.",
    "players_setup.use_these_patterns": "Usar estes padroes",

    # --------------------------------------------- eventos de alerta
    "event.server_stopped": "Servidor parou de rodar",
    "event.server_back": "Servidor voltou a rodar",
    "event.game_failed": "Jogo quebrou (servico em 'failed')",
    "event.restart_loop": "Jogo caindo em loop de restart",
    "event.game_mute": "Jogo nao responde (de pe, mas mudo)",
    "event.game_answering": "Jogo voltou a responder",
    "event.player_joined": "Jogador conectou",
    "event.player_left": "Jogador desconectou",
    "event.log_error": "Erro no log do jogo",
    "event.lost_contact": "Painel perdeu contato (SSH)",
    "event.contact_back": "Contato restabelecido",
    "event.scheduled_task_failed": "Tarefa agendada falhou",
    "event.disk_almost_full": "Disco quase cheio",
    "event.memory_almost_full": "Memoria quase cheia",
    "event.cpu_high": "Uso de CPU alto",

    # ----------------------------------- nome das acoes no historico
    "job.shell": "Comando no container",
    "job.terminal": "Terminal interativo",
    "job.file_saved": "Arquivo salvo",
    "job.file_deleted": "Arquivo apagado",
    "job.config_changed": "Configuracao alterada",
    "job.file_downloaded": "Arquivo baixado",
    "job.file_uploaded": "Arquivo enviado",
    "job.backup": "Backup",
    "job.backup_restored": "Backup restaurado",
    "job.backup_deleted": "Backup apagado",
    "job.player_action": "Acao sobre jogador",
    "job.instance_created": "Instancia criada (broker)",
    "job.instance_deactivated": "Instancia desativada (broker)",
    "job.instance_removed": "Instancia removida (broker)",
    "player_action.announce": "Avisar todo mundo",
    "player_action.kick": "Expulsar",
    "player_action.ban": "Banir",

    # ---------------------------------------- mensagens de flash
    "flash.two_factor_required_here": "Este painel exige a verificacao em duas etapas: ative-a para continuar.",
    "flash.too_many_tries": "Muitas tentativas. Tente de novo em {n}s.",
    "flash.bad_credentials": "Usuario ou senha invalidos.",
    "flash.verification_expired": "A verificacao expirou. Entre de novo.",
    "flash.code_invalid_or_used": "Codigo invalido ou ja usado.",
    "flash.bad_port": "Porta invalida.",
    "flash.count_on_by_query": "Contagem de jogadores ligada pela consulta na porta {port}/udp.",
    "flash.need_api_url": "Informe a URL da API.",
    "flash.count_on_by_api_login": "Contagem ligada pela API, com login automatico (o token renova sozinho).",
    "flash.count_on_by_api": "Contagem de jogadores ligada pela API HTTP do servidor.",
    "flash.need_join_pattern": "Informe o padrao da linha de entrada.",
    "flash.count_on_by_log": "Contagem de jogadores ligada pelo log do servidor.",
    "flash.bad_choice": "Escolha invalida.",
    "flash.could_not": "Nao consegui: {reason}",
    "flash.player_action_done": "{label}: {who}.",
    "flash.notice_sent": "Aviso enviado: {message}",
    "flash.server_added": "Servidor {name} cadastrado.",
    "flash.server_updated": "Servidor atualizado.",
    "flash.server_removed": "Servidor removido do painel (o container nao foi tocado).",
    "flash.type_a_command": "Digite um comando.",
    "flash.command_too_long": "Comando muito longo (limite de {n} caracteres).",
    "flash.file_too_big": "Arquivo grande demais para salvar (limite de {kb} KB).",
    "flash.file_over_edit_limit":
        "{path} tem {size} KB e passou do limite de edicao ({kb} KB). Nada foi gravado — baixe o "
        "arquivo para mexer nele.",
    "flash.file_saved": "{path} salvo ({bytes} bytes). Uma copia .bak foi guardada ao lado.",
    "flash.is_a_root_folder": "{path} e uma pasta raiz do editor — nao da para apagar por aqui.",
    "flash.deleted_no_bak": "{output} (sem copia .bak — apagar nao tem volta).",
    "flash.also_left_config": "{path} tambem saiu dos arquivos da tela Config.",
    "flash.could_not_delete": "Nao consegui apagar: {reason}",
    "flash.pick_a_file": "Escolha um arquivo para enviar.",
    "flash.bad_file_name": "Nome de arquivo invalido.",
    "flash.could_not_upload": "Nao consegui enviar: {reason}",
    "flash.uploaded": "{output}. Se o arquivo ja existia, uma copia .bak ficou ao lado.",
    "flash.nothing_to_back_up":
        "Este servidor nao tem o que guardar: preencha a pasta de configuracao ou os caminhos de "
        "backup no cadastro.",
    "flash.left_config_screen": "{path} saiu da tela de configuracao (o arquivo nao foi tocado).",
    "flash.config_files_limit": "Limite de {n} arquivos por servidor.",
    "flash.now_opens_in_config": "{path} agora abre direto na tela Config.",
    "flash.value_out_of_range": "Nao salvei nada porque ha valor fora do limite - {errors}",
    "flash.no_field_changed": "Nenhum campo foi alterado.",
    "flash.could_not_save": "Nao consegui salvar: {reason}",
    "flash.settings_saved":
        "{n} configuracao(oes) salva(s) em {path}: {keys}. Uma copia .bak foi guardada ao "
        "lado.",
    "flash.broker_needs_two_factor":
        "O broker so pode ser usado por quem tem a verificacao em duas etapas ativa: ative-a em "
        "Conta.",
    "flash.broker_error": "Broker: {reason}",
    "flash.game_added": "Jogo {name} adicionado ao catalogo.",
    "flash.broker_no_operation_id": "Broker: resposta sem identificador de operacao.",
    "flash.instance_deactivated": "Instancia desativada: portas fechadas e container parado.",
    "flash.instance_removed": "Instancia removida.",
    "flash.task_scheduled": "{task} agendado.",
    "flash.task_off": "Tarefa desligada.",
    "flash.task_on": "Tarefa ligada.",
    "flash.task_removed": "Tarefa removida.",
    "flash.could_not_trigger": "Nao consegui disparar (servidor sem caminhos de backup?).",
    "flash.wrong_current_password": "Senha atual incorreta.",
    "flash.password_changed": "Senha alterada.",
    "flash.wrong_code": "Codigo incorreto. Confira o horario do celular e tente de novo.",
    "flash.two_factor_on": "Verificacao em duas etapas ativada.",
    "flash.two_factor_off": "Verificacao em duas etapas desativada.",
    "flash.new_codes": "Codigos novos gerados: os antigos deixaram de valer.",
    "flash.threshold_range": "O aviso de {name} vale de 50% a 100%.",
    "flash.preferences_saved": "Preferencias salvas.",
    "flash.destination_limit": "Limite de {n} destinos atingido.",
    "flash.need_webhook_url": "Informe a URL do webhook.",
    "flash.destination_added": "Destino adicionado.",
    "flash.destination_not_found": "Destino nao encontrado.",
    "flash.destination_saved": "Destino salvo.",
    "flash.destination_removed": "Destino removido.",
    "flash.bad_url": "URL invalida (comece com http:// ou https://).",
    "flash.destination_test_failed": "{name}: {reason}",
    "flash.destination_test_sent": "Mensagem enviada para {name} - confira o canal.",
    "flash.user_exists": "Ja existe um usuario chamado '{user}'.",
    "flash.user_created":
        "Usuario '{user}' criado como {role}. Passe a senha para ele e peca para troca-la na "
        "tela Conta.",
    "flash.cannot_change_own_role": "Voce nao pode mudar o proprio papel — peca a outro administrador.",
    "flash.user_already_is": "'{user}' ja e {role}.",
    "flash.only_admin_demote": "Este e o unico administrador: promova outra pessoa antes de rebaixa-lo.",
    "flash.user_now_is": "'{user}' agora e {role}.",
    "flash.password_reset": "Senha de '{user}' redefinida.",
    "flash.own_two_factor_in_account": "Para desligar o seu proprio 2FA use a tela Conta.",
    "flash.user_two_factor_off": "Verificacao em duas etapas de '{user}' desligada.",
    "flash.cannot_remove_self": "Voce nao pode remover a propria conta.",
    "flash.cannot_remove_only_admin": "Nao da para remover o unico administrador do painel.",
    "flash.user_removed": "Usuario '{user}' removido.",

    # --------------------------------- erros do cadastro de servidor
    "form.need_name": "Informe um nome.",
    "form.bad_host": "Host invalido (use o IP ou hostname do container).",
    "form.bad_ssh_user": "Usuario SSH invalido.",
    "form.bad_ssh_port": "Porta SSH invalida.",
    "form.bad_query_port": "Porta de consulta invalida (use 0 para desligar).",
    "form.bad_service": "Servico invalido (ex.: dragonwilds.service).",
    "form.bad_player_source": "Forma de contar jogadores invalida.",
    "form.bad_config_folder": "Pasta de configuracao invalida: {reason}",
    "form.bad_config_file": "Arquivo de configuracao invalido ({path}): {reason}",
    "form.too_many_config_files": "No maximo {n} arquivos de configuracao por servidor.",
    "form.bad_backup_path": "Caminho de backup invalido ({path}): {reason}",
    "form.no_root_backup": "Backup da raiz nao: aponte a pasta do save ou da configuracao.",
    "form.too_many_backup_paths": "No maximo {n} caminhos de backup por servidor.",
    "form.bad_api_url": "URL da API invalida (ex.: http://127.0.0.1:8212/v1/api/players).",
    "form.bad_login_url": "URL de login invalida (ex.: https://127.0.0.1:7787/api/v1).",
    "form.bad_json": "{label} nao e JSON valido: {reason}.",
    "form.request_body": "Corpo da requisicao",
    "form.login_body": "Corpo do login",
    "form.path_list": "lista",
    "form.path_count": "contagem",
    "form.path_token": "token",
    "form.bad_json_path": "Caminho da {label} invalido (use algo como 'data.players').",
    "form.login_needs_token_path":
        "Para o login automatico, informe tambem o caminho do token (ex.: "
        "data.authenticationToken).",
    "pattern.join": "entrada",
    "pattern.leave": "saida",
    "pattern.error": "erro",

    # -------------------------------------------------- consulta A2S
    "a2s.truncated": "resposta do servidor terminou antes do esperado",
    "a2s.unterminated_text": "texto sem terminador na resposta",
    "a2s.split_incomplete": "resposta dividida veio incompleta",
    "a2s.split_unknown": "resposta dividida em formato desconhecido (compactada?)",
    "a2s.unexpected_reply": "resposta inesperada do servidor (tipo {kind})",
    "a2s.no_reply": "sem resposta em {seconds}s na porta {port}/udp",
    "a2s.query_failed": "falha ao consultar {host}:{port} - {reason}",

    # -------------------------------- caminho e arquivo no container
    "path.outside_roots": "fora das pastas permitidas ({folders})",
    "path.not_absolute": "use um caminho absoluto (comecando com /)",
    "path.bad_character": "caractere invalido no caminho",
    "path.too_long": "caminho longo demais",
    "file.unexpected_reply": "resposta inesperada do container ao ler o arquivo",
    "file.corrupted": "conteudo do arquivo chegou corrompido",
    "backup.bad_name": "nome de backup invalido",

    # ----------------------------------------------------------- ssh
    "ssh.failed_to_run": "falha ao executar ssh: {reason}",
    "ssh.no_stdin": "nao consegui abrir a entrada do ssh",
    "ssh.no_stdout": "nao consegui abrir a saida do ssh",
    "ssh.upload_timeout": "tempo esgotado ({seconds}s) enviando para {host}",

    # ---------------------------------------------- api http do jogo
    "http.bad_url": "URL invalida (ex.: http://127.0.0.1:8212/v1/api/players)",
    "http.auth_failed": "a API respondeu {status} - confira o usuario/senha de admin",
    "http.bad_status": "a API respondeu HTTP {status}",
    "http.reply_too_big": "resposta da API grande demais para ser lida aqui",
    "http.not_json": "a resposta nao e JSON: {sample}",
    "api.login_incomplete": "login automatico incompleto (falta URL de login ou caminho do token)",
    "api.no_token_at": "o login respondeu, mas nao achei um token em '{path}'",
    "api.need_url": "informe a URL da API do jogo",
    "api.need_join_pattern": "informe o padrao da linha de entrada de jogador",
    "api.need_query_port": "informe a porta de consulta (query Steam) do servidor",
    "api.action_not_published": "este servidor nao publica essa acao",
    "api.write_the_notice": "escreva o aviso",
    "api.no_player_id": "nao sei quem expulsar: a API nao publicou o identificador deste jogador",

    # ---------------------------------------- padrao de log e broker
    "pattern.too_long": "padrao de {label} longo demais (limite de {n} caracteres)",
    "pattern.invalid": "padrao de {label} invalido: {reason}",
    "broker.bad_host_or_service": "o broker devolveu host ou servico com formato invalido",
    "broker.server_not_saved": "o servidor nao foi gravado",

    # -------------------------- texto dos alertas (vai para o canal)
    "alert.contact_back": "{name}: contato restabelecido",
    "alert.lost_contact": "{name}: painel perdeu contato",
    "alert.no_detail": "sem detalhe",
    "alert.server_back": "{name}: servidor voltou a rodar",
    "alert.server_stopped": "{name}: servidor parou de rodar",
    "alert.game_failed": "{name}: o jogo quebrou",
    "alert.service_is_failed": "servico {service} esta 'failed'",
    "alert.service_is": "servico {service} esta '{state}'",
    "alert.restart_loop": "{name}: o jogo esta caindo em loop",
    "alert.systemd_restarted": "o systemd reiniciou {service} {times}x desde a ultima olhada",
    "alert.game_answering": "{name}: o jogo voltou a responder",
    "alert.game_mute": "{name}: o jogo nao responde",
    "alert.service_up_game_mute": "o servico {service} esta rodando, mas o jogo nao responde ha",
    "alert.log_error": "{name}: erro no log do jogo",
    "alert.disk_almost_full": "{name}: disco quase cheio",
    "alert.disk_detail": "{mount} em {pct}% ({used} de {total})",
    "alert.memory_almost_full": "{name}: memoria quase cheia",
    "alert.memory_detail": "{pct}% ({used} de {total})",
    "alert.cpu_high": "{name}: uso de CPU alto",
    "alert.cpu_detail_one": "{pct}% em {cores} nucleo",
    "alert.cpu_detail_many": "{pct}% em {cores} nucleos",
    "alert.cpu_game_part": " (jogo: {pct}%)",
    "alert.nobody_online": "nenhum jogador online",
    "alert.players_online_one": "{n} jogador online",
    "alert.players_online_many": "{n} jogadores online",
    "alert.players_online_rough": "{n} jogador(es) online",
    "alert.player_joined": "{name}: {player} entrou no jogo",
    "alert.player_left": "{name}: {player} saiu do jogo",
    "alert.joined_one": "{name}: um jogador conectou",
    "alert.joined_many": "{name}: {n} jogadores conectaram",
    "alert.left_one": "{name}: um jogador saiu",
    "alert.left_many": "{name}: {n} jogadores sairam",
    "alert.restarts_total": " ({n} no total desta subida)",
    "alert.mute_rounds": " {n} verificacoes",

    # ---------------------------------------- agendamento e dias da semana
    "schedule.daily": "todo dia as {time}",
    "schedule.weekly": "{weekday} as {time}",
    "schedule.every_hour": "a cada hora",
    "schedule.every_n_hours": "a cada {n}h",
    "weekday.monday": "segunda",
    "weekday.tuesday": "terca",
    "weekday.wednesday": "quarta",
    "weekday.thursday": "quinta",
    "weekday.friday": "sexta",
    "weekday.saturday": "sabado",
    "weekday.sunday": "domingo",
    "weekday.on_monday": "toda segunda",
    "weekday.on_tuesday": "toda terca",
    "weekday.on_wednesday": "toda quarta",
    "weekday.on_thursday": "toda quinta",
    "weekday.on_friday": "toda sexta",
    "weekday.on_saturday": "todo sabado",
    "weekday.on_sunday": "todo domingo",
}
