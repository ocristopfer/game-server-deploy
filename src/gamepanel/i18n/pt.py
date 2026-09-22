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
    "alerts.pending_item": "<em>{evento}</em>: nenhum servidor tem {falta}.",
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
    "alerts.remove_confirm": "Remover o destino {nome}?",
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
        "memoria e CPU a cada <strong>{medidor} min</strong> (o medidor custa bem mais caro que o "
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
        "<em>ouvindo</em> o log ({ouvindo}) e reage a linha no segundo em que ela sai. Perguntar "
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
        "Restaurar {arquivo} em {servidor}?\n\nO servidor sera PARADO, os arquivos de agora serao "
        "substituidos e ele volta a subir. Uma copia do estado atual e guardada antes.",
    "backups.delete_confirm": "Apagar {arquivo}? Nao tem volta.",
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
    "files.delete_confirm": "Apagar {caminho}? Isto nao tem volta.",
    "history.filter": "Filtrar",
    "history.clear": "limpar",
    "history.newer": "mais recentes",
    "history.older": "mais antigas",
    "instances.create": "Criar instancia",
    "instances.create_confirm":
        "Criar o container, instalar o jogo e abrir as portas no firewall? Isso pode levar varios "
        "minutos.",
    "instances.deactivate_confirm": "Desativar {nome}? O servidor sera PARADO e as portas fecham no firewall.",
    "instances.remove_confirm": "Remover {nome}? O container e o jogo serao APAGADOS.",
    "login_2fa.confirm": "Confirmar",
    "login_2fa.back": "Voltar",
    "schedules.run_now": "rodar agora",
    "schedules.run_now_help": "Roda agora, sem esperar a hora",
    "schedules.turn_on": "ligar",
    "schedules.turn_off": "desligar",
    "schedules.delete": "remover",
    "schedules.delete_confirm": "Remover: {tarefa}?",
    "schedules.schedule_it": "Agendar",
    "schedules.never": "nunca",
    "server_detail.configure": "Configurar",
    "server_detail.how_counting_works": "Como o painel conta os jogadores deste servidor",
    "server_detail.announce": "Avisar",
    "server_detail.reload": "Recarregar",
    "users.change": "Trocar",
    "users.two_factor_off": "Desligar 2FA",
    "users.two_factor_off_confirm":
        "Desligar a verificacao em duas etapas de {usuario}? Ele entra so com a senha ate ativar "
        "de novo.",
    "users.remove_confirm": "Remover o usuario {usuario}?",
    "users.create": "Criar",
}
