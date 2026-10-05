"""Portuguese catalog (the panel's default language).

The key is neutral and the same in every catalog; see the package docstring. A new key goes
in HERE first - this is the file the test uses as the reference to check the other languages.

Key convention: `area.subject`, all lowercase, in English (it is a code identifier, not
screen text).
"""
from __future__ import annotations

MESSAGES: dict[str, str] = {
    # -------------------------------------------------------- navigation
    "nav.servers": "Servidores",
    "nav.history": "Histórico",
    "nav.alerts": "Alertas",
    "nav.account": "Conta",
    "nav.users": "Usuários",
    "nav.backups": "Backups",
    "nav.backups.help": "Cópias do save guardadas no painel",
    "archive.title": "Backups no painel",
    "archive.intro":
        "Todas as cópias do save que o painel guardou, por jogo — inclusive as de um jogo cujo "
        "servidor já foi removido. Elas ficam em <code>{dir}</code>.",
    "archive.keep": "De cada jogo ficam as {n} cópias mais novas.",
    "archive.keep_all": "Nenhuma cópia é apagada automaticamente.",
    "archive.none":
        "O painel ainda não guardou nenhuma cópia. Todo backup novo vem para cá; os antigos, que só "
        "estão no container, podem ser enviados pela aba Backups do servidor.",
    "archive.restore_on": "Restaurar em",
    "archive.no_server":
        "Nenhum servidor deste jogo no painel. Crie a instância (ou cadastre o servidor) de novo: "
        "a cópia aparece na aba Backups dele, com o botão restaurar.",
    "archive.game": "Jogo",
    "nav.instances": "Instâncias",
    "nav.instances.help": "Instâncias de jogo",
    "nav.catalog": "Catálogo",
    "nav.catalog.help": "Catálogo de jogos",
    "nav.add_server": "Adicionar servidor",
    "nav.ssh_key": "Acesso SSH",
    "nav.logout": "Sair",
    "nav.more": "Mais",
    "prefs.theme": "Alternar tema claro/escuro",
    "prefs.language": "Mudar o idioma da tela",
    "nav.account_of": "Conta de {name}",
    "nav.main": "Navegação principal",

    # ------------------------------------------------------------ roles
    "role.admin": "Administrador",
    "role.operator": "Operador",

    # ------------------------------------------------ server sections
    "server.overview": "Visão geral",
    "server.overview.help": "Estado, jogadores, recursos e log",
    "server.config": "Configuração",
    "server.config.help": "As chaves do jogo, campo a campo",
    "server.mods": "Mods",
    "server.mods.help": "O que o servidor carrega de mod, e enviar mod para ele",
    "server.files": "Arquivos",
    "server.files.help": "Navegar, editar como texto, enviar e baixar",
    "server.charts": "Gráficos",
    "server.charts.help": "CPU, memória e jogadores ao longo do tempo",
    "server.backups": "Backups",
    "server.backups.help": "Cópias do save, e como restaurar",
    "server.schedules": "Agendamentos",
    "server.schedules.help": "Reinício e backup na hora marcada",
    "server.terminal": "Terminal",
    "server.terminal.help": "Linha de comando dentro do container",
    "server.console": "Console",
    "server.edit": "Editar",
    "server.edit.help": "Host, serviço, portas e caminhos",

    # ------------------------------------------------------------ actions
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

    # ------------------------------------------------- base and version notice
    "app.name": "Painel de Jogos",
    "app.new_version": "Há uma versão nova do painel.",
    "app.version": "Painel versão {version}",
    "app.update_now": "Atualizar agora",
    "app.install": "Instalar",

    # ------------------------------------------------------------- login
    "login.title": "Entrar",
    "login.subtitle": "Entre para gerenciar os servidores.",
    "login.username": "Usuário",
    "login.password": "Senha",

    # ------------------------------------------------------------ language
    "account.language": "Idioma",
    "account.language.title": "Idioma da tela",
    "account.language.changed": "Idioma alterado.",

    # -------------------------------------------------------- dashboard
    "dashboard.no_servers": "Nenhum servidor cadastrado ainda.",
    "dashboard.ssh_access": "Acesso SSH",
    "dashboard.ask_an_admin": "Peça a um administrador do painel para cadastrar o servidor.",

    # ----------------------------------------------------- history
    "history.server": "Servidor",
    "history.any_server": "todos",
    "history.action": "Ação",
    "history.any_action": "todas",
    "history.who": "Quem",
    "history.anyone": "qualquer um",
    "history.when": "Quando",
    "history.result": "Resultado",
    "history.auto": "auto",
    "history.running": "rodando",
    "history.empty": "Nada no histórico com esses filtros.",
    "history.by_scheduler": "Disparado pelo relógio do painel",

    # ----------------------------------------------------------- job
    "job.target": "Destino",
    "job.started": "Iniciado",
    "job.by": "Por",
    "job.result": "Resultado",

    # ------------------------------------------------------- offline
    "offline.title": "Sem conexão — Painel de Jogos",
    "offline.heading": "Sem conexão",
    "offline.vpn_hint": "Se você está fora de casa, confira se a VPN está ligada.",
    "offline.retry": "Tentar de novo",

    # ----------------------------------------------------- ssh key
    "ssh_key.public_key": "Chave pública do painel",
    "ssh_key.not_found": "Chave não encontrada. Rode o deploy do painel novamente.",
    "ssh_key.authorize": "Autorizar num container de jogo",
    "ssh_key.host_keys": "Host keys",

    # ------------------------------------------------------ charts
    "charts.no_samples": "Ainda não há amostras deste período.",
    "charts.cpu_memory": "CPU e memória",
    "charts.no_readings": "Sem leitura de medidores neste período.",
    "charts.players": "Jogadores",
    "charts.as_table": "Ver os números em tabela",
    "charts.when": "Quando",
    "charts.cpu": "CPU",
    "charts.memory": "Memória",
    "charts.period": "Período",

    # ------------------------------------------------------- backups
    "backups.what_is_saved": "O que entra na cópia",
    "backups.stored_copies": "Cópias no container",
    "backups.file": "Arquivo",
    "backups.when": "Quando",
    "backups.size": "Tamanho",
    "backups.before_restore": "antes de restaurar",
    "backups.admin_only": "baixar, restaurar e apagar são de administrador",
    "backups.none_yet": "Nenhuma cópia ainda.",
    "backups.pre_restore_copy": "Tirada pelo painel logo antes de uma restauração",

    # -------------------------------------------------- schedules
    "schedules.tasks_here": "Tarefas deste servidor",
    "schedules.task": "Tarefa",
    "schedules.when": "Quando",
    "schedules.next_run": "Próxima",
    "schedules.last_run": "Última vez",
    "schedules.off": "desligada",
    "schedules.admin_only": "só administrador altera",
    "schedules.none_here": "Nada agendado para este servidor.",
    "schedules.new_task": "Agendar uma tarefa",
    "schedules.what_to_do": "O que fazer",
    "schedules.daily": "Todo dia, numa hora fixa",
    "schedules.weekly": "Uma vez por semana",
    "schedules.every_n_hours": "A cada N horas",
    "schedules.hour": "Hora",
    "schedules.minute": "Minuto",
    "schedules.weekday": "Dia da semana",
    "schedules.every": "A cada",
    "schedules.hours_from_now": "horas, contadas a partir de agora",
    # ---------------------------------------------------- instances
    "instances.new": "Nova instância",
    "instances.game": "Jogo",
    "instances.only_installable": "Só aparecem os jogos que o broker sabe instalar sozinho.",
    "instances.name": "Nome",
    "instances.none_creatable": "Nenhum jogo criável no catálogo (ou o broker não respondeu).",
    "instances.game_not_listed": "O jogo não está aqui? Adicione ao catálogo.",
    "instances.name_hint":
        "Como a instância aparece no painel. Letras, números, espaço, ponto, "
        "hífen e sublinhado.",
    "instances.how_it_works":
        "O broker escolhe o IP e as portas livres, cria o container, instala o jogo e só então "
        "abre o firewall. Você acompanha o progresso na tela da ação.",
    "instances.instance": "Instância",
    "instances.remove": "Remover",
    "instances.type_name_to_confirm": "Digite o nome para confirmar",
    "instances.forget_record_only": "Esquecer só o registro (o container já não existe mais no Proxmox)",
    "instances.none_yet": "Nenhuma instância criada pelo broker ainda.",

    # ------------------------------------------------------- console
    "console.interactive": "Sessão interativa",
    "console.single_command": "Comando único",
    "console.history_hint": "Histórico: &uarr; e &darr; percorrem os comandos anteriores.",
    "console.output": "Saída",
    "console.previous_commands": "Comandos anteriores",
    "console.when": "Quando",
    "console.command": "Comando",
    "console.by": "Por",
    "console.result": "Resultado",
    "console.view": "ver",
    "console.none_yet": "Nenhum comando executado neste servidor ainda.",
    "console.terminal_mode": "Modo do terminal",

    # ------------------------------------------------------ files
    "files.download": "baixar",
    "files.delete": "apagar",
    "files.empty_folder": "pasta vazia",
    "files.listing_truncated": "Listagem cortada nos primeiros itens desta pasta.",
    "files.configuration": "Configuração",
    "files.editor": "Editor",
    "files.edit_server": "Editar servidor",
    "files.path_lower": "caminho",
    "files.file_to_upload": "arquivo para enviar",
    "files.path": "Caminho",

    # ------------------------------------------------- second factor
    "login_2fa.title": "Verificação",
    "login_2fa.hint": "Digite o código de 6 dígitos do aplicativo autenticador.",
    "login_2fa.code": "Código",
    "account_2fa.copy_key": "Copiar chave",
    "account_2fa.six_digit_code": "Código de 6 dígitos",
    "account_2fa_codes.copy_codes": "Copiar códigos",

    # ------------------------------------------------------ users
    "users.user": "Usuário",
    "users.role": "Papel",
    "users.created_at": "Criado em",
    "users.you": "você",
    "users.reset_password": "Redefinir senha",
    "users.new_user": "Novo usuário",
    "users.initial_password": "Senha inicial",
    "users.confirm_password": "Confirmar senha",
    "users.what_each_role_opens": "O que cada papel abre",
    "users.screen": "Tela",
    "users.perm_overview": "Servidores, status, jogadores, log",
    "users.yes": "sim",
    "users.no": "não",
    "users.perm_actions": "Start / stop / restart / update",
    "users.perm_config": "Configuração (arquivos já registrados)",
    "users.perm_charts": "Gráficos, backups e agendamentos",
    "users.perm_manage_servers": "Cadastrar / editar / remover servidor",
    "users.perm_register_config": "Registrar novo arquivo de config",
    "users.perm_terminal": "Terminal e navegador de arquivos",
    "users.two_factor_on": "Verificação em duas etapas ativada",
    "users.new_password_lower": "nova senha",
    "users.confirm_lower": "confirmar",

    # ------------------------------------------ game configuration
    "config.edit_as_text": "editar como texto",
    "config.unpin": "tirar da lista",
    "config.found_in_container": "Arquivos de configuração encontrados no container",
    "config.pin_here": "fixar aqui",
    "config.empty_block": "Bloco vazio &mdash; use &quot;adicionar configuração&quot; abaixo.",
    "config.no_match": "Nenhuma configuração com esse nome.",
    "config.add_setting": "Adicionar configuração",
    "config.new_setting_block": "Bloco da configuração nova",
    "config.restart_after_save": "reiniciar o servidor depois de salvar",
    "config.edit_as_text_title": "Edite como texto",
    "config.file_path": "caminho do arquivo de configuração",
    "config.filter_placeholder": "filtrar por nome...",
    "config.filter_label": "filtrar configurações",
    "config.name_example": "Nome (ex.: ServerPassword)",
    "config.new_setting_name": "nome da configuração nova",
    "config.value": "Valor",
    "config.new_setting_value": "valor da configuração nova",

    # ------------------------------------------------------ terminal
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

    # --------------------------------------------------------- account
    "account.role": "Papel",
    "account.change_password": "Trocar senha",
    "account.current_password": "Senha atual",
    "account.new_password": "Nova senha",
    "account.min_length": "Mínimo de 8 caracteres.",
    "account.confirm_new_password": "Confirmar nova senha",
    "account.two_factor": "Verificação em duas etapas",
    "account.on": "ativada",
    "account.off": "desativada",
    "account.two_factor_on_hint": "Além da senha, o login pede o código do aplicativo autenticador.",
    "account.new_recovery_codes": "Gerar códigos de recuperação novos",
    "account.app_code": "Código do aplicativo",
    "account.old_codes_expire": "Os códigos antigos deixam de valer.",
    "account.disable": "Desativar",
    "account.app_or_recovery_code": "Código do aplicativo (ou de recuperação)",
    "account.two_factor_required": "Este painel exige o segundo fator: não dá para desativar.",
    "account.two_factor_broker_hint": "Este painel cria e apaga containers pelo broker: ative.",
    "account.sign_out": "Sair",
    "account.sign_out_hint": "Encerra a sessão neste aparelho.",

    # ---------------------------------------------- server screen
    "server_detail.host": "Host",
    "server_detail.access": "Acesso",
    "server_detail.access_helper": "sem root ({user})",
    "server_detail.access_legacy": "root (legado, falta migrar)",
    "server_detail.ssh_port": "Porta SSH",
    "server_detail.service": "Serviço",
    "server_detail.game_ports": "Portas do jogo",
    "server_detail.config_folder": "Pasta de config",
    "server_detail.server": "Servidor",
    "server_detail.maintenance": "Manutenção",
    "server_detail.published_name": "Nome publicado",
    "server_detail.world": "Mundo",
    "server_detail.online": "Online",
    "server_detail.player": "Jogador",
    "server_detail.connected_for": "Conectado há",
    "server_detail.score": "Pontos",
    "server_detail.no_identifier": "sem identificador",
    "server_form.max_players": "Vagas",
    "server_form.max_players_hint": (
        "Total de jogadores do servidor, para a tela mostrar 2/6. Só conta "
        "quando a contagem não informa (log, conexões ativas)."),
    "form.bad_max_players": "Vagas: um número de 0 a 1000.",
    "player_source.net": "conexões ativas",
    "server_form.count_net": "Conexões ativas na porta do jogo (firewall do CT)",
    "flash.count_on_by_net": "Contagem ligada pelas conexões ativas na porta do jogo.",
    "presence.missing": (
        "O firewall deste CT não conta conexões ainda: reaplique o firewall "
        "(deploy/firewall/apply-firewall.ps1)."),
    "presence.unreadable": "Não consegui ler as conexões ativas do firewall do CT.",
    "players_setup.presence_title": "Conexões ativas na porta do jogo",
    "players_setup.presence_help": (
        "Quem está trocando pacotes com o servidor agora, contado pelo firewall do CT. Serve para "
        "jogo sem consulta (o Dragonwilds usa EOS): o número não depende do log, e os nomes "
        "continuam vindo dele."),
    "server_detail.names_from": "Contagem por: {source}. Nomes por: {names_from}.",
    "server_detail.names_partial": "Os nomes não batem com a contagem: a lista mostra os últimos a entrar.",
    "server_detail.fallback": "A fonte escolhida não respondeu ({error}). Contando por: {source}.",
    "player_source.a2s": "consulta A2S",
    "player_source.http": "API do jogo",
    "player_source.log": "log do servidor",
    "server_detail.resources": "Recursos",
    "server_detail.swap": "Swap",
    "server_detail.network": "Rede",
    "server_detail.uptime": "Uptime",
    "server_detail.game_process": "Processo do jogo",
    "server_detail.recent_actions": "Ações recentes",
    "server_detail.no_actions_yet": "Nenhuma ação executada por aqui ainda.",
    "server_detail.service_log": "Log do serviço",
    "server_detail.live": "ao vivo",
    "server_detail.follow_log": "Seguir log",
    "server_detail.lines": "linhas",
    "server_detail.broadcast": "Aviso para todo mundo no servidor",
    "server_detail.broadcast_message": "mensagem do aviso",

    # --------------------------------------------- alerts - destinations
    "alerts.destinations_on_one": "{n} destino ligado",
    "alerts.destinations_on_many": "{n} destinos ligados",
    "alerts.no_destination_on": "nenhum destino ligado",
    "alerts.intro":
        "O painel avisa por <strong>webhook</strong> quando algo acontece sem ninguém estar "
        "olhando. Cada destino tem a sua própria lista de eventos &mdash; dá para mandar tudo para "
        "o canal da equipe e só as quedas para o canal geral. Serve para <strong>Discord</strong> "
        "(Editar canal &rarr; Integrações &rarr; Webhooks &rarr; Copiar URL), "
        "<strong>Slack</strong> (Incoming Webhook) ou qualquer endereço que aceite um "
        "<code>POST</code> de JSON &mdash; a chamada leva os campos <code>content</code> e "
        "<code>text</code>, então cada um lê o seu.",
    "alerts.destinations": "Destinos",
    "alerts.no_destination_yet": "Nenhum destino cadastrado — os alertas estão desligados. Adicione o primeiro abaixo.",
    "alerts.pending_intro":
        "<strong>Ligado, mas sem onde olhar.</strong> Estes eventos nunca vão disparar do jeito "
        "que o painel está hoje &mdash; e canal em silêncio parece \"está tudo bem\":",
    "alerts.pending_item": "<em>{event}</em>: nenhum servidor tem {missing}.",
    "alerts.pending_fix": "Ajuste no <a href=\"{url}\">cadastro de cada servidor</a>.",
    "alerts.destination_name": "Nome do destino",
    "alerts.team_channel": "Canal da equipe",
    "alerts.on": "Ligado",
    "alerts.off": "Desligado",
    "alerts.url_is_a_secret": "A URL fica escondida: é uma credencial",
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
    "alerts.name_hint": "Só para você se achar nesta lista.",
    "alerts.webhook_url": "URL do webhook",
    "alerts.webhook_url_hint": "É um segredo: quem a tiver escreve no seu canal.",
    "alerts.add": "Adicionar",
    "alerts.came_from_env":
        "O deploy trouxe uma URL em <code>GAMEPANEL_WEBHOOK_URL</code>; ela virou o primeiro "
        "destino desta lista e a partir daqui só vale o que estiver cadastrado.",

    # ----------------------------------------- alerts - preferences
    "alerts.preferences": "Preferências",
    "alerts.warn_disk_over": "Avisar quando o disco passar de",
    "alerts.disk_hint":
        "No disco mais cheio do container. Avisa uma vez, na virada: um disco a 95% continua a 95% "
        "na volta seguinte e ninguém merece o mesmo alerta a cada minuto.",
    "alerts.warn_memory_over": "Avisar quando a memória passar de",
    "alerts.memory_hint":
        "Memória do container, contra o limite dele (não o da máquina inteira). Avisa uma vez, na "
        "virada, do mesmo jeito que o disco.",
    "alerts.warn_cpu_over": "Avisar quando a CPU passar de",
    "alerts.cpu_hint":
        "Uso do container sobre os núcleos que ele tem, medido junto com o disco (a cada {n} min). "
        "Como é uma amostra curta de vez em quando, serve para pegar CPU presa no teto, não pico "
        "de um segundo.",

    # ----------------------------------------------- alerts - daily log
    "alerts.journal": "Diário de alertas",
    "alerts.journal_empty":
        "Nada registrado ainda. Cada alerta que o painel decidir mandar aparece aqui &mdash; "
        "inclusive os que <strong>não</strong> saíram.",
    "alerts.when_utc": "Quando (UTC)",
    "alerts.event": "Evento",
    "alerts.what": "O que",
    "alerts.destination": "Destino",
    "alerts.outcome": "Saída",
    "alerts.sent": "enviado",
    "alerts.failed": "falhou",
    "alerts.no_destination": "sem destino",
    "alerts.internal_error": "erro interno",
    "alerts.journal_legend":
        "<strong>sem destino</strong> quer dizer que o alerta aconteceu de verdade e nenhum "
        "destino ativo tinha esse evento marcado &mdash; o canal fica mudo por escolha, não por "
        "defeito. <strong>erro interno</strong> é uma tarefa do relógio que quebrou: enquanto ela "
        "aparecer aqui, os alertas dela não estão sendo checados.",

    # ---------------------------------------- alerts - how it works
    "alerts.how_it_works": "Como funciona",
    "alerts.rule_rhythm":
        "O painel confere o estado de cada servidor a cada <strong>{monitor}s</strong> e disco, "
        "memória e CPU a cada <strong>{meter} min</strong> (o medidor custa bem mais caro que o "
        "status, e as três leituras saem de uma vez só).",
    "alerts.rule_joining":
        "<strong>Jogador entrando é a exceção:</strong> esse o painel confere a cada "
        "<strong>{n}s</strong>, porque quem recebe o aviso costuma querer entrar junto e um minuto "
        "depois já é tarde. Essa volta curta pergunta direto ao jogo, sem SSH &mdash; por isso ela "
        "cabe sem encarecer o resto. Vale para quem conta por <strong>A2S ou API HTTP</strong>.",
    "alerts.streams_now": "<strong>{n}</strong> agora",
    "alerts.streams_none": "nenhuma no momento",
    "alerts.rule_log_listen":
        "Quem conta por <strong>log</strong> não é perguntado: o painel deixa uma conexão aberta "
        "<em>ouvindo</em> o log ({listening}) e reage a linha no segundo em que ela sai. Perguntar "
        "de 15 em 15 segundos custaria uma leitura do log inteiro a cada vez; assim só se lê "
        "quando alguém de fato entrou ou saiu. Se a conexão cair, o aviso volta a sair pela volta "
        "de {monitor}s até ela se restabelecer.",
    "alerts.rule_on_change":
        "Ele avisa na <strong>mudança</strong>, nunca em repetição: o alerta sai quando o servidor "
        "cai, não a cada volta enquanto ele estiver caído.",
    "alerts.rule_all_destinations":
        "Cada evento vai para <strong>todos os destinos</strong> que o marcaram. Um destino fora "
        "do ar não impede os outros de receber.",
    "alerts.rule_service_up_is_not_game_up":
        "<strong>Serviço de pé não quer dizer jogo de pé.</strong> Além da queda, o painel olha "
        "três coisas que passariam batido:",
    "alerts.rule_game_failed":
        "<em>Jogo quebrou</em> &mdash; o systemd marcou o serviço como <code>failed</code>. É "
        "diferente de \"parou\": alguém parar pelo painel não gera este alerta, e este aqui sai "
        "mesmo dentro da janela de silêncio.",
    "alerts.rule_restart_loop":
        "<em>Loop de restart</em> &mdash; o jogo morre e o systemd levanta de novo, sem parar. "
        "Entre uma queda e outra o serviço responde <code>active</code>, e o alerta de queda nunca "
        "dispara. Sai uma vez por episódio.",
    "alerts.rule_game_mute":
        "<em>Jogo não responde</em> &mdash; o processo está vivo mas mudo na consulta do próprio "
        "jogo, por {n} verificações seguidas. Só vale para quem conta jogadores por <strong>A2S ou "
        "API HTTP</strong>: contagem por log não pergunta nada ao jogo.",
    "alerts.rule_log_error":
        "<em>Erro no log do jogo</em> lê o fim do log a cada <strong>{n}s</strong> e procura a "
        "expressão cadastrada em cada servidor. Sem expressão, nem a leitura acontece. A mesma "
        "linha não avisa duas vezes.",
    "alerts.rule_quiet_window":
        "Parar, reiniciar, atualizar ou restaurar <strong>pelo painel</strong> não vira alerta "
        "&mdash; nos {n}s seguintes a uma dessas ações a queda é esperada.",
    "alerts.rule_on_boot":
        "Ao subir, o painel só <strong>anota</strong> o estado de todo mundo. Reiniciar o painel "
        "não dispara um alerta por servidor que já estava parado.",
    "alerts.rule_scheduled_only":
        "De tarefa que falha, só a <strong>agendada</strong> vira alerta: quem clicou o botão já "
        "está com o erro na tela.",
    "alerts.rule_editing_resets":
        "Mexer nesta tela zera a linha de base do monitor, para a volta seguinte não avisar sobre "
        "o que já estava assim antes da mudança.",

    # --------------------------------------------- mod manager
    "mods.no_profile":
        "Este jogo ainda não tem gestor de mods. Os arquivos de mod podem ir pela tela Arquivos.",
    "mods.help_ets2":
        "No Euro Truck Simulator 2 o servidor <strong>não carrega arquivo de mod</strong>: mapa, "
        "DLCs e mods vêm dentro dos <code>server_packages</code>, exportados do JOGO com os mods "
        "ativos no perfil (console, com o mapa carregado: <code>export_server_packages</code>). "
        "Cada jogador precisa ter os MESMOS mods. Trocou a lista? Exporte e envie os pacotes de novo.",
    "mods.help_unreal_linux":
        "Os mods <code>.pak</code> do servidor ficam em <code>{folder}</code>. Mod que mexe só no "
        "visual e do cliente; mod de regra de jogo precisa estar aqui E, em geral, nos jogadores. "
        "Mods de script (UE4SS) rodam pelo UE4SS oficial compilado para Linux, logo abaixo: os mods "
        "Lua ficam na pasta <code>ue4ss/Mods</code> ao lado do executável do jogo. Instalar gera os "
        "arquivos deste servidor (o motor de cada jogo tem mudanças do estúdio); depois de um update "
        "do jogo, instale de novo.",
    "mods.help_palworld":
        "Os mods <code>.pak</code> do servidor ficam em <code>{folder}</code>. Mod que mexe só no "
        "visual e do cliente; mod de regra de jogo precisa estar aqui E, em geral, nos jogadores. "
        "Mods de script (UE4SS) rodam pelo UE4SS oficial compilado para Linux, logo abaixo: os mods "
        "Lua ficam na pasta <code>ue4ss/Mods</code> ao lado do executável do jogo.",
    "mods.packages_title": "O que o servidor carrega",
    "mods.no_packages":
        "Nenhum pacote em <code>{folder}</code> ainda: exporte do jogo e envie o "
        "<code>server_packages.sii</code> e o <code>server_packages.dat</code> abaixo.",
    "mods.packages_unreadable": "O server_packages.sii do servidor não pode ser lido como texto.",
    "mods.summary": "Mapa {map} - {dlcs} DLCs - {n} mods",
    "mods.col_mod": "Mod",
    "mods.col_origin": "Origem",
    "mods.workshop": "Workshop",
    "mods.manual": "instalado à mão (fora da Workshop)",
    "mods.optional": "opcional",
    "mods.players_list_title": "Links para os jogadores",
    "mods.players_list_help":
        "Copie e mande para quem vai jogar: são os mods da Workshop que o servidor usa. Os "
        "instalados à mão (como um mapa baixado de site) não estão aqui.",
    "mods.expected_title": "Lista de mods que o servidor deveria ter",
    "mods.missing": "Faltam {n} mods da lista nos pacotes do servidor:",
    "mods.missing_help":
        "Não estavam ativos no perfil de quem exportou. Ative-os no jogo, exporte de novo e envie "
        "os pacotes.",
    "mods.all_present": "Todos os mods da lista estão nos pacotes do servidor.",
    "mods.extra": "No servidor, mas fora da lista: {names}",
    "mods.expected_label": "Links ou IDs da Workshop, um por linha",
    "mods.expected_help":
        "Pode colar a conversa do jeito que veio (com hora e nome na frente): o painel acha o "
        "id= de cada linha.",
    "mods.expected_save": "Guardar lista",
    "mods.expected_saved": "Lista guardada: {n} mods.",
    "mods.files_title": "Mods no servidor",
    "mods.no_files": "Nenhum mod na pasta ainda.",
    "mods.delete": "Remover",
    "mods.delete_confirm": "Remover {name} do servidor?",
    "mods.deleted": "{name} removido.",
    "mods.upload_title": "Enviar para o servidor",
    "mods.files_to_send": "Arquivos",
    "mods.upload_accepts":
        "Aceita {allowed}. Vai para {folder}; um arquivo de mesmo nome é substituído (fica uma "
        "cópia .bak).",
    "mods.restart_after": "Reiniciar o servidor depois (mod só entra quando ele sobe de novo)",
    "mods.upload_button": "Enviar",
    "mods.help_vrising":
        "Mods do V Rising vêm do <strong>Thunderstore</strong> e rodam no <strong>BepInEx</strong>, "
        "que precisa estar instalado e ligado no servidor. O painel baixa tudo DE DENTRO do "
        "container. Mod de servidor só precisa estar aqui; se o mod mexe no cliente, cada jogador "
        "instala o seu.",
    "mods.status_failed": "Não consegui ler os mods do servidor: {reason}",
    "mods.not_thunderstore": "Este servidor não usa mods do Thunderstore.",
    "mods.overlay_problem":
        "O ajuste do carregador não chegaria ao jogo neste servidor (acessado sem root): {reason}",
    "mods.bad_package":
        "Não reconheci o pacote. Cole o link da página dele no Thunderstore, ou autor/pacote.",
    "mods.loader_title": "BepInEx (carregador de mods)",
    "mods.loader_on": "ligado",
    "mods.loader_off": "desligado",
    "mods.loader_missing": "O BepInEx ainda não está instalado neste servidor.",
    "mods.loader_install": "Instalar o BepInEx",
    "mods.loader_update": "Reinstalar / atualizar",
    "mods.loader_enable": "Ligar",
    "mods.loader_disable": "Desligar (o servidor sobe sem mods)",
    "mods.loader_uninstall": "Desinstalar",
    "mods.loader_uninstall_confirm":
        "Desinstalar o {name}? Ele sai do servidor junto com os mods que dependem dele, e o jogo "
        "volta ao original. Os .pak da pasta do jogo ficam. Para voltar, instale de novo.",
    "mods.overrides_bad":
        "O ajuste do Wine que o BepInEx precisa foi desfeito (um redeploy do jogo reescreve esse "
        "arquivo). Instale o BepInEx de novo para reaplicar.",
    "mods.low_memory":
        "Este servidor tem {have} MB de memória, e a primeira subida com o BepInEx pede uns "
        "{need} MB (medido: 9,4 GB). Com menos, o servidor cai por falta de memória em laço. "
        "Aumente a memória do container antes de instalar.",
    "mods.loader_first_run":
        "A primeira subida depois de instalar o BepInEx demora vários minutos: ele gera o código "
        "do jogo antes de abrir o servidor. As seguintes são normais.",
    "mods.plugins_title": "Mods (plugins)",
    "mods.col_version": "Versão",
    "mods.plugin_add_label": "Instalar mod do Thunderstore",
    "mods.plugin_add_help":
        "Link da página do mod, ou autor/pacote (ex.: deca/VampireCommandFramework). As "
        "dependências vêm junto. Sem versão, vem a mais nova; com versão (no campo abaixo ou "
        "no nome colado, deca-VampireCommandFramework-0.11.0), vem aquela e as dependências "
        "na versão que ela pede.",
    "mods.version_label": "Versão (opcional)",
    "mods.version_help": "Vazio = a mais nova. Ex.: 1.2.3",
    "mods.bad_version": "Versão inválida. Use números no formato 1.2.3, ou deixe vazio para a mais nova.",
    "mods.pinned": "versão fixada",
    "mods.change_version_title": "Trocar a versão de um mod instalado",
    "mods.change_version_help":
        "A versão escolhida substitui a instalada por inteiro, junto com as dependências que "
        "ela pede (uma dependência dividida com outro mod pode voltar para uma versão mais "
        "velha). A config do mod é mantida. Vazio atualiza para a mais nova.",
    "mods.change_version_button": "Trocar versão",
    "mods.antivirus_note":
        "Todo mod passa pelo <strong>antivírus (ClamAV)</strong> dentro do container antes de "
        "chegar ao jogo; se ele achar algo, ou não conseguir verificar, o mod NÃO entra e o "
        "servidor não reinicia. Na primeira vez o container instala o ClamAV (uns minutos a "
        "mais). Ele acha o que já é conhecido: continue baixando só de fonte em que confia.",
    "mods.audit_button": "Verificar mods instalados",
    "mods.audit_help":
        "Passa o antivírus no que já está instalado neste servidor, inclusive o que entrou antes "
        "da verificação existir. Só lê: nada é apagado, e o resultado sai no log da tarefa. Usa "
        "uns 1 GB de memória por alguns segundos, ao lado do jogo.",
    "mods.plugin_install": "Instalar",
    "mods.where_to_find": "Onde achar mods",
    "mods.source_workshop": "Steam Workshop",
    "mods.source_nexus": "Nexus Mods",
    "mods.source_thunderstore": "Thunderstore",
    "mods.source_shroudtopia": "Shroudtopia (carregador)",
    "mods.help_dragonwilds":
        "Os mods do servidor são os <strong>.pak</strong> (com os <code>.utoc</code> e "
        "<code>.ucas</code> de mesmo nome, que a Unreal 5 exige - mande os três juntos) e ficam em "
        "<code>{folder}</code>. Mods de script (UE4SS) rodam pelo UE4SS oficial compilado para Linux, "
        "logo abaixo; o jogo marca a sessão como modificada enquanto ele estiver ligado. O Nexus "
        "Mods não deixa baixar por automação sem conta Premium: baixe lá e envie aqui. A "
        "página de cada mod diz se os jogadores também precisam dele.",
    "mods.help_enshrouded":
        "Mods do Enshrouded precisam de um <strong>carregador</strong> no servidor: o Shroudtopia, que "
        "o painel baixa do GitHub e põe ao lado do <code>enshrouded_server.exe</code>. Os mods são DLLs "
        "(Nexus Mods) que entram em <code>{folder}</code>. Provado num servidor de verdade sob o Proton. "
        "A página de cada mod diz se ele é só do servidor ou também dos jogadores.",
    "mods.shroudtopia_title": "Shroudtopia (carregador de mods)",
    "mods.shroudtopia_missing": "O Shroudtopia ainda não está instalado neste servidor.",
    "mods.shroudtopia_install": "Instalar o Shroudtopia",
    "mods.shroudtopia_folder_mod": "pasta (com mod.json)",
    "mods.shroudtopia_log": "Fim do log do carregador",
    "mods.shroudtopia_log_help":
        "Mod feito para outra versão do jogo não derruba o servidor, mas perde a função "
        "em silêncio: aqui aparece como \"not found\".",
    "mods.shroudtopia_config_help":
        "Os mods de exemplo do pacote oficial NÃO são instalados: eles trazem trapaça "
        "ligada. Opções de cada mod ficam no <code>shroudtopia.json</code>, "
        "na <a href=\"{url}\">tela Arquivos</a>.",
    "mods.help_icarus":
        "Mods de script do Icarus rodam no <strong>UE4SS</strong>, que o painel baixa do GitHub e põe "
        "ao lado do <code>IcarusServer-Win64-Shipping.exe</code>. Os mods ficam em <code>{folder}</code>, "
        "uma pasta por mod.",
    "mods.ue4ss_title": "UE4SS (carregador de mods)",
    "mods.ue4ss_missing": "O UE4SS ainda não está instalado neste servidor.",
    "mods.ue4ss_install": "Instalar o UE4SS",
    "mods.ue4ss_log": "Fim do log do UE4SS",
    "mods.ue4ss_config_help":
        "Instalado sem console e sem os mods de trapaça que vêm com ele: só os carregadores de mod "
        "de blueprint ficam ligados. Cada mod é uma pasta em <code>{folder}</code>, ligada no "
        "<code>mods.txt</code> da mesma pasta, pela <a href=\"{url}\">tela Arquivos</a>.",
    "mods.source_ue4ss": "UE4SS (carregador)",
    "mods.not_proven":
        "Este instalador ainda NÃO foi testado num servidor de verdade. Faça backup do mundo antes "
        "(tela Backups) e confira o servidor depois de instalar.",
    "mods.help_satisfactory":
        "Mods do Satisfactory rodam no <strong>SML</strong> (Satisfactory Mod Loader). O painel "
        "baixa do ficsit.app o pacote de servidor Linux de cada mod e das dependências dele, "
        "confere o sha256 e o antivírus, e põe cada um numa pasta em <code>{folder}</code>. "
        "Todo jogador precisa dos MESMOS mods no jogo (pelo Satisfactory Mod Manager).",
    "mods.help_valheim":
        "Mods do Valheim rodam no <strong>BepInEx</strong>, instalado do Thunderstore. No servidor "
        "Linux ele entra por variáveis do systemd (um drop-in), sem trocar o script de partida.",
    "mods.help_rust":
        "Plugins do Rust rodam no <strong>Oxide</strong> (uMod). Ele SOBRESCREVE arquivos do jogo, "
        "e o painel guarda os originais para poder desligar. <strong>Toda atualização do Rust "
        "apaga o Oxide</strong>: reinstale depois de atualizar. Os plugins são <code>.cs</code> "
        "em <code>{folder}</code>, e entram sem reiniciar.",
    "mods.sml_title": "SML (Satisfactory Mod Loader)",
    "mods.sml_missing": "O SML ainda não está instalado. Ele também vem sozinho com o primeiro mod.",
    "mods.sml_install": "Instalar o SML",
    "mods.sml_mod_label": "Instalar mod do ficsit.app",
    "mods.sml_mod_help": (
        "A referência do mod (RefinedPower) ou o link da página dele no ficsit.app. As dependências "
        "vêm junto."),
    "mods.sml_bad_ref": "Não reconheci o mod: use a referência (RefinedPower) ou o link ficsit.app/mod/...",
    "mods.oxide_title": "Oxide (carregador de plugins)",
    "mods.oxide_missing": "O Oxide ainda não está instalado neste servidor.",
    "mods.oxide_install": "Instalar o Oxide",
    "mods.oxide_wiped": "Parte dos arquivos do Oxide foi trocada (o Rust foi atualizado?): reinstale.",
    "mods.oxide_log": "Fim do log do Oxide",
    "mods.source_ficsit": "ficsit.app",
    "mods.source_reforger_workshop": "Workshop do Arma Reforger",
    "mods.help_workshop_dst":
        "No Don't Starve Together quem baixa os mods é o <strong>próprio servidor</strong>, da Steam "
        "Workshop, na subida. O painel escreve a lista no <code>dedicated_server_mods_setup.lua</code> "
        "(o que baixar) e no <code>modoverrides.lua</code> de cada shard (o que ligar); as opções que "
        "você já deu a um mod ficam. Todo jogador recebe os mods sozinho ao entrar.",
    "mods.help_workshop_zomboid":
        "No Project Zomboid quem baixa os mods é o <strong>próprio servidor</strong>, da Steam Workshop, "
        "na subida. São duas listas no <code>.ini</code> do servidor: os IDs da Workshop (o que baixar) "
        "e os IDs de mod (o que ligar). Um item da Workshop pode trazer vários mods: depois de baixar, "
        "a tela mostra os que ele trouxe.",
    "mods.help_workshop_unturned":
        "No Unturned quem baixa os mods é o <strong>próprio servidor</strong>, da Steam Workshop, na "
        "subida, pelo <code>WorkshopDownloadConfig.json</code> da pasta do servidor. Mapa e mod vêm "
        "com as dependências. O comando do jogo precisa de <code>+InternetServer/&lt;nome&gt;</code>.",
    "mods.help_workshop_reforger":
        "No Arma Reforger quem baixa os mods é o <strong>próprio servidor</strong>, do workshop da "
        "Bohemia, na subida, pela lista <code>game.mods</code> do JSON passado em <code>-config</code>. "
        "O ID é o GUID de 16 caracteres da página do mod. Versão fixada à mão na config fica.",
    "mods.workshop_antivirus_note":
        "Aqui o antivírus NÃO verifica antes: quem baixa é o servidor do jogo, na subida. Use o "
        "<strong>Verificar mods instalados</strong> depois, que passa o ClamAV na pasta onde o jogo "
        "guarda o que baixou.",
    "mods.workshop_title": "Mods da Workshop",
    "mods.workshop_config": "Config: <code>{path}</code>",
    "mods.workshop_problem_no_cluster":
        "Nenhum cluster com server.ini: suba o servidor uma vez para ele criar a configuração.",
    "mods.workshop_problem_no_config":
        "A config do servidor ainda não existe: suba o servidor uma vez para ele criá-la.",
    "mods.workshop_problem_no_server_name":
        "Sem o nome do servidor: ponha +InternetServer/<nome> no comando do jogo (tela Editar) e suba "
        "uma vez.",
    "mods.workshop_problem_no_config_arg":
        "O servidor não recebe -config no comando: crie o config.json e passe -config no comando do "
        "jogo (tela Editar).",
    "mods.workshop_problem_bad_json": "A config do servidor não é um JSON válido: corrija na tela Arquivos.",
    "mods.workshop_dst_setup_missing":
        "Estes mods não estão no dedicated_server_mods_setup.lua (um update do jogo o reescreve) e "
        "não serão baixados: salve a lista de novo. {ids}",
    "mods.workshop_zomboid_found": "Mods neste item: {mods}",
    "mods.workshop_downloaded": "baixado",
    "mods.workshop_pending": "baixa na próxima subida",
    "mods.workshop_ids_label": "Mods (um por linha)",
    "mods.workshop_ids_help":
        "O link da página do mod na Steam Workshop ou só o número. Tirar uma linha remove o mod.",
    "mods.workshop_reforger_help":
        "O link da página do mod no workshop do Reforger, ou o GUID seguido do nome. Tirar uma linha "
        "remove o mod.",
    "mods.zomboid_mods_label": "Mods ligados (Mods=)",
    "mods.zomboid_mods_help":
        "Os IDs de mod separados por ponto e vírgula, como na lista que a tela mostra depois de baixar.",
    "mods.workshop_save": "Salvar a lista",
    "mods.help_workshop_ark":
        "No ARK: Survival Ascended quem baixa os mods é o <strong>próprio servidor</strong>, do "
        "CurseForge, na subida. A lista vai no comando do servidor (<code>-mods=</code>), por um "
        "ajuste do systemd que o painel escreve; o <code>ActiveMods</code> do "
        "GameUserSettings.ini é ignorado pelo jogo. Todo jogador precisa dos mesmos mods.",
    "mods.help_workshop_conan":
        "No Conan Exiles o servidor <strong>não baixa mod nenhum</strong>: o container baixa cada "
        "item da Steam Workshop, o antivírus verifica e só então os arquivos vão para "
        "<code>ConanSandbox/Mods</code>, na ordem da lista (o <code>modlist.txt</code>). Use os "
        "itens marcados como Enhanced: os antigos (Legacy) são ignorados, e um mod desatualizado "
        "para a versão do jogo impede o servidor de subir.",
    "mods.source_curseforge": "CurseForge",
    "mods.workshop_ark_help":
        "O Project ID do mod no CurseForge (o número na lateral da página do mod), um por linha. "
        "Tirar uma linha remove o mod.",
    "mods.workshop_ark_base_changed":
        "O comando do servidor mudou depois que a lista de mods foi salva (um redeploy?): o "
        "servidor ainda sobe com o comando antigo. Salve a lista de novo para usar o novo.",
    "mods.workshop_conan_modlist_off":
        "O ServerModList está desligado no ServerSettings.ini: os mods não carregam. Salve a "
        "lista de novo para religá-lo.",
    "mods.workshop_rejected": "O servidor recusou este mod: {reason}",
    "mods.workshop_rejected_badge": "recusado",
    "mods.workshop_refresh":
        "Baixar de novo todos os mods (para pegar as atualizações depois de um update do jogo)",
    "mods.workshop_problem_root_dropin":
        "A lista de mods foi gravada como root antes da migração do servidor, e sem root ela não pode "
        "ser mudada. Rode deploy/game/migrate-ct.ps1 de novo neste CT: ele converte a lista.",
    "mods.workshop_problem_no_win_run":
        "O comando do servidor não passa pelo win-run, que é por onde a lista chega ao jogo sem root.",
    "mods.workshop_problem_no_overlay":
        "Este CT ainda não foi preparado para mods sem root: rode deploy/game/migrate-ct.ps1 de novo nele.",
    "mods.workshop_problem_no_unit":
        "Não achei o comando do servidor no systemd: confira o nome do serviço na tela Editar.",
    "mods.workshop_bad_ids": "Não achei nenhum ID de mod no que foi colado: nada foi mudado.",
    "mods.zomboid_bad_mods": "A lista Mods= só aceita letras, números, _ . - e ponto e vírgula.",
    "mods.source_umod": "uMod (plugins)",
    "mods.ue4ss_linux_config_help":
        "Port Linux do UE4SS, ligado por LD_PRELOAD no serviço, sem console "
        "nem janela. Cada mod é uma pasta em <code>{folder}</code>, ligada no <code>mods.txt</code> "
        "dali, pela <a href=\"{url}\">tela Arquivos</a>. Só mods em Lua ou <code>.so</code> de Linux: "
        "<code>.dll</code> de Windows não carrega.",
    "mods.source_ue4ss_linux": "UE4SS para Linux (jogos testados)",
    "mods.ue4ss_release":
        "Versão fixa do UE4SS para Linux: {tag}. Se o servidor traz o .sym, o layout do jogo é "
        "gerado dele a cada instalação - depois de um update do jogo, instale de novo.",
    "mods.ue4ss_old_layout":
        "Ainda há a instalação antiga do UE4SS (o fork anterior) ao lado do executável: instale de "
        "novo para passar os mods Lua para a pasta ue4ss/ e tirar os arquivos dela.",
    "mods.bad_name": "{name} não é aceito aqui. Esperado: {allowed}.",

    # --------------------------------------------- game catalog
    "catalog.title": "Catálogo de jogos",
    "catalog.game": "Jogo",
    "catalog.creatable": "criável",
    "catalog.manual": "manual",
    "catalog.ports": "Portas",
    "catalog.shifted_port": "porta sorteada",
    "catalog.shifted_port_help":
        "O broker sorteia as portas numa faixa própria dele; as listadas aqui são só as padrão do "
        "jogo",
    "catalog.empty": "Catálogo vazio (ou o broker não respondeu).",
    "catalog.curated_vs_dynamic":
        "<strong>curado</strong>: vem dos arquivos <code>games/*.env</code> do repositório. "
        "<strong>dinâmico</strong>: adicionado por aqui. Jogo que exige conta Steam ou instalador "
        "próprio continua sendo criado pelo <code>deploy-game.ps1</code>.",
    "catalog.add_game": "Adicionar jogo",
    "catalog.data_only":
        "Só dados: o broker <strong>não aceita comandos</strong>. O que precisa de instalação "
        "especial (Wine, Proton, symlink do Steam) entra pelas receitas abaixo.",
    "catalog.search_game": "Buscar jogo",
    "catalog.by_name_or_app_id": "(nome ou App ID)",
    "catalog.search_hint":
        "Preenche App ID, portas e comando de start a partir do LinuxGSM, dos eggs do Pterodactyl "
        "e de uma lista do painel. É só sugestão: confira antes de enviar.",
    "catalog.start_from_template": "Começar de um modelo",
    "catalog.blank": "Em branco",
    "catalog.template_hint":
        "Jogo que a busca não acha? Escolha o motor dele: o modelo preenche portas, caminhos, "
        "argumentos e o padrão do log de uma vez.",
    "catalog.search_filled": "campos preenchidos. Confira antes de enviar.",
    "catalog.search_in_catalog": "já está no catálogo",
    "catalog.search_none":
        "Nenhuma sugestão para esse nome. Comece de um modelo abaixo (pelo motor do jogo) e "
        "procure o App ID do servidor dedicado e as portas:",
    "catalog.search_steamdb": "App ID no SteamDB",
    "catalog.search_web_ports": "Portas na web",
    "catalog.search_failed": "Não consegui buscar:",
    "catalog.recipes_hint":
        "Servidor só de Windows: marque <strong>proton</strong> (o preferido; <strong>wine</strong> "
        "só se o Proton não funcionar), <strong>xvfb</strong> se ele criar janela ao subir e "
        "<strong>vulkan</strong> se ele cair no Direct3D 12 sem placa de vídeo.",
    "catalog.template.unreal_linux": "Unreal Engine (servidor nativo Linux)",
    "catalog.template.unreal_linux_help":
        "Palworld, Satisfactory, Dragonwilds e a maioria dos jogos Unreal com build Linux. Troque "
        "{project} pela pasta do projeto (a que aparece em /opt/game depois de instalar) e ponha "
        "o App ID do servidor dedicado.",
    "catalog.template.unreal_windows": "Unreal Engine (só Windows, via Proton)",
    "catalog.template.unreal_windows_help":
        "Servidor Unreal sem build Linux (Icarus, Abiotic Factor, Conan). Troque {project} pela "
        "pasta do projeto nos caminhos e no executável Shipping, que é o que abre a porta.",
    "catalog.template.unity_linux": "Unity (servidor nativo Linux)",
    "catalog.template.unity_linux_help":
        "Troque {executable} pelo executável .x86_64 da raiz do jogo. Confira no guia do jogo "
        "como ele recebe a porta: a Unity não tem um argumento padrão para isso.",
    "catalog.template.unity_windows": "Unity (só Windows, via Proton)",
    "catalog.template.unity_windows_help":
        "Servidor Unity sem build Linux (V Rising, Sons of the Forest). Troque {executable} pelo "
        ".exe da raiz. Vem com X virtual (xvfb): servidor Unity costuma criar janela ao subir.",
    "catalog.template.source": "Source / srcds (Valve)",
    "catalog.template.source_help":
        "Jogos da Valve e mods (srcds_run). Troque {mod} pela pasta do jogo (cstrike, tf, garrysmod) "
        "e MAPA por um mapa que exista.",
    "catalog.key": "Chave",
    "catalog.key_example": "meujogo",
    "catalog.key_hint": "Minúsculas, números e hífen. Vira o nome do container e do serviço.",
    "catalog.name": "Nome",
    "catalog.name_example": "Meu Jogo",
    "catalog.app_id": "App ID do servidor dedicado (Steam)",
    "catalog.client_app_id": "App ID do jogo (cliente)",
    "catalog.client_app_id_hint":
        "Só para servidor de Windows sem <code>steam_appid.txt</code> ao lado do executável "
        "(Conan Exiles: 440900). Sem ele o servidor responde à Steam com appid 0 e não aparece na"
        " lista de servidores do jogo. Em branco na maioria dos jogos.",
    "catalog.suggestion.ark_ascended.vulkan":
        "Mesmo sem tela, o servidor cria um dispositivo Direct3D 12: sem o X virtual (xvfb) e sem"
        " o driver Vulkan por software (vulkan) ele cai ao subir.",
    "catalog.suggestion.conan_exiles.xvfb_appid":
        "Sem o X virtual (xvfb) o servidor trava logo depois de montar os arquivos do jogo. O App"
        " ID do cliente (440900) é o que faz ele aparecer na lista de servidores.",
    "catalog.app_id_hint": "O do <strong>servidor dedicado</strong>, não o do jogo. Consulte o SteamDB.",
    "catalog.ports_hint": "Porta/protocolo, separadas por espaço. Abaixo de 1024 não é permitido.",
    "catalog.game_port": "Porta do jogo",
    "catalog.query_port": "Porta de consulta",
    "catalog.extra_port": "Porta extra",
    "catalog.example": "ex.: {value}",
    "catalog.optional": "(opcional)",
    "catalog.start_script": "Script de start",
    "catalog.start_args": "Argumentos",
    "catalog.start_args_hint":
        "Use <code>{PORT}</code>, <code>{QUERY_PORT}</code> e <code>{EXTRA_PORT}</code>. Nada de "
        "<code>; | &amp; $</code>.",
    "catalog.memory_mb": "Memória (MB)",
    "catalog.cpus": "CPUs",
    "catalog.disk_gb": "Disco (GB)",
    "catalog.config_folder": "Pasta de configuração",
    "catalog.config_folder_hint": "Caminho absoluto sob <code>/opt/game</code> ou <code>/home/steam</code>.",
    "catalog.config_files": "Arquivos de configuração",
    "catalog.one_per_line": "(um por linha)",
    "catalog.one_per_line_f": "(uma por linha)",
    "catalog.backup_paths": "Pastas de backup",
    "catalog.player_count": "Contagem de jogadores",
    "catalog.by_server_log": "Pelo log do servidor",
    "catalog.by_steam_query": "Consulta Steam (A2S)",
    "catalog.platform": "Plataforma",
    "catalog.linux_default": "Linux (padrão)",
    "catalog.windows_needs_wine": "Windows (exige Proton ou Wine)",
    "catalog.log_join_line": "Log: linha de entrada",
    "catalog.log_leave_line": "Log: linha de saída",
    "catalog.install_recipes": "Receitas de instalação",
    "catalog.broker_picks_ports": "O broker sorteia as portas (várias instâncias do mesmo jogo)",
    "catalog.broker_picks_ports_hint":
        "Só marque se o jogo aceita as portas pelos argumentos: os argumentos de start precisam "
        "ter {PORT} (e {QUERY_PORT} e {EXTRA_PORT}, se houver porta de consulta e porta extra) e o "
        "jogo só pode ter essas três portas.",
    "catalog.key_fixed_hint":
        "A chave não muda: ela é o nome do jogo no broker. Para trocar, apague e adicione de "
        "novo.",
    "catalog.edited": "editado",
    "catalog.edited_help":
        "Os dados foram editados pelo painel e valem por cima do arquivo games/*.env do "
        "repositório.",
    "catalog.edit": "Editar",
    "catalog.delete": "Apagar",
    "catalog.delete_confirm": "Apagar {name} do catálogo? As instâncias já criadas continuam.",
    "catalog.undo_edit": "Desfazer edição",
    "catalog.undo_edit_confirm": "Descartar a edição de {name} e voltar ao arquivo do repositório?",
    "catalog.edit_title": "Editar {name}",
    "catalog.curated_edit_note": (
        "Jogo <strong>curado</strong>: a edição fica guardada no broker, por cima de "
        "<code>games/{game}.env</code>. Os comandos de instalação continuam os do arquivo; "
        "para voltar a ele, use <strong>Desfazer edição</strong> no catálogo."),
    "catalog.edit_instances_note": "Vale para as próximas instâncias. As já criadas não mudam.",
    "catalog.save": "Salvar",
    "catalog.add_to_catalog": "Adicionar ao catálogo",

    # ------------------------------------------ server registration
    "server_form.title_new": "Adicionar servidor",
    "server_form.title_edit": "Editar servidor",
    "server_form.optional": "(opcional)",
    "server_form.one_per_line": "(um por linha)",
    "server_form.one_per_line_optional": "(um por linha, opcional)",
    "server_form.name": "Nome",
    "server_form.name_hint": "Como o servidor aparece no painel. Ex.: <code>Dragonwilds</code>",
    "server_form.host": "Host",
    "server_form.host_hint": "IP ou hostname do container do jogo. O painel se conecta nele por SSH.",
    "server_form.ssh_user": "Usuário SSH",
    "server_form.ssh_port": "Porta SSH",
    "server_form.systemd_service": "Serviço systemd",
    "server_form.service_hint":
        "Normalmente <code>&lt;nome-do-jogo&gt;.service</code>. O <code>.service</code> é "
        "adicionado se faltar.",
    "server_form.game_ports": "Portas do jogo",
    "server_form.game_ports_hint": "Apenas informativo, para lembrar o que redirecionar no roteador.",
    "server_form.query_port": "Porta de consulta",
    "server_form.query_port_hint": "Porta de query Steam (A2S). Palworld: <code>27015</code>.",
    "server_form.player_count": "Contagem de jogadores",
    "server_form.count_off": "Desligada",
    "server_form.count_a2s": "Consulta Steam (A2S) na porta acima",
    "server_form.count_http": "API HTTP do jogo (dá os nomes)",
    "server_form.count_log": "Pelo log do servidor",
    "server_form.player_count_hint":
        "Jogo que não publica nada na rede (RuneScape Dragonwilds, por exemplo) só dá para contar "
        "pelo log.",
    "server_form.player_count_wizard":
        "O <a href=\"{url}\">assistente</a> testa as portas UDP e TCP, monta a chamada da API e "
        "acha os padrões do log para você.",
    "server_form.log_join": "Log: linha de entrada",
    "server_form.log_leave": "Log: linha de saída",
    "server_form.log_file": "Log: arquivo",
    "server_form.log_file_hint":
        "Em branco lê a saída do serviço. Preenchido, lê esse arquivo &mdash; é como se alcança o "
        "nome do jogador em jogos que só o escrevem em log próprio (DayZ).",
    "server_form.log_error": "Log: linha de erro",
    "server_form.log_error_hint":
        "Liga o alerta <strong>Erro no log do jogo</strong> em <a href=\"{url}\">Alertas</a>: o "
        "painel procura esta expressão no fim do log e avisa quando ela aparece. Em branco, nem a "
        "leitura acontece. Comece estreito &mdash; um padrão largo demais transforma o canal em "
        "cópia do log.",
    "server_form.api_url": "API: URL",
    "server_form.api_url_hint": "Chamada de dentro do container, por SSH. Palworld: porta <code>8212</code>.",
    "server_form.api_auth": "API: autenticação",
    "server_form.api_auth_hint":
        "<code>basic:usuario:senha</code>, <code>bearer:token</code> ou <code>header:Nome: "
        "valor</code> (TeamSpeak: <code>header:x-api-key: SUA-CHAVE</code>). Fica em texto puro no "
        "banco.",
    "server_form.api_body": "API: corpo JSON",
    "server_form.api_body_hint": "Preenchido vira <code>POST</code>; vazio é <code>GET</code>.",
    "server_form.api_paths": "API: caminho da lista / da contagem",
    "server_form.api_paths_hint": "Vazios: o painel procura sozinho na resposta.",
    "server_form.config_folder": "Pasta de configuração",
    "server_form.config_folder_hint":
        "Onde a tela <strong>Arquivos</strong> abre por padrão. Ex.: "
        "<code>/opt/game/Pal/Saved/Config/LinuxServer</code>",
    "server_form.config_files": "Arquivos de configuração",
    "server_form.config_files_hint":
        "Informe aqui o arquivo que você edita de verdade: a tela <strong>Config</strong> abre ele "
        "direto como formulário (um campo por chave, com botão para acrescentar chave nova) "
        "&mdash; sem navegar por pastas. Em branco, a própria tela ajuda a procurar os candidatos "
        "no container.",
    "server_form.config_files_hint_link":
        "Informe aqui o arquivo que você edita de verdade: a tela <a "
        "href=\"{url}\"><strong>Config</strong></a> abre ele direto como formulário (um campo por "
        "chave, com botão para acrescentar chave nova) &mdash; sem navegar por pastas. Em branco, "
        "a própria tela ajuda a procurar os candidatos no container.",
    "server_form.backup_paths": "Caminhos de backup",
    "server_form.backup_paths_hint":
        "O que a tela <strong>Backups</strong> guarda no <code>.tar.gz</code>. Em branco vale a "
        "<strong>pasta de configuração</strong> acima. Aponte a pasta do <strong>save</strong>, "
        "não a raiz do jogo: <code>/opt/game</code> inteiro leva dezenas de GB de binário que o "
        "SteamCMD rebaixa de graça.",
    "server_form.backup_paths_hint_link":
        "O que a tela <a href=\"{url}\"><strong>Backups</strong></a> guarda no "
        "<code>.tar.gz</code>. Em branco vale a <strong>pasta de configuração</strong> acima. "
        "Aponte a pasta do <strong>save</strong>, não a raiz do jogo: <code>/opt/game</code> "
        "inteiro leva dezenas de GB de binário que o SteamCMD rebaixa de graça.",
    "server_form.notes": "Notas",
    "server_form.cancel": "Cancelar",
    "server_form.sshd_note":
        "O container precisa ter <code>sshd</code> rodando e a chave do painel autorizada — veja "
        "<a href=\"{url}\">Acesso SSH</a>.",
    "server_form.remove": "Remover do painel",
    "server_form.remove_hint": "Apaga apenas o cadastro. O container e os arquivos do jogo não são tocados.",
    "server_form.remove_confirm": "Remover este servidor do painel?",

    # ------------------------------------------ titles and components
    # ------------------------- error page and permission barrier
    # Text that used to be a literal inside `abort(...)` and `errors.append(...)`: it went
    # through `translate` and came back unchanged, so the English screen showed Portuguese.
    # See "Texto fixo devolvido por funcao nao traduz" in CLAUDE.md.
    "error.csrf_invalid": "Token CSRF inválido ou expirado — recarregue a página.",
    "error.terminal_session_gone": "Sessão de terminal expirada ou encerrada.",
    "error.terminal_bad_input": "Entrada inválida.",
    "error.terminal_bad_size": "Tamanho inválido.",
    "error.download_too_large":
        "Arquivo de {size} bytes acima do limite de download ({limit} bytes) — use scp para este.",
    "error.not_found": "Página não encontrada.",
    "error.admin_only": "Esta tela é restrita a administradores do painel.",
    "error.job_admin_only": "Este registro é de uma ação restrita a administradores do painel.",
    "error.terminal_disabled": "O terminal está desabilitado (GAMEPANEL_ALLOW_SHELL=0).",
    "error.terminal_no_pty": "Terminal indisponível: este sistema não tem PTY.",
    "error.console_disabled": "O console está desabilitado (GAMEPANEL_ALLOW_SHELL=0).",
    "error.files_disabled": "O editor de arquivos está desabilitado (GAMEPANEL_ALLOW_FILES=0).",
    "error.broker_disabled": "O broker está desligado neste painel (GAMEPANEL_ALLOW_BROKER=0).",
    "error.operator_reads_registered_only":
        "Operador só abre os arquivos de configuração já registrados neste servidor.",
    "error.operator_saves_registered_only":
        "Operador só salva os arquivos de configuração já registrados neste servidor.",
    "error.upload_too_large":
        "Arquivo grande demais para o envio (limite de {limit}). Para mandar um maior, suba o "
        "GAMEPANEL_UPLOAD_MAX do painel — conferindo antes se há esse espaço livre no container "
        "do painel.",
    "error.content_too_large": "Conteúdo grande demais (o editor aceita até {kb} KB por arquivo).",

    # ------------------------------------- form validation
    "flash.server_duplicate": "Já existe um servidor cadastrado em {host}.",
    "flash.username_invalid":
        "Nome de usuário inválido: use de 1 a 32 caracteres entre letras minúsculas, números, "
        "'-' e '_', começando por letra ou '_'.",
    "flash.role_invalid": "Papel inválido.",
    "flash.schedule_pick_action": "Escolha o que a tarefa deve fazer.",
    "flash.schedule_pick_kind": "Escolha quando a tarefa deve rodar.",
    "flash.schedule_bad_time": "Horário inválido (use hora 0-23 e minuto 0-59).",
    "flash.schedule_bad_interval": "Intervalo inválido (de 1 a {max} horas).",
    "account_2fa.qr_label": "QR code da verificação em duas etapas",

    "error.title": "Erro {code}",
    "job.title": "Ação #{id}",
    "account_2fa_codes.title": "Códigos de recuperação",
    "players_setup.title": "Contagem de jogadores",
    "server.sections_of_this_server": "Telas deste servidor",
    "server.measuring": "medindo recursos...",
    "server.server": "Servidor",

    # -------------------------------- button labels and confirmation
    "account.generate": "Gerar",
    "account.enable": "Ativar",
    "account.disable_confirm": "Desativar a verificação em duas etapas? O login volta a pedir só a senha.",
    "account.sign_out_of_panel": "Sair do painel",
    "account_2fa.open_in_app": "Abrir no aplicativo",
    "account_2fa_codes.saved_them": "Já guardei",
    "backups.back_up_now": "Fazer backup agora",
    "backups.restore": "restaurar",
    "backups.restore_confirm":
        "Restaurar {file} em {server}?\n\nO servidor será PARADO, os arquivos de agora serão "
        "substituídos e ele volta a subir. Uma cópia do estado atual é guardada antes.",
    "backups.delete_confirm": "Apagar {file}? Não tem volta.",
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
    "files.delete_confirm": "Apagar {path}? Isto não tem volta.",
    "history.filter": "Filtrar",
    "history.clear": "limpar",
    "history.newer": "mais recentes",
    "history.older": "mais antigas",
    "instances.create": "Criar instância",
    "instances.create_confirm":
        "Criar o container, instalar o jogo e abrir as portas no firewall? Isso pode levar vários "
        "minutos.",
    "instances.deactivate_confirm":
        "Desativar {name}? Primeiro o save é copiado para o painel; "
        "depois o servidor será PARADO e as portas fecham no firewall.",
    "instances.remove_confirm": "Remover {name}? O container e o jogo serão APAGADOS.",
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
        "Desligar a verificação em duas etapas de {user}? Ele entra só com a senha até ativar "
        "de novo.",
    "users.remove_confirm": "Remover o usuário {user}?",
    "users.create": "Criar",

    # ---------------------------------------- player count
    "players_setup.intro":
        "Três formas de saber quantos estão jogando, da melhor para a última: a <strong>API do "
        "jogo</strong> (dá os nomes), a <strong>consulta direta</strong> que o navegador de "
        "servidores usa (dá a contagem) e, quando o jogo não publica nada na rede, o <strong>log "
        "do servidor</strong>.",
    "players_setup.how_to_count": "Como contar",
    "players_setup.tab_udp": "1. Consulta direta (UDP)",
    "players_setup.tab_http": "2. API HTTP (TCP)",
    "players_setup.tab_log": "3. Pelo log",
    "players_setup.ports_tested": "Portas testadas",
    "players_setup.ports_tested_hint":
        "O painel leu de <code>/proc</code> quais portas UDP estão abertas dentro do container e "
        "<strong>qual processo abriu cada uma</strong>, e mandou um <code>A2S_INFO</code> em "
        "todas. As detectadas vêm primeiro; as marcadas como <em>chute</em> não estavam abertas e "
        "só servem para quando o servidor está parado.",
    "players_setup.port": "Porta",
    "players_setup.opened_by": "Aberta por",
    "players_setup.answer": "Resposta",
    "players_setup.server": "Servidor",
    "players_setup.address": "Endereço",
    "players_setup.status": "Status",
    "players_setup.kind": "Tipo",
    "players_setup.infra_not_the_game": "infra, não é o jogo",
    "players_setup.open_no_owner": "aberta, sem processo dono neste container",
    "players_setup.was_not_open": "não estava aberta (chute)",
    "players_setup.no_answer": "sem resposta",
    "players_setup.use_this": "Usar esta",
    "players_setup.no_port_to_test": "Nenhuma porta para testar.",
    "players_setup.no_udp_query_one":
        "<strong>Este jogo não publica consulta UDP.</strong> O processo do servidor abriu {n} "
        "porta UDP e ela não respondeu ao <code>A2S_INFO</code> &mdash; não é porta errada nem "
        "firewall: é porta do próprio jogo, e ela não fala o protocolo. A contagem que aparece no "
        "navegador do jogo, quando existe, vem do serviço da Steam/Epic e não do servidor. Confira "
        "a aba <a href=\"{url_http}\">API HTTP</a> (vários jogos trocaram a query UDP por uma API "
        "em TCP) e, se ali também não houver nada, a contagem só pode sair do <a "
        "href=\"{url_log}\">log</a>.",
    "players_setup.no_udp_query_many":
        "<strong>Este jogo não publica consulta UDP.</strong> O processo do servidor abriu {n} "
        "portas UDP e nenhuma respondeu ao <code>A2S_INFO</code> &mdash; não é porta errada nem "
        "firewall: são as portas do próprio jogo, e elas não falam o protocolo. A contagem que "
        "aparece no navegador do jogo, quando existe, vem do serviço da Steam/Epic e não do "
        "servidor. Confira a aba <a href=\"{url_http}\">API HTTP</a> (vários jogos trocaram a "
        "query UDP por uma API em TCP) e, se ali também não houver nada, a contagem só pode sair "
        "do <a href=\"{url_log}\">log</a>.",
    "players_setup.none_answered":
        "Nenhuma respondeu? Veja a aba <a href=\"{url}\">API HTTP</a> &mdash; vários jogos "
        "trocaram a query UDP por uma API de administração em TCP.",
    "players_setup.tcp_answered_http": "Portas TCP que responderam HTTP",
    "players_setup.tcp_hint":
        "O painel leu de <code>/proc</code> as portas TCP em <code>LISTEN</code> dentro do "
        "container e <strong>qual processo abriu cada uma</strong>, e bateu nelas por HTTP "
        "<strong>de dentro do próprio container</strong> &mdash; essas APIs costumam escutar só em "
        "<code>127.0.0.1</code>, e é assim que elas devem continuar. Um <code>401</code> também é "
        "um bom sinal: existe API ali, ela só quer senha. Confira a coluna &quot;Aberta por&quot;: "
        "se não for o processo do jogo, não é a API dele.",
    "players_setup.same_on_everything": "{status} em tudo",
    "players_setup.asks_for_password": "{status} pede senha",
    "players_setup.http_but_not_a_game_api": "fala HTTP, mas não é API de jogo",
    "players_setup.use_this_url": "Usar esta URL",
    "players_setup.no_tcp_answered_http": "Nenhuma porta TCP respondeu HTTP.",
    "players_setup.no_http_answer_on": "Sem resposta HTTP em:",
    "players_setup.no_game_api":
        "<strong>Nenhuma API de jogo respondeu.</strong> Quase sempre é porque ela vem "
        "<em>desligada</em> de fábrica e precisa ser ligada na configuração do servidor &mdash; a "
        "porta só passa a existir depois disso. No <strong>Palworld</strong>, no "
        "<code>PalWorldSettings.ini</code> (dentro de <code>OptionSettings=(...)</code>): "
        "<code>RESTAPIEnabled=True</code>, <code>RESTAPIPort=8212</code> e uma "
        "<code>AdminPassword</code> forte. Pare o servidor, edite, suba de novo e recarregue esta "
        "página. Se o jogo simplesmente não tem API (RuneScape Dragonwilds não tem), use a aba <a "
        "href=\"{url}\">Pelo log</a>.",
    "players_setup.test_the_call": "Testar a chamada",
    "players_setup.url": "URL",
    "players_setup.url_hint":
        "Sempre <code>127.0.0.1</code>: a chamada sai de dentro do container, pelo mesmo SSH do "
        "resto do painel. Não precisa abrir nada no roteador.",
    "players_setup.auth": "Autenticação",
    "players_setup.auth_hint":
        "<code>basic:usuario:senha</code>, <code>bearer:token</code> ou um cabeçalho "
        "<code>Authorization</code> pronto. Palworld: <code>basic:admin:</code> + a "
        "<code>AdminPassword</code> do <code>PalWorldSettings.ini</code>. Para API que autentica "
        "por outro cabeçalho, use <code>header:Nome: valor</code> &mdash; o TeamSpeak pede "
        "<code>header:x-api-key: SUA-CHAVE</code>.",
    "players_setup.json_body": "Corpo JSON",
    "players_setup.json_body_hint": "Preenchido, a chamada vira <code>POST</code>. Vazio, é um <code>GET</code>.",
    "players_setup.list_path": "Caminho da lista",
    "players_setup.count_path": "Caminho da contagem",
    "players_setup.auto_login": "Login automático",
    "players_setup.auto_login_hint":
        "Para APIs cujo token <strong>expira</strong> — a do Satisfactory é assim. Preenchendo "
        "estes três campos, o painel troca a senha por um token sozinho, guarda, e quando a API "
        "responder <code>401</code> ele refaz o login e repete a consulta. Deixe a "
        "<em>Autenticação</em> acima vazia: quem manda o cabeçalho passa a ser o token obtido "
        "aqui.",
    "players_setup.login_url": "URL de login",
    "players_setup.token_path": "Caminho do token",
    "players_setup.login_json_body": "Corpo JSON do login",
    "players_setup.login_json_body_hint":
        "Satisfactory: a senha é a de <strong>admin</strong> definida no cliente ao reivindicar o "
        "servidor. O corpo vai para a mesma API, sem cabeçalho de autenticação.",
    "players_setup.leave_paths_empty":
        "Deixe os dois caminhos vazios primeiro: o painel procura sozinho uma lista de jogadores "
        "e, se não achar, um número em chaves conhecidas (<code>currentplayernum</code>, "
        "<code>numPlayers</code>, ...). Só preencha se ele errar &mdash; a resposta crua aparece "
        "abaixo para você ver o nome certo do campo.",
    "players_setup.test": "Testar",
    "players_setup.result": "Resultado:",
    "players_setup.players_count": "jogador(es)",
    "players_setup.players_online_now": "jogador(es) online agora",
    "players_setup.raw_api_answer": "Resposta crua da API",
    "players_setup.use_this_api": "Usar esta API",
    "players_setup.password_in_plain_text":
        "A senha da API fica guardada no banco do painel em texto puro (e ela precisa ir no "
        "cabeçalho de cada chamada). Trate <code>panel.db</code> como segredo.",
    "players_setup.log_lines_that_look_like": "Linhas do log que parecem de entrada/saída",
    "players_setup.find_the_lines":
        "Ache a linha que aparece quando alguém entra e a que aparece quando alguém sai, e escreva "
        "os padrões abaixo. Use <code>(?P&lt;name&gt;.+)</code> onde estiver o nome do jogador "
        "&mdash; com o nome nos dois padrões o painel lista quem está online; sem ele, mostra só a "
        "contagem.",
    "players_setup.no_join_leave_lines": "Nenhuma linha com palavras de entrada/saída no log desta execução.",
    "players_setup.test_the_pattern": "Testar o padrão",
    "players_setup.log_file": "Arquivo de log",
    "players_setup.log_file_hint":
        "Em branco, o painel lê a saída do serviço (<code>journalctl</code>) &mdash; é onde a "
        "maioria dos jogos anuncia. Alguns só escrevem o <strong>nome</strong> de quem entra num "
        "arquivo próprio: o <strong>DayZ</strong> é assim (<code>/opt/game/profiles/*.ADM</code>, "
        "já ligado pelo <code>-adminlog</code> do nosso deploy). O <code>*</code> vale, e o painel "
        "pega sempre o arquivo mais novo.",
    "players_setup.join_line": "Linha de entrada",
    "players_setup.leave_line": "Linha de saída",
    "players_setup.last_matching_lines": "Últimas linhas que casaram com os padrões:",
    "players_setup.no_line_matched": "Nenhuma linha casou com os padrões — confira a grafia.",
    "players_setup.use_these_patterns": "Usar estes padrões",

    # --------------------------------------------- alert events
    "event.server_stopped": "Servidor parou de rodar",
    "event.server_back": "Servidor voltou a rodar",
    "event.game_failed": "Jogo quebrou (serviço em 'failed')",
    "event.restart_loop": "Jogo caindo em loop de restart",
    "event.game_mute": "Jogo não responde (de pé, mas mudo)",
    "event.game_answering": "Jogo voltou a responder",
    "event.player_joined": "Jogador conectou",
    "event.player_left": "Jogador desconectou",
    "event.log_error": "Erro no log do jogo",
    "event.lost_contact": "Painel perdeu contato (SSH)",
    "event.contact_back": "Contato restabelecido",
    "event.scheduled_task_failed": "Tarefa agendada falhou",
    "event.disk_almost_full": "Disco quase cheio",
    "event.memory_almost_full": "Memória quase cheia",
    "event.cpu_high": "Uso de CPU alto",

    # ----------------------------------- action names in the history
    "job.shell": "Comando no container",
    "job.terminal": "Terminal interativo",
    "job.file_saved": "Arquivo salvo",
    "job.file_deleted": "Arquivo apagado",
    "job.config_changed": "Configuração alterada",
    "job.file_downloaded": "Arquivo baixado",
    "job.mod_loader": "Carregador de mods",
    "job.mod_installed": "Mod instalado",
    "job.mod_workshop": "Lista de mods da Workshop trocada",
    "job.mod_audited": "Mods verificados (antivírus)",
    "job.mod_removed_plugin": "Mod desinstalado",
    "job.mod_uploaded": "Mod enviado",
    "job.mod_deleted": "Mod removido",
    "job.file_uploaded": "Arquivo enviado",
    "job.backup": "Backup",
    "job.backup_restored": "Backup restaurado",
    "job.backup_deleted": "Backup apagado",
    "backups.stored_both_html":
        "Guardado como <code>.tar.gz</code> em <code>{dir}</code>, dentro do próprio container, "
        "e uma segunda cópia vai para o painel.",
    "backups.panel_copies": "Cópias no painel",
    "backups.panel_copies_help":
        "Ficam no painel mesmo que o servidor ou a instância seja removido. Um servidor novo do "
        "mesmo jogo enxerga estas cópias e pode restaurar a partir delas.",
    "backups.panel_keep": "As {n} mais novas ficam; as antigas saem sozinhas.",
    "backups.panel_keep_all": "Nenhuma cópia é apagada automaticamente.",
    "backups.panel_none":
        "Nenhuma cópia no painel ainda. Os próximos backups vêm para cá sozinhos; os antigos do "
        "container podem ser enviados pelo botão \"enviar ao painel\".",
    "backups.in_panel": "no painel",
    "backups.in_panel_title": "Já existe uma cópia deste arquivo no painel",
    "backups.send_to_panel": "enviar ao painel",
    "backups.panel_restore_confirm":
        "Restaurar {file} (cópia do painel) em {server}? O servidor será PARADO, a cópia volta ao "
        "container e substitui o save atual. Uma cópia de segurança é tirada antes.",
    "backups.panel_delete_confirm":
        "Apagar {file} do painel? Se o container "
        "já não existir, esta pode ser a única cópia.",
    "instances.installing": "Instalação em andamento",
    "instances.installing_help":
        "A criação continua mesmo que você saia "
        "desta tela; o log mostra em que fase ela está.",
    "instances.view_log": "Ver log",
    "instances.cancel_install": "Cancelar instalação",
    "instances.cancel_confirm":
        "Cancelar a instalação de {name}? O container criado será APAGADO e o IP, o CT e as portas "
        "voltam a ficar livres.",
    "instances.confirm_title": "Confirmar a nova instância",
    "instances.confirm_intro":
        "Conferido agora no Proxmox e no OPNsense. Nada foi reservado ainda: se outra criação "
        "acontecer antes de você confirmar, os números podem mudar.",
    "instances.confirm_game": "Jogo",
    "instances.confirm_name": "Nome",
    "instances.confirm_ct": "Container (CT)",
    "instances.confirm_ip": "IP",
    "instances.confirm_ports": "Portas",
    "instances.confirm_create": "Criar agora",
    "instances.back": "Voltar",
    "flash.install_cancelling": "Cancelamento pedido: a instalação para e o container é apagado. Acompanhe no log.",
    "flash.install_already_finished": "Essa instalação já terminou; não há o que cancelar.",
    "instances.deactivate_no_backup": "Desativar sem backup",
    "instances.deactivate_no_backup_confirm": "Desativar {name} SEM copiar o save para o painel?",
    "instances.panel_copies": "Cópias do save no painel: {n} (a mais nova em {when}).",
    "instances.panel_copies_none": "Nenhuma cópia do save no painel: remover apaga o jogo sem volta.",
    "flash.panel_backup_deleted": "Cópia {file} apagada do painel.",
    "flash.deactivate_without_backup":
        "Esta instância não tem servidor no painel com caminhos de backup: foi desativada SEM cópia do save.",
    "job.backup_sent_to_panel": "Backup enviado ao painel",
    "job.player_action": "Ação sobre jogador",
    "job.instance_created": "Instância criada (broker)",
    "job.instance_deactivated": "Instância desativada (broker)",
    "job.instance_removed": "Instância removida (broker)",
    "job.game_edited": "Jogo do catálogo editado",
    "job.game_removed": "Jogo apagado do catálogo (ou edição desfeita)",
    "job.game_added": "Jogo adicionado ao catálogo",
    "player_action.announce": "Avisar todo mundo",
    "player_action.kick": "Expulsar",
    "player_action.ban": "Banir",

    # ---------------------------------------- flash messages
    "flash.two_factor_required_here": "Este painel exige a verificação em duas etapas: ative-a para continuar.",
    "flash.too_many_tries": "Muitas tentativas. Tente de novo em {n}s.",
    "flash.bad_credentials": "Usuário ou senha inválidos.",
    "flash.verification_expired": "A verificação expirou. Entre de novo.",
    "flash.code_invalid_or_used": "Código inválido ou já usado.",
    "flash.bad_port": "Porta inválida.",
    "flash.count_on_by_query": "Contagem de jogadores ligada pela consulta na porta {port}/udp.",
    "flash.need_api_url": "Informe a URL da API.",
    "flash.count_on_by_api_login": "Contagem ligada pela API, com login automático (o token renova sozinho).",
    "flash.count_on_by_api": "Contagem de jogadores ligada pela API HTTP do servidor.",
    "flash.need_join_pattern": "Informe o padrão da linha de entrada.",
    "flash.count_on_by_log": "Contagem de jogadores ligada pelo log do servidor.",
    "flash.bad_choice": "Escolha inválida.",
    "flash.could_not": "Não consegui: {reason}",
    "flash.player_action_done": "{label}: {who}.",
    "flash.notice_sent": "Aviso enviado: {message}",
    "flash.server_added": "Servidor {name} cadastrado.",
    "flash.server_updated": "Servidor atualizado.",
    "flash.server_removed": "Servidor removido do painel (o container não foi tocado).",
    "flash.type_a_command": "Digite um comando.",
    "flash.command_too_long": "Comando muito longo (limite de {n} caracteres).",
    "flash.file_too_big": "Arquivo grande demais para salvar (limite de {kb} KB).",
    "flash.file_over_edit_limit":
        "{path} tem {size} KB e passou do limite de edição ({kb} KB). Nada foi gravado — baixe o "
        "arquivo para mexer nele.",
    "flash.file_saved": "{path} salvo ({bytes} bytes). Uma cópia .bak foi guardada ao lado.",
    "flash.is_a_root_folder": "{path} é uma pasta raiz do editor — não dá para apagar por aqui.",
    "flash.deleted_no_bak": "{output} (sem cópia .bak — apagar não tem volta).",
    "flash.also_left_config": "{path} também saiu dos arquivos da tela Config.",
    "flash.could_not_delete": "Não consegui apagar: {reason}",
    "flash.pick_a_file": "Escolha um arquivo para enviar.",
    "flash.bad_file_name": "Nome de arquivo inválido.",
    "flash.could_not_upload": "Não consegui enviar: {reason}",
    "flash.uploaded": "{output}. Se o arquivo já existia, uma cópia .bak ficou ao lado.",
    "flash.nothing_to_back_up":
        "Este servidor não tem o que guardar: preencha a pasta de configuração ou os caminhos de "
        "backup no cadastro.",
    "flash.left_config_screen": "{path} saiu da tela de configuração (o arquivo não foi tocado).",
    "flash.config_files_limit": "Limite de {n} arquivos por servidor.",
    "flash.now_opens_in_config": "{path} agora abre direto na tela Config.",
    "flash.value_out_of_range": "Não salvei nada porque há valor fora do limite - {errors}",
    "flash.no_field_changed": "Nenhum campo foi alterado.",
    "flash.could_not_save": "Não consegui salvar: {reason}",
    "flash.settings_saved":
        "{n} configuração(ões) salva(s) em {path}: {keys}. Uma cópia .bak foi guardada ao "
        "lado.",
    "flash.broker_needs_two_factor":
        "O broker só pode ser usado por quem tem a verificação em duas etapas ativa: ative-a em "
        "Conta.",
    "flash.broker_error": "Broker: {reason}",
    "flash.game_updated": "Jogo {name} atualizado.",
    "flash.game_restored": "Edição de {name} desfeita: vale de novo o arquivo do repositório.",
    "flash.game_removed": "Jogo {name} apagado do catálogo.",
    "flash.game_added": "Jogo {name} adicionado ao catálogo.",
    "flash.broker_no_operation_id": "Broker: resposta sem identificador de operação.",
    "flash.instance_deactivated": "Instância desativada: portas fechadas e container parado.",
    "flash.instance_removed": "Instância removida.",
    "flash.task_scheduled": "{task} agendado.",
    "flash.task_off": "Tarefa desligada.",
    "flash.task_on": "Tarefa ligada.",
    "flash.task_removed": "Tarefa removida.",
    "flash.could_not_trigger": "Não consegui disparar (servidor sem caminhos de backup?).",
    "flash.wrong_current_password": "Senha atual incorreta.",
    "flash.password_changed": "Senha alterada.",
    "flash.password_too_short": "A senha precisa ter ao menos {n} caracteres.",
    "flash.password_mismatch": "A confirmação não confere.",
    "flash.wrong_code": "Código incorreto. Confira o horário do celular e tente de novo.",
    "flash.two_factor_on": "Verificação em duas etapas ativada.",
    "flash.two_factor_off": "Verificação em duas etapas desativada.",
    "flash.new_codes": "Códigos novos gerados: os antigos deixaram de valer.",
    "flash.threshold_range": "O aviso de {name} vale de 50% a 100%.",
    "flash.preferences_saved": "Preferências salvas.",
    "flash.destination_limit": "Limite de {n} destinos atingido.",
    "flash.need_webhook_url": "Informe a URL do webhook.",
    "flash.destination_added": "Destino adicionado.",
    "flash.destination_not_found": "Destino não encontrado.",
    "flash.destination_saved": "Destino salvo.",
    "flash.destination_removed": "Destino removido.",
    "flash.bad_url": "URL inválida (comece com http:// ou https://).",
    "flash.destination_test_failed": "{name}: {reason}",
    "flash.destination_test_sent": "Mensagem enviada para {name} - confira o canal.",
    "flash.user_exists": "Já existe um usuário chamado '{user}'.",
    "flash.user_created":
        "Usuário '{user}' criado como {role}. Passe a senha para ele e peça para trocá-la na "
        "tela Conta.",
    "flash.cannot_change_own_role": "Você não pode mudar o próprio papel — peça a outro administrador.",
    "flash.user_already_is": "'{user}' já é {role}.",
    "flash.only_admin_demote": "Este é o único administrador: promova outra pessoa antes de rebaixá-lo.",
    "flash.user_now_is": "'{user}' agora é {role}.",
    "flash.password_reset": "Senha de '{user}' redefinida.",
    "flash.own_two_factor_in_account": "Para desligar o seu próprio 2FA use a tela Conta.",
    "flash.user_two_factor_off": "Verificação em duas etapas de '{user}' desligada.",
    "flash.cannot_remove_self": "Você não pode remover a própria conta.",
    "flash.cannot_remove_only_admin": "Não dá para remover o único administrador do painel.",
    "flash.user_removed": "Usuário '{user}' removido.",

    # --------------------------------- server registration errors
    "form.need_name": "Informe um nome.",
    "form.bad_host": "Host inválido (use o IP ou hostname do container).",
    "form.bad_ssh_user": "Usuário SSH inválido.",
    "form.bad_ssh_port": "Porta SSH inválida.",
    "form.bad_query_port": "Porta de consulta inválida (use 0 para desligar).",
    "form.bad_service": "Serviço inválido (ex.: dragonwilds.service).",
    "form.bad_player_source": "Forma de contar jogadores inválida.",
    "form.bad_config_folder": "Pasta de configuração inválida: {reason}",
    "form.bad_config_file": "Arquivo de configuração inválido ({path}): {reason}",
    "form.too_many_config_files": "No máximo {n} arquivos de configuração por servidor.",
    "form.bad_backup_path": "Caminho de backup inválido ({path}): {reason}",
    "form.no_root_backup": "Backup da raiz não: aponte a pasta do save ou da configuração.",
    "form.too_many_backup_paths": "No máximo {n} caminhos de backup por servidor.",
    "form.bad_api_url": "URL da API inválida (ex.: http://127.0.0.1:8212/v1/api/players).",
    "form.bad_login_url": "URL de login inválida (ex.: https://127.0.0.1:7787/api/v1).",
    "form.bad_json": "{label} não é JSON válido: {reason}.",
    "form.request_body": "Corpo da requisição",
    "form.login_body": "Corpo do login",
    "form.path_list": "lista",
    "form.path_count": "contagem",
    "form.path_token": "token",
    "form.bad_json_path": "Caminho da {label} inválido (use algo como 'data.players').",
    "form.login_needs_token_path":
        "Para o login automático, informe também o caminho do token (ex.: "
        "data.authenticationToken).",
    "pattern.join": "entrada",
    "pattern.leave": "saída",
    "pattern.error": "erro",

    # -------------------------------------------------- A2S query
    "a2s.truncated": "resposta do servidor terminou antes do esperado",
    "a2s.unterminated_text": "texto sem terminador na resposta",
    "a2s.split_incomplete": "resposta dividida veio incompleta",
    "a2s.split_unknown": "resposta dividida em formato desconhecido (compactada?)",
    "a2s.unexpected_reply": "resposta inesperada do servidor (tipo {kind})",
    "a2s.no_reply": "sem resposta em {seconds}s na porta {port}/udp",
    "a2s.query_failed": "falha ao consultar {host}:{port} - {reason}",

    # -------------------------------- path and file in the container
    "path.outside_roots": "fora das pastas permitidas ({folders})",
    "path.not_absolute": "use um caminho absoluto (começando com /)",
    "path.bad_character": "caractere inválido no caminho",
    "path.too_long": "caminho longo demais",
    "file.unexpected_reply": "resposta inesperada do container ao ler o arquivo",
    "file.corrupted": "conteúdo do arquivo chegou corrompido",
    "backup.bad_name": "nome de backup inválido",

    # ----------------------------------------------------------- ssh
    "ssh.failed_to_run": "falha ao executar ssh: {reason}",
    "ssh.no_stdin": "não consegui abrir a entrada do ssh",
    "ssh.no_stdout": "não consegui abrir a saída do ssh",
    "ssh.upload_timeout": "tempo esgotado ({seconds}s) enviando para {host}",

    # ---------------------------------------------- game http api
    "http.bad_url": "URL inválida (ex.: http://127.0.0.1:8212/v1/api/players)",
    "http.auth_failed": "a API respondeu {status} - confira o usuário/senha de admin",
    "http.bad_status": "a API respondeu HTTP {status}",
    "http.reply_too_big": "resposta da API grande demais para ser lida aqui",
    "http.not_json": "a resposta não é JSON: {sample}",
    "api.login_incomplete": "login automático incompleto (falta URL de login ou caminho do token)",
    "api.no_token_at": "o login respondeu, mas não achei um token em '{path}'",
    "api.need_url": "informe a URL da API do jogo",
    "api.need_join_pattern": "informe o padrão da linha de entrada de jogador",
    "api.need_query_port": "informe a porta de consulta (query Steam) do servidor",
    "api.action_not_published": "este servidor não publica essa ação",
    "api.write_the_notice": "escreva o aviso",
    "api.no_player_id": "não sei quem expulsar: a API não publicou o identificador deste jogador",

    # ---------------------------------------- log pattern and broker
    "pattern.too_long": "padrão de {label} longo demais (limite de {n} caracteres)",
    "pattern.invalid": "padrão de {label} inválido: {reason}",
    "broker.bad_host_or_service": "o broker devolveu host ou serviço com formato inválido",
    "broker.server_not_saved": "o servidor não foi gravado",

    # -------------------------- alert text (goes to the channel)
    "alert.contact_back": "{name}: contato restabelecido",
    "alert.lost_contact": "{name}: painel perdeu contato",
    "alert.no_detail": "sem detalhe",
    "alert.server_back": "{name}: servidor voltou a rodar",
    "alert.server_stopped": "{name}: servidor parou de rodar",
    "alert.game_failed": "{name}: o jogo quebrou",
    "alert.service_is_failed": "serviço {service} está 'failed'",
    "alert.service_is": "serviço {service} está '{state}'",
    "alert.restart_loop": "{name}: o jogo está caindo em loop",
    "alert.systemd_restarted": "o systemd reiniciou {service} {times}x desde a última olhada",
    "alert.game_answering": "{name}: o jogo voltou a responder",
    "alert.game_mute": "{name}: o jogo não responde",
    "alert.service_up_game_mute": "o serviço {service} está rodando, mas o jogo não responde há",
    "alert.log_error": "{name}: erro no log do jogo",
    "alert.disk_almost_full": "{name}: disco quase cheio",
    "alert.disk_detail": "{mount} em {pct}% ({used} de {total})",
    "alert.memory_almost_full": "{name}: memória quase cheia",
    "alert.memory_detail": "{pct}% ({used} de {total})",
    "alert.cpu_high": "{name}: uso de CPU alto",
    "alert.cpu_detail_one": "{pct}% em {cores} núcleo",
    "alert.cpu_detail_many": "{pct}% em {cores} núcleos",
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
    "alert.left_many": "{name}: {n} jogadores saíram",
    "alert.restarts_total": " ({n} no total desta subida)",
    "alert.mute_rounds": " {n} verificações",

    # ---------------------------------------- scheduling and weekdays
    "schedule.daily": "todo dia às {time}",
    "schedule.weekly": "{weekday} às {time}",
    "schedule.every_hour": "a cada hora",
    "schedule.every_n_hours": "a cada {n}h",
    "weekday.monday": "segunda",
    "weekday.tuesday": "terça",
    "weekday.wednesday": "quarta",
    "weekday.thursday": "quinta",
    "weekday.friday": "sexta",
    "weekday.saturday": "sábado",
    "weekday.sunday": "domingo",
    "weekday.on_monday": "toda segunda",
    "weekday.on_tuesday": "toda terça",
    "weekday.on_wednesday": "toda quarta",
    "weekday.on_thursday": "toda quinta",
    "weekday.on_friday": "toda sexta",
    "weekday.on_saturday": "todo sábado",
    "weekday.on_sunday": "todo domingo",
    "passkey.sign_in": "Entrar com biometria",
    "passkey.title": "Biometria do aparelho",
    "passkey.hint": (
        "Entre com a digital, o rosto ou o PIN do celular, sem digitar a senha. Vale como senha e "
        "código juntos: cadastre só aparelhos que são seus."),
    "passkey.created": "cadastrado em {when}",
    "passkey.last_used": "usado em {when}",
    "passkey.remove": "Remover",
    "passkey.remove_confirm": "Remover \"{name}\"? Esse aparelho deixa de entrar por biometria.",
    "passkey.add": "Cadastrar este aparelho",
    "passkey.label": "Nome do aparelho",
    "passkey.label_example": "ex.: celular",
    "passkey.disabled": "Entrar por biometria está desligado neste painel (precisa de um endereço https).",
    "passkey.cancelled": "Cancelado ou o tempo acabou. Tente de novo.",
    "passkey.login_failed": "Não consegui confirmar a biometria. Entre com a senha.",
    "passkey.register_failed": "O aparelho não foi cadastrado. Tente de novo.",
    "passkey.already_registered": "Este aparelho já está cadastrado.",
    "passkey.default_label": "Aparelho",
    "passkey.registered": "Aparelho cadastrado: da próxima vez, entre com a biometria.",
    "passkey.removed": "Aparelho removido.",
    "passkey.not_found": "Aparelho não encontrado.",
    # ------------------------------ screen text moved out of templates and scripts
    "account.operator_scope":
        "Como operador você liga, desliga, atualiza e edita a configuração dos servidores já "
        "cadastrados. Cadastro de servidor, terminal, arquivos e usuários são do administrador.",
    "account.recovery_codes_left_one": "{n} código de recuperação restante",
    "account.recovery_codes_left_many": "{n} códigos de recuperação restantes",
    "account.two_factor_off_hint":
        "Com ela, saber a senha não basta para entrar: o painel também pede um código de 6 "
        "dígitos do seu celular.",
    "account.two_factor_root_hint": "Este painel dá poder de root nos containers de jogo: ative.",
    "account_2fa.step_register": "1. Cadastre o painel no aplicativo",
    "account_2fa.step_register_hint":
        "Use um aplicativo autenticador (Google Authenticator, Authy, Microsoft Authenticator, "
        "1Password, Bitwarden...). No celular, escolha <strong>adicionar conta</strong> e "
        "<strong>escanear código QR</strong> — ou, sem câmera, <strong>inserir chave "
        "manualmente</strong> com o texto abaixo do código.",
    "account_2fa.key_details":
        "Tipo <strong>baseado em tempo</strong>, 6 dígitos, 30 segundos. Guarde esta chave e "
        "este código apenas até confirmar abaixo: depois de ativar eles não aparecem mais.",
    "account_2fa.step_confirm": "2. Confirme com um código",
    "account_2fa.clock_hint":
        "Confira também se a hora do celular está no automático: é o que faz o código bater.",
    "account_2fa_codes.save_them_now_html":
        "<strong>Guarde estes códigos agora.</strong> Eles aparecem só esta vez. Cada um entra "
        "no lugar do código do aplicativo uma única vez — é a saída se você perder o celular. "
        "Guarde num gerenciador de senhas ou impresso, nunca no mesmo celular do aplicativo.",
    "backups.keep_newest":
        "As <strong>{n}</strong> cópias mais novas ficam; as antigas saem sozinhas.",
    "backups.keep_all": "Nenhuma cópia é apagada automaticamente.",
    "backups.change_paths":
        "Para mudar o que entra, edite os <a href=\"{url}\">caminhos de backup</a> do cadastro.",
    "backups.live_copy_hint":
        "Dá para tirar a cópia com o servidor ligado, é o normal. Só saiba que um save gravado "
        "no meio da cópia pode entrar pela metade &mdash; para uma cópia perfeita, pare o "
        "servidor antes.",
    "backups.nothing_to_save_admin":
        "Este servidor não tem o que guardar. Preencha a <strong>pasta de configuração</strong> "
        "ou os <strong>caminhos de backup</strong> <a href=\"{url}\">no cadastro</a>.",
    "backups.nothing_to_save_operator":
        "Este servidor não tem o que guardar. Preencha a <strong>pasta de configuração</strong> "
        "ou os <strong>caminhos de backup</strong> (peça a um administrador).",
    "history.removed": "(removido)",
    "history.error": "erro",
    "history.keep_days":
        "O painel guarda os últimos <strong>{n} dias</strong> "
        "(<code>GAMEPANEL_JOBS_KEEP_DAYS</code>) &mdash; cada registro carrega a saída inteira "
        "do que rodou, e sem limpeza o banco só cresce.",
    "history.cleanup_off":
        "A limpeza automática está desligada (<code>GAMEPANEL_JOBS_KEEP_DAYS=0</code>): o "
        "histórico cresce sem limite.",
    "history.admin_actions_hidden":
        "Terminal, console e arquivos não aparecem aqui &mdash; são ações de administrador.",
    "catalog.source_curated": "curado",
    "catalog.source_dynamic": "dinâmico",
    "config.no_files": "Nenhum arquivo de configuração informado ainda para este servidor.",
    "config.ask_admin_to_register": "Peça a um administrador do painel para registrar o arquivo.",
    "config.format": "formato {name}",
    "config.pin_hint":
        "&quot;Fixar aqui&quot; deixa o arquivo na barra acima (até {n} por servidor); o link "
        "abre sem fixar.",
    "config.nothing_found":
        "Nada encontrado em <code>{folder}</code>. Ajuste a &quot;Pasta de configuração&quot; "
        "em <a href=\"{url}\">Editar servidor</a> ou informe o caminho completo do arquivo na "
        "barra acima.",
    "config.settings_count": "Configurações ({n})",
    "config.on": "Ligado",
    "config.off": "Desligado",
    "config.outside_catalog": "{value} (fora do catálogo)",
    "config.range": "{low} a {high}",
    "config.add_setting_hint":
        "Para chave que ainda não existe no arquivo. Ela entra no fim do bloco escolhido, sem "
        "mexer no resto.",
    "config.save_hint":
        "Grava só as chaves alteradas, mantendo comentários e o resto do arquivo. Uma cópia "
        "<code>.bak</code> fica ao lado antes de qualquer gravação. A maioria dos jogos só lê a "
        "configuração ao iniciar &mdash; sem reiniciar, a mudança não vale.",
    "config.cannot_open_as_form": "Não consegui abrir <code>{path}</code> como formulário.",
    "config.ask_admin_text_edit":
        "Avise um administrador do painel &mdash; a edição como texto é restrita a ele.",
    "service_state.unknown": "desconhecido",
    "service_state.unreachable": "inacessível",
    "server.more_actions_on": "Mais ações em {name}",
    "dashboard.register_hint":
        "Cadastre o IP de um container de jogo para controlar start, stop, update e rodar "
        "comandos por aqui.",
    "dashboard.authorize_key_hint":
        "O painel acessa cada container por SSH &mdash; antes autorize a chave dele no "
        "container em <a href=\"{url}\">Acesso SSH</a>.",
    "players.badge_online": "{count} online",
    "players.badge_players": "{count} jogadores",
    "players.no_reading": "sem leitura",
    "players.names_unpublished": "Este jogo não publica a lista de nomes — só a contagem.",
    "players.nobody_online": "Ninguém conectado agora.",
    "server_detail.count_off_admin":
        "Contagem desligada. Use o <a href=\"{url}\">assistente</a>: ele testa as portas UDP e "
        "TCP que o jogo abriu, monta a chamada da API HTTP quando existe uma e, se nada "
        "responder, ajuda a contar pelo log.",
    "server_detail.count_off_operator":
        "Contagem desligada. Um administrador do painel liga isso no assistente de contagem.",
    "server_detail.query_failed": "Não consegui consultar: {error}",
    "server_detail.query_failed_admin":
        "Confira no <a href=\"{url}\">assistente</a> se a porta/URL está certa e se o servidor "
        "está no ar.",
    "server_detail.query_failed_operator":
        "Confira se o servidor está no ar; se estiver, avise um administrador do painel.",
    "server_detail.log_only_games":
        "Jogo que não publica nada na rede (como o RuneScape Dragonwilds) precisa da contagem "
        "pelo log.",
    "server_detail.online_of": "{n} de {total}",
    "server_detail.player_action_confirm": "{action} {player} de {server}?",
    "server_detail.approx_admin":
        "A <strong>contagem</strong> está certa, mas os <strong>nomes</strong> são um palpite: "
        "o log deste jogo avisa que alguém saiu sem dizer quem, então o painel mostra os "
        "últimos a entrar. Se a linha de saída do seu servidor tiver o nome, ponha "
        "<code>(?P&lt;name&gt;...)</code> nela no <a href=\"{url}\">assistente</a> e a lista "
        "passa a ser exata.",
    "server_detail.approx_operator":
        "A <strong>contagem</strong> está certa, mas os <strong>nomes</strong> são um palpite: "
        "o log deste jogo avisa que alguém saiu sem dizer quem, então o painel mostra os "
        "últimos a entrar. Se a linha de saída do seu servidor tiver o nome, ponha "
        "<code>(?P&lt;name&gt;...)</code> nela e a lista passa a ser exata.",
    "server_detail.player_actions_note":
        "Expulsar, banir e avisar saem pela API do próprio jogo &mdash; a mesma que conta os "
        "jogadores. Cada uma fica no <a href=\"{url}\">histórico</a>.",
    "server_detail.no_log_lines": "(sem linhas de log)",
    "server_detail.stop_following": "Parar de seguir",
    "server_detail.no_connection": "sem conexão",
    "metrics.unavailable": "indisponível",
    "metrics.refresh_every": "atualiza a cada {n}s",
    "metrics.no_reading_now": "sem leitura no momento",
    "metrics.read_failed": "Não consegui ler os medidores: {error}",
    "metrics.meters_unavailable": "medidores indisponíveis",
    "metrics.cores_load": "{cores} núcleo(s) · load {load}",
    "metrics.used_of_total": "{used} de {total}",
    "metrics.disk_mount": "Disco {mount}",
    "metrics.disk": "Disco",
    "metrics.stopped": "parado",
    "files.upload_hint":
        "O arquivo sobe em pedaços, direto para o container &mdash; dá para mandar mod ou save "
        "de vários GB. Se já existir um com o mesmo nome, ele é substituído e uma cópia "
        "<code>.bak</code> fica ao lado.",
    "files.parent": ".. (subir)",
    "files.download_name": "Baixar {name}",
    "files.delete_name": "Apagar {name}",
    "files.delete_dir_name": "Apagar {name} (só se estiver vazia)",
    "files.delete_entry_confirm": "Apagar {path}?\n\nIsto não tem volta.",
    "files.binary_notice":
        "<strong>Arquivo binário.</strong> O painel não edita isso para não corromper o jogo "
        "&mdash; mas dá para baixar o arquivo inteiro.",
    "files.download_size": "Baixar ({size})",
    "files.truncated_notice":
        "<strong>Somente leitura:</strong> o arquivo tem {size} e passa do limite de edição "
        "({max_kb} KB). Abaixo estão os últimos {shown} &mdash; baixe o arquivo para trabalhar "
        "nele inteiro.",
    "files.save_hint":
        "Ctrl+S salva. Antes de gravar, o painel guarda uma cópia "
        "<code>{name}.&lt;data&gt;.bak</code> na mesma pasta, e mantém dono e permissão do "
        "arquivo original.",
    "files.crlf_note": "Este arquivo usa fim de linha CRLF &mdash; será salvo assim.",
    "files.opens_as_form_html":
        "abre este arquivo como formulário e o fixa na tela <strong>Configuração</strong>",
    "files.delete_no_undo":
        "tira <code>{name}</code> do container na hora &mdash; aqui não há cópia "
        "<code>.bak</code> nem como desfazer",
    "files.editor_intro":
        "Escolha um arquivo na lista ao lado para editar &mdash; até {max_kb} KB. Acima disso o "
        "painel mostra os últimos {preview_kb} KB só para leitura.",
    "files.any_file_downloadable_html":
        "Qualquer arquivo pode ser baixado pelo link <em>baixar</em> da lista, inclusive "
        "binários (saves, .so, .pak) e arquivos grandes demais para o editor.",
    "files.config_search_hint":
        "Procurando o arquivo de configuração do jogo? A busca por candidatos fica em <a "
        "href=\"{url}\">Configuração</a> &mdash; é lá que o resultado dela serve para alguma "
        "coisa (fixar o arquivo e editá-lo campo a campo).",
    "files.config_folder_is": "Pasta de config deste servidor: <code>{path}</code>",
    "files.config_folder_hint_html":
        "Dica: preencha a \"Pasta de configuração\" em <a href=\"{url}\">Editar servidor</a> "
        "para esta tela já abrir no lugar certo.",
    "files.stop_before_editing":
        "Pare o servidor antes de mexer nos arquivos que ele reescreve ao sair &mdash; vários "
        "jogos sobrescrevem o .ini no shutdown.",
    "terminal.session_intro":
        "Sessão SSH interativa como <strong>{user}</strong> em <code>{host}</code>. Tem TTY de "
        "verdade: <code>htop</code>, <code>nano</code>, <code>vim</code> e prompts de "
        "confirmação funcionam. A sessão cai sozinha depois de {minutes} min sem uso.",
    "terminal.input": "entrada do terminal",
    "terminal.keyboard_help":
        "O teclado vai direto para o shell: <code>Tab</code> completa, <code>&uarr;</code> "
        "percorre o histórico do bash e <code>Ctrl+C</code> interrompe. Para copiar, selecione "
        "com o mouse (com texto selecionado o <code>Ctrl+C</code> copia em vez de interromper); "
        "<code>Ctrl+V</code> cola.",
    "terminal.exit_fullscreen": "Sair da tela cheia",
    "terminal.expired": "sessão expirada",
    "terminal.closed": "sessão fechada",
    "terminal.ended": "encerrado",
    "terminal.ended_exit": "encerrado (exit {code})",
    "terminal.reconnecting": "reconectando...",
    "terminal.connecting": "conectando...",
    "terminal.connected": "conectado",
    "terminal.http_error": "erro http {status}",
    "terminal.open_failed": "falha ao abrir: {error}",
    "terminal.output_lost": "[painel: saída antiga descartada]",
    "copy.done": "Copiado!",
    "copy.failed": "Não consegui copiar",
    "config.unsaved_changes": "há alterações não salvas",
    "files.cursor_position": "linha {line}, coluna {column}",
    "files.changed_suffix": " - alterado",
    "http.no_connection": "sem conexão",
    "app.short_name": "Jogos",
    "app.description": "Liga, desliga, atualiza e acompanha os servidores de jogos.",
    "offline.no_answer": "O painel não respondeu.",
    "offline.no_answer_hint":
        "O painel não respondeu. Ele só funciona com acesso à rede onde os containers estão "
        "&mdash; ligar e desligar servidor não tem como acontecer offline.",
    "console.run_as_intro":
        "Os comandos rodam como <strong>{user}</strong> dentro do container "
        "<code>{host}</code>, via SSH. Cada execução tem limite de {timeout}s e fica registrada "
        "no histórico abaixo.",
    "console.interactive_hint":
        "Para algo interativo (nano, htop, prompts de confirmação) use a <a "
        "href=\"{url}\">sessão interativa</a>.",
    "console.non_interactive_hint":
        "Não interativo: sem TTY, sem <code>vim</code>/<code>top</code>/<code>htop</code>. Use "
        "<code>journalctl -n 50</code>, <code>ls</code>, <code>df -h</code>, <code>cat</code>, "
        "<code>sed -i</code> etc. Ctrl+Enter executa.",
    "console.running_placeholder": "(executando...)",
    "console.running": "Em execução...",
    "job.waiting_output": "(aguardando saída...)",
    "job.finished_exit": "Concluído com exit code {code}.",
    "job.running_hint":
        "Em execução — a saída abaixo atualiza sozinha. Um update de jogo pode levar vários "
        "minutos.",
    "login_2fa.recovery_hint":
        "Sem o celular? Use um dos códigos de recuperação (<code "
        "class=\"nowrap\">abcde-12345</code>); cada um serve uma vez.",
    "ssh_key.intro":
        "O painel controla cada servidor por SSH, usando a chave abaixo. Para um container "
        "aparecer como acessível, ele precisa de <code>sshd</code> rodando e desta chave "
        "autorizada no usuário informado no cadastro (normalmente <code>root</code>).",
    "ssh_key.from_proxmox":
        "A partir do host Proxmox, trocando <code>&lt;CTID&gt;</code> pelo id do container:",
    "ssh_key.provisioned_note":
        "Containers provisionados pelo <code>deploy-game.ps1</code> com "
        "<code>PANEL_PUBKEY</code> no <code>.env</code> já saem prontos &mdash; este passo é só "
        "para os criados antes disso.",
    "ssh_key.host_key_changed":
        "Na primeira conexão o painel aprende e fixa a host key do container "
        "(<code>accept-new</code>). Se o container for recriado, a chave muda e a conexão passa "
        "a falhar com <code>REMOTE HOST IDENTIFICATION HAS CHANGED</code> &mdash; nesse caso "
        "remova a entrada antiga:",
    "ssh_key.container_ip": "ip-do-container",
    "ssh_key.run_as": "Rode dentro do container do painel, como o usuário <code>gamepanel</code>.",
    "schedules.clock_note":
        "O relógio é o do <strong>painel</strong> &mdash; agora são <strong>{now}</strong> "
        "({zone}). Se não bater com a sua hora, ajuste o <code>TZ</code> do container do "
        "painel. Tarefa que venceu enquanto o painel estava fora do ar <strong>não dispara "
        "atrasada</strong>: ela espera a próxima ocorrência.",
    "schedules.no_timezone": "sem fuso definido",
    "schedules.what_to_do_hint":
        "<strong>Backup</strong> usa os caminhos do cadastro, com a mesma retenção da tela "
        "Backups. <strong>Atualizar</strong> roda o SteamCMD &mdash; o servidor fica fora do ar "
        "durante a atualização.",
    "schedules.daily_and_weekly": "(diário e semanal)",
    "schedules.weekly_only": "(semanal)",
    "schedules.interval_only": "(intervalo)",
    "schedules.runs_note":
        "Cada disparo aparece no <a href=\"{url}\">histórico</a> como qualquer outra ação, com "
        "<code>agendador</code> no lugar do usuário.",
    "users.role_of": "Papel de {name}",
    "users.username_hint":
        "Letras minúsculas, números, <code>-</code> e <code>_</code>. Ex.: <code>joao</code>",
    "users.roles_hint":
        "<strong>{operator}</strong>: liga, desliga, atualiza, edita a configuração já "
        "registrada, vê log e jogadores. <strong>{admin}</strong>: tudo isso mais cadastrar "
        "servidor, terminal, navegador de arquivos e esta tela.",
    "users.password_handoff_html":
        "Você define a senha e passa para a pessoa; ela troca depois em <a "
        "href=\"{url}\">Conta</a>. O painel não envia e-mail.",
    "users.cut_note":
        "O corte segue o que dá acesso de root ao container: terminal, editor de arquivos e o "
        "cadastro do servidor (que aponta o SSH do painel) ficam com o administrador.",
    "charts.over_time": "{title} ao longo do tempo",
    "charts.samples_note":
        "{n} amostra(s) &middot; uma a cada {every} min &middot; guardadas por {days} dias",
    "charts.no_samples_hint":
        "O painel guarda uma leitura a cada {every} minutos enquanto está no ar &mdash; volte "
        "daqui a pouco, ou escolha um período maior.",
    "charts.peak_in_period": "pico de <strong>{n}</strong> no período",
    "charts.no_player_count":
        "Sem contagem de jogadores neste período (a contagem precisa estar ligada no cadastro "
        "do servidor).",
    "charts.table_hint":
        "Os mesmos valores do gráfico, sem depender de cor nem de passar o dedo por cima. Do "
        "mais recente para o mais antigo.",
    "charts.range_6h": "6 horas",
    "charts.range_24h": "24 horas",
    "charts.range_7d": "7 dias",

    # ---- errors that reach the screen from runtime/, integrations/, app.py and blueprints/
    # Raised as `i18n.Message` far from any request; the display point translates them.
    "ssh.timeout": "tempo esgotado ({seconds}s) executando no host {host}",
    "ssh.command_failed": "comando falhou (exit {code})",
    "terminal.session_open_failed": "falha ao abrir a sessão: {reason}",
    "terminal.session_ended": "sessão encerrada: {reason}",
    "terminal.too_many_sessions": "limite de {n} terminais simultâneos atingido",
    "file.list_failed": "falha ao listar a pasta",
    "file.search_failed": "falha na busca",
    "file.read_failed": "falha ao ler o arquivo",
    "file.write_failed": "falha ao gravar",
    "file.delete_failed": "falha ao apagar",
    "file.upload_failed": "falha ao enviar (exit {code})",
    "backup.list_failed": "falha ao listar os backups",
    "backup.delete_failed": "falha ao apagar o backup",
    "http.path_missing": "'{path}' não existe na resposta",
    "http.not_a_list": "'{path}' não aponta para uma lista",
    "http.not_a_count": "'{path}' não é um número nem uma lista",
    "http.no_players_found": "não achei jogadores na resposta - preencha o caminho da lista ou da contagem",
    "log.bad_path":
        "caminho de log inválido - use um caminho absoluto, sem espaços (o '*' é permitido, ex.: "
        "/opt/game/profiles/*.ADM)",
    "ports.list_failed": "não consegui listar as portas abertas do container: {reason}",
    "ports.tcp_probe_failed": "não consegui sondar as portas TCP: {reason}",
    "error.timed_out": "tempo esgotado",
    "broker.cert_mismatch": "o certificado do broker não confere com a impressão fixada",
    "broker.not_configured": "o broker não está configurado neste painel",
    "broker.unreachable": "não consegui falar com o broker ({kind})",
    "broker.reply_too_big": "resposta grande demais do broker",
    "broker.unexpected_reply": "resposta inesperada do broker",
    "broker.http_status": "o broker respondeu HTTP {status}",
    "webhook.bad_url": "URL inválida (use http:// ou https://)",
    "webhook.http_status": "o webhook respondeu HTTP {status}",
    "webhook.http_status_reason": "o webhook respondeu HTTP {status}: {reason}",
    "webhook.call_failed": "não consegui chamar o webhook: {reason}",
    "players.need_join_pattern": "informe o padrão da linha de entrada",
    "players.everyone": "todos",
    "api.two_factor_required": "ative a verificação em duas etapas em Conta",
    "api.broker_needs_two_factor": "ative a verificação em duas etapas em Conta para usar o broker",
    "account.wrong_password": "Senha incorreta.",
    "account.too_many_tries": "Muitas tentativas. Espere alguns minutos.",
    "account.code_invalid_or_used": "Código inválido ou já usado.",
    "alerts.bad_webhook_url": "URL inválida (comece com http:// ou https://).",
    "alerts.needs_query_count": "contagem de jogadores por consulta (A2S) ou API HTTP",
    "alerts.needs_player_count": "contagem de jogadores (A2S, API HTTP ou log)",
    "alerts.needs_error_pattern": "uma expressão de erro no cadastro do servidor",
    "alerts.limit_disk": "disco cheio",
    "alerts.limit_memory": "memória cheia",
    "alerts.limit_cpu": "CPU alta",
    "alerts.destination_fallback": "destino",
    "flash.backup_deleted": "Backup {file} apagado.",
    "alerts.unnamed": "Sem nome",
    # ---- the "Add game" form (services/broker_service.py) and the console end-of-job line
    "broker_form.app_id": "App ID",
    "broker_form.memory": "Memória",
    "broker_form.must_be_number": "{label} deve ser um número.",
    "console.exit_code": "exit code {code}",
    # ---- "Add game" search suggestions: source and warnings of the hand-written list
    # (games/catalog/manual_suggestions.py) and the Pterodactyl complement note (search.py)
    "catalog.source.manual": "curadoria do painel",
    "catalog.suggestion.from_pterodactyl": "Veio do egg do Pterodactyl (o LinuxGSM não tinha): {fields}.",
    "catalog.suggestion.field.config_path": "pasta de config",
    "catalog.suggestion.field.config_files": "arquivos de config",
    "catalog.suggestion.field.ports": "portas",
    "catalog.suggestion.proton_note":
        "Servidor só de Windows: roda pelo Proton (receita proton). Se não subir, "
        "troque para wine e anote o motivo.",
    "catalog.suggestion.ark_ascended.no_steam_query":
        "O ASA não publica query da Steam (a lista é pela Epic): a contagem vem do log.",
    "catalog.suggestion.ark_ascended.map_argument":
        "O mapa é o primeiro argumento (TheIsland_WP). Nome e senha do servidor ficam no "
        "GameUserSettings.ini, não no comando.",
    "catalog.suggestion.ark_ascended.memory": "Precisa de ~13 GB de RAM só para subir o mapa padrão.",
    "catalog.suggestion.abiotic_factor.sandbox_settings":
        "As regras do mundo ficam no SandboxSettings.ini de cada mundo, que só nasce no "
        "primeiro start (Saved/SaveGames/Server/Worlds/<mundo>/).",
    "catalog.suggestion.conan_exiles.port_plus_one":
        "A 7778/UDP é a porta do jogo + 1, aberta sozinha pelo servidor: por isso ele não "
        "anda de porta (o broker não tem como avisá-la).",
    "catalog.suggestion.conan_exiles.save": "O save inteiro é o game.db em ConanSandbox/Saved.",
    "catalog.suggestion.sons_of_the_forest.ports":
        "As portas (GamePort, QueryPort, BlobSyncPort) moram no dedicatedserver.cfg, que o "
        "servidor cria em /opt/game/userdata no primeiro start: não há como passá-las pelo "
        "comando, então ele fica nas portas padrão.",
    "catalog.suggestion.sons_of_the_forest.xvfb": "O servidor cria janela na largada: por isso a receita xvfb.",

    # ---- game config fields (games/adapters/*.py)
    # The Config screen's labels, help texts and option labels, one block per adapter:
    # `game.<adapter>.<field>.label` / `.help` / `.opt.<value>`, with the field and the value
    # LOWERCASED (the key convention test). A game with its own screen brings its keys here
    # and in the other catalog; `test_game_texts.py` fails while one is missing.
    # The section names and the format name that `config_format` produces (an unnamed block).
    "config.no_section": "(sem seção)",
    "config.root": "(raiz)",
    "config.format_text": "Texto",
    # Errors of the config readers (`games/config_format.py`, `load_config_doc`).
    "config.error.invalid_name": "nome de configuração inválido: {name}",
    "config.error.value_newline": "o valor não pode ter quebra de linha",
    "config.error.value_too_long": "valor longo demais (limite de {n} caracteres)",
    "config.error.invalid_bool": "valor booleano inválido: {value} (use True ou False)",
    "config.error.value_double_quote": 'o valor não pode conter aspas duplas (")',
    "config.error.invalid_json": "JSON inválido: {reason}",
    "config.error.json_not_container": "JSON precisa ser um objeto ou lista para virar formulário",
    "config.error.json_missing_path": "caminho inexistente no JSON: {path}",
    "config.error.not_an_integer": "{value} não é um número inteiro",
    "config.error.not_a_number": "{value} não é um número",
    "config.error.json_dot_in_key": "ponto (.) não é aceito no nome de uma chave JSON",
    "config.error.json_add_to_list": "não dá para acrescentar {name} numa lista JSON",
    "config.error.json_not_object": "{section} não é um objeto JSON",
    "config.error.sii_value_quote": 'o valor não pode conter aspas (") nem barra invertida (\\)',
    "config.error.sii_needs_block": "no .sii a configuração nova precisa ir dentro de um bloco",
    "config.error.sii_invalid_name": "nome de configuração inválido no .sii: {name}",
    "config.error.binary_file": "este arquivo é binário — a edição campo a campo não se aplica a ele",
    "config.error.file_too_big":
        "o arquivo tem {kb} KB e passa do limite de edição ({limit} KB) — arquivo de configuração não costuma "
        "chegar a esse tamanho, confira se é o arquivo certo",
    "config.error.too_many_keys":
        "o arquivo tem {n} chaves (o formulário para em {limit}) — pelo jeito não é um arquivo de configuração",
    # Units and the validation message of a mapped field (`games/base.py`).
    "game.unit.factor": "x",
    "game.unit.minutes": "min",
    "game.unit.seconds": "s",
    "game.validation.invalid_choice": "valor inválido; use um de: {choices}",
    "game.validation.not_a_number": "precisa ser um número",
    "game.validation.minimum": "mínimo {limit}",
    "game.validation.maximum": "máximo {limit}",
    "game.validation.with_unit": "{value} {unit}",
    # Labels shared by several games, then one block per adapter.
    "game.common.name": "Nome do servidor",
    "game.common.join_password": "Senha de entrada",
    "game.common.admin_password": "Senha de admin",
    "game.dayz.hostname.help": "Como aparece no navegador de servidores.",
    "game.dayz.password.help": "Vazio = servidor aberto.",
    "game.dayz.passwordadmin.help": "Acesso ao console remoto. TROQUE antes de expor.",
    "game.dayz.maxplayers.label": "Vagas",
    "game.dayz.maxplayers.help": "Máximo de jogadores simultâneos.",
    "game.dayz.steamqueryport.label": "Porta de consulta",
    "game.dayz.steamqueryport.help":
        "Sem ela o servidor não aparece no navegador do cliente. Precisa bater com o que está liberado no roteador.",
    "game.dayz.verifysignatures.label": "Verificar assinaturas",
    "game.dayz.verifysignatures.help": "2 = só aceita mods assinados. Deixe em 2.",
    "game.dayz.forcesamebuild.label": "Mesma versão",
    "game.dayz.forcesamebuild.help": "1 = cliente precisa estar na mesma versão do servidor.",
    "game.dayz.disable3rdperson.label": "Somente 1a pessoa",
    "game.dayz.disable3rdperson.help": "1 = servidor apenas em primeira pessoa.",
    "game.dayz.disablevon.label": "Desligar voz",
    "game.dayz.disablevon.help": "0 = voz habilitada.",
    "game.dayz.servertimeacceleration.label": "Aceleração do tempo",
    "game.dayz.servertimeacceleration.help": "12 = um dia do jogo a cada 2 horas reais.",
    "game.dayz.instanceid.label": "ID da instância",
    "game.dayz.instanceid.help": "Define a pasta storage_<id> da persistência.",
    "game.dragonwilds.ownerid.label": "ID do dono",
    "game.dragonwilds.ownerid.help":
        "Seu Player ID, no rodapé do menu de Configurações do jogo (não é o Steam ID de 17 dígitos). Sem ele o "
        "servidor NÃO sobe.",
    "game.dragonwilds.servername.help": "Como ele aparece para quem entra.",
    "game.dragonwilds.defaultworldname.label": "Nome do mundo padrão",
    "game.dragonwilds.defaultworldname.help":
        "Nome do mundo criado no primeiro start. Trocar depois não renomeia um mundo que já existe.",
    "game.dragonwilds.adminpassword.help":
        "Quem souber esta senha abre a aba Server Management no menu do jogo e vira admin. TROQUE antes de expor o "
        "servidor.",
    "game.dragonwilds.worldpassword.help": "Vazio = qualquer um entra.",
    "game.dragonwilds.serverguid.label": "GUID do servidor",
    "game.dragonwilds.serverguid.help": "Gerado pelo próprio jogo. Não edite à mão.",
    "game.dragonwilds.knownplayerlist.label": "Jogadores conhecidos",
    "game.dragonwilds.knownplayerlist.help":
        "Preenchido pelo próprio jogo (quem já entrou, privilégios e banimentos). Não edite à mão.",
    "game.enshrouded.name.help": "Como ele aparece na lista de servidores do jogo.",
    "game.enshrouded.slotcount.label": "Vagas",
    "game.enshrouded.slotcount.help": "Quantos jogadores podem estar conectados ao mesmo tempo.",
    "game.enshrouded.queryport.label": "Porta",
    "game.enshrouded.queryport.help":
        "Porta que o jogador digita para entrar. Mudar aqui exige mudar também o redirecionamento no roteador.",
    "game.enshrouded.ip.label": "IP de escuta",
    "game.enshrouded.ip.help": "0.0.0.0 aceita conexão por qualquer interface. Só mude se souber exatamente por que.",
    "game.enshrouded.enablevoicechat.label": "Voz",
    "game.enshrouded.enablevoicechat.help": "Liga o chat de voz no servidor.",
    "game.enshrouded.enabletextchat.label": "Texto",
    "game.enshrouded.enabletextchat.help": "Liga o chat de texto no servidor.",
    "game.enshrouded.voicechatmode.label": "Modo de voz",
    "game.enshrouded.voicechatmode.help": "Proximity: só ouve quem está perto. Global: todo mundo se ouve.",
    "game.enshrouded.voicechatmode.opt.proximity": "Proximidade (padrão)",
    "game.enshrouded.voicechatmode.opt.global": "Global",
    "game.enshrouded.gamesettingspreset.label": "Preset de dificuldade",
    "game.enshrouded.gamesettingspreset.help":
        "ATENÇÃO: escolher um preset diferente de Custom faz o jogo IGNORAR os ajustes individuais abaixo. Se você "
        "personalizou algo, deixe em Custom.",
    "game.enshrouded.gamesettingspreset.opt.default": "Padrão (primeira vez)",
    "game.enshrouded.gamesettingspreset.opt.relaxed": "Relaxado (construção)",
    "game.enshrouded.gamesettingspreset.opt.hard": "Difícil (combate)",
    "game.enshrouded.gamesettingspreset.opt.survival": "Sobrevivência (punitivo)",
    "game.enshrouded.gamesettingspreset.opt.custom": "Custom (usa os ajustes abaixo)",
    "game.enshrouded.playerhealthfactor.label": "Vida do jogador",
    "game.enshrouded.playerhealthfactor.help": "Multiplica a vida máxima. 2 = o dobro de vida.",
    "game.enshrouded.playermanafactor.label": "Mana do jogador",
    "game.enshrouded.playermanafactor.help": "Multiplica a mana máxima.",
    "game.enshrouded.playerstaminafactor.label": "Stamina do jogador",
    "game.enshrouded.playerstaminafactor.help": "Multiplica a stamina máxima.",
    "game.enshrouded.playerbodyheatfactor.label": "Calor corporal",
    "game.enshrouded.playerbodyheatfactor.help":
        "Multiplica a resistência ao frio. Maior = aguenta mais tempo em região gelada.",
    "game.enshrouded.playerdivingtimefactor.label": "Fôlego",
    "game.enshrouded.playerdivingtimefactor.help": "Multiplica o tempo que dá para ficar submerso.",
    "game.enshrouded.enabledurability.label": "Durabilidade",
    "game.enshrouded.enabledurability.help": "Desligado, equipamento nunca quebra e não precisa de reparo.",
    "game.enshrouded.enablestarvingdebuff.label": "Penalidade de fome",
    "game.enshrouded.enablestarvingdebuff.help": "Ligado, ficar sem comer aplica penalidade (não só remove os buffs).",
    "game.enshrouded.foodbuffdurationfactor.label": "Duração do buff de comida",
    "game.enshrouded.foodbuffdurationfactor.help": "Multiplica quanto tempo o efeito da comida dura.",
    "game.enshrouded.fromhungertostarving.label": "Da fome até passar fome",
    "game.enshrouded.fromhungertostarving.help": "Tempo entre ficar com fome e começar a sofrer a penalidade.",
    "game.enshrouded.shroudtimefactor.label": "Tempo dentro da Bruma",
    "game.enshrouded.shroudtimefactor.help": "Multiplica quanto tempo dá para ficar na Bruma antes de morrer.",
    "game.enshrouded.tombstonemode.label": "Ao morrer",
    "game.enshrouded.tombstonemode.help": "O que fica na lápide. 'Perde tudo' inclui o que estava equipado.",
    "game.enshrouded.tombstonemode.opt.addbackpackmaterials": "Perde os materiais da mochila (padrão)",
    "game.enshrouded.tombstonemode.opt.everything": "Perde tudo",
    "game.enshrouded.tombstonemode.opt.notombstone": "Mantém tudo (sem lápide)",
    "game.enshrouded.enablegliderturbulences.label": "Turbulência no planador",
    "game.enshrouded.enablegliderturbulences.help": "Desligado, o planador voa estável, sem correntes de ar.",
    "game.enshrouded.daytimeduration.label": "Duração do dia",
    "game.enshrouded.daytimeduration.help":
        "Quanto tempo REAL dura o dia no jogo. O arquivo guarda em nanossegundos; aqui você edita em minutos.",
    "game.enshrouded.nighttimeduration.label": "Duração da noite",
    "game.enshrouded.nighttimeduration.help":
        "Quanto tempo REAL dura a noite. Mínimo de 2 minutos - valor menor que isso o jogo descarta.",
    "game.enshrouded.weatherfrequency.label": "Frequência do clima",
    "game.enshrouded.weatherfrequency.help": "Com que frequência o tempo muda (chuva, tempestade).",
    "game.enshrouded.weatherfrequency.opt.disabled": "Desligado",
    "game.enshrouded.weatherfrequency.opt.rare": "Raro",
    "game.enshrouded.weatherfrequency.opt.normal": "Normal",
    "game.enshrouded.weatherfrequency.opt.often": "Frequente",
    "game.enshrouded.fishingdifficulty.label": "Dificuldade da pesca",
    "game.enshrouded.fishingdifficulty.help": "Quão difícil é o minigame de fisgar o peixe.",
    "game.enshrouded.fishingdifficulty.opt.veryeasy": "Muito fácil",
    "game.enshrouded.fishingdifficulty.opt.easy": "Fácil",
    "game.enshrouded.fishingdifficulty.opt.normal": "Normal",
    "game.enshrouded.fishingdifficulty.opt.hard": "Difícil",
    "game.enshrouded.fishingdifficulty.opt.veryhard": "Muito difícil",
    "game.enshrouded.cursemodifier.label": "Maldição",
    "game.enshrouded.cursemodifier.help": "Chance de receber maldição. 'Fácil' desliga o sistema.",
    "game.enshrouded.cursemodifier.opt.easy": "Fácil (desligado)",
    "game.enshrouded.cursemodifier.opt.normal": "Normal",
    "game.enshrouded.cursemodifier.opt.hard": "Difícil (chance dobrada)",
    "game.enshrouded.randomspawneramount.label": "Inimigos pelo mundo",
    "game.enshrouded.randomspawneramount.help": "Quantos inimigos aparecem fora das bases inimigas.",
    "game.enshrouded.randomspawneramount.opt.few": "Poucos",
    "game.enshrouded.randomspawneramount.opt.normal": "Normal",
    "game.enshrouded.randomspawneramount.opt.many": "Muitos",
    "game.enshrouded.randomspawneramount.opt.extreme": "Extremo",
    "game.enshrouded.aggropoolamount.label": "Inimigos que atacam juntos",
    "game.enshrouded.aggropoolamount.help": "Quantos inimigos podem perseguir o jogador ao mesmo tempo.",
    "game.enshrouded.aggropoolamount.opt.few": "Poucos",
    "game.enshrouded.aggropoolamount.opt.normal": "Normal",
    "game.enshrouded.aggropoolamount.opt.many": "Muitos",
    "game.enshrouded.aggropoolamount.opt.extreme": "Extremo",
    "game.enshrouded.miningdamagefactor.label": "Dano de mineração",
    "game.enshrouded.miningdamagefactor.help":
        "Multiplica o quanto a picareta quebra por golpe. Maior = mina mais rápido.",
    "game.enshrouded.plantgrowthspeedfactor.label": "Velocidade das plantações",
    "game.enshrouded.plantgrowthspeedfactor.help": "Multiplica a velocidade de crescimento das plantas.",
    "game.enshrouded.resourcedropstackamountfactor.label": "Recursos por coleta",
    "game.enshrouded.resourcedropstackamountfactor.help": "Multiplica a quantidade que cai ao coletar.",
    "game.enshrouded.factoryproductionspeedfactor.label": "Velocidade de produção",
    "game.enshrouded.factoryproductionspeedfactor.help": "Multiplica a velocidade das bancadas e fornalhas.",
    "game.enshrouded.perkupgraderecyclingfactor.label": "Retorno ao reciclar perk",
    "game.enshrouded.perkupgraderecyclingfactor.help":
        "Fração do material devolvida ao desfazer um upgrade de arma. 0,5 = devolve metade; 1 = devolve tudo.",
    "game.enshrouded.perkcostfactor.label": "Custo dos perks",
    "game.enshrouded.perkcostfactor.help": "Multiplica o material necessário para melhorar armas.",
    "game.enshrouded.experiencecombatfactor.label": "XP de combate",
    "game.enshrouded.experiencecombatfactor.help": "Multiplica a experiência ganha lutando.",
    "game.enshrouded.experienceminingfactor.label": "XP de mineração",
    "game.enshrouded.experienceminingfactor.help": "Multiplica a experiência ganha minerando.",
    "game.enshrouded.experienceexplorationquestsfactor.label": "XP de exploração e missões",
    "game.enshrouded.experienceexplorationquestsfactor.help":
        "Multiplica a experiência de explorar e completar missões.",
    "game.enshrouded.enemydamagefactor.label": "Dano dos inimigos",
    "game.enshrouded.enemydamagefactor.help": "Multiplica o dano que os inimigos causam.",
    "game.enshrouded.enemyhealthfactor.label": "Vida dos inimigos",
    "game.enshrouded.enemyhealthfactor.help": "Multiplica a vida dos inimigos.",
    "game.enshrouded.enemystaminafactor.label": "Stamina dos inimigos",
    "game.enshrouded.enemystaminafactor.help": "Multiplica a stamina deles (quanto conseguem atacar seguido).",
    "game.enshrouded.enemyperceptionrangefactor.label": "Alcance de percepção",
    "game.enshrouded.enemyperceptionrangefactor.help": "Multiplica a distância em que os inimigos notam você.",
    "game.enshrouded.bossdamagefactor.label": "Dano dos chefes",
    "game.enshrouded.bossdamagefactor.help": "Multiplica o dano dos chefes.",
    "game.enshrouded.bosshealthfactor.label": "Vida dos chefes",
    "game.enshrouded.bosshealthfactor.help": "Multiplica a vida dos chefes.",
    "game.enshrouded.threatbonus.label": "Agressividade",
    "game.enshrouded.threatbonus.help": "Multiplica a facilidade com que os inimigos se irritam.",
    "game.enshrouded.pacifyallenemies.label": "Inimigos pacíficos",
    "game.enshrouded.pacifyallenemies.help": "Ligado, nenhum inimigo ataca - modo construção/exploração.",
    "game.enshrouded.tamingstartlerepercussion.label": "Ao assustar animal domesticável",
    "game.enshrouded.tamingstartlerepercussion.help":
        "Quanto do progresso de domesticação se perde quando o animal se assusta.",
    "game.enshrouded.tamingstartlerepercussion.opt.keepprogress": "Mantém todo o progresso",
    "game.enshrouded.tamingstartlerepercussion.opt.losesomeprogress": "Perde parte (padrão)",
    "game.enshrouded.tamingstartlerepercussion.opt.loseallprogress": "Perde tudo",
    "game.enshrouded.password.label": "Senha do grupo",
    "game.enshrouded.password.help":
        "Senha que o jogador digita para entrar NESTE grupo. Cada grupo (Admin/Friend/Guest) tem a sua - não existe "
        "senha única de servidor.",
    "game.enshrouded.cankickban.label": "Pode expulsar/banir",
    "game.enshrouded.cankickban.help": "Permite remover jogadores do servidor.",
    "game.enshrouded.canaccessinventories.label": "Pode abrir inventários",
    "game.enshrouded.canaccessinventories.help": "Permite mexer em baú de outros jogadores.",
    "game.enshrouded.caneditbase.label": "Pode editar base",
    "game.enshrouded.caneditbase.help": "Permite construir e destruir dentro da base.",
    "game.enshrouded.canextendbase.label": "Pode ampliar base",
    "game.enshrouded.canextendbase.help": "Permite aumentar a área da base.",
    "game.enshrouded.caneditworld.label": "Pode editar o mundo",
    "game.enshrouded.caneditworld.help": "Permite alterar terreno fora das bases.",
    "game.enshrouded.reservedslots.label": "Vagas reservadas",
    "game.enshrouded.reservedslots.help": "Vagas garantidas para este grupo, mesmo com o servidor cheio.",
    "game.ets2.lobby_name.help": "Como aparece na lista de servidores do jogo.",
    "game.ets2.description.label": "Descrição",
    "game.ets2.description.help": "Texto curto mostrado junto do nome na lista.",
    "game.ets2.welcome_message.label": "Mensagem de boas-vindas",
    "game.ets2.welcome_message.help": "Aparece no chat para quem entra.",
    "game.ets2.password.help": "Vazio = servidor aberto.",
    "game.ets2.max_players.label": "Vagas",
    "game.ets2.max_players.help":
        "Acima de 8, CADA jogador precisa de g_max_convoy_size 128 no config.cfg do jogo, senão o servidor some da "
        "lista dele.",
    "game.ets2.max_vehicles_total.label": "Veículos no total",
    "game.ets2.max_vehicles_total.help": "Limite de veículos no mundo.",
    "game.ets2.max_ai_vehicles_player.label": "Tráfego por jogador",
    "game.ets2.max_ai_vehicles_player.help": "Veículos de IA em volta de cada um.",
    "game.ets2.player_damage.label": "Dano entre jogadores",
    "game.ets2.player_damage.help": "Colisão entre caminhões causa dano.",
    "game.ets2.traffic.label": "Tráfego",
    "game.ets2.traffic.help": "Liga os veículos de IA.",
    "game.ets2.hide_colliding.label": "Esconder quem colide",
    "game.ets2.hide_colliding.help": "Caminhão parado em cima do outro some.",
    "game.ets2.force_speed_limiter.label": "Limitador de velocidade",
    "game.ets2.force_speed_limiter.help": "Obriga o limitador ligado.",
    "game.ets2.friends_only.label": "Só amigos",
    "game.ets2.friends_only.help": "Só amigos da Steam de quem está no servidor entram.",
    "game.ets2.show_server.label": "Mostrar na lista",
    "game.ets2.show_server.help": "Desligado = só entra quem procura pelo ID.",
    "game.ets2.name_tags.label": "Nomes sobre os caminhões",
    "game.ets2.name_tags.help": "Mostra o nome de cada jogador.",
    "game.ets2.server_logon_token.label": "Token de logon",
    "game.ets2.server_logon_token.help": "Mantém a mesma identidade do servidor entre reinícios.",
    "game.icarus.sessionname.help": "Como ele aparece no navegador de servidores.",
    "game.icarus.joinpassword.help": "Vazio = qualquer um entra.",
    "game.icarus.adminpassword.help": "Dá acesso aos comandos de administrador no jogo.",
    "game.icarus.maxplayers.label": "Vagas",
    "game.icarus.maxplayers.help": "Máximo de jogadores simultâneos.",
    "game.icarus.allownonadminstolaunchprospects.label": "Jogador comum pode iniciar prospect",
    "game.icarus.allownonadminstolaunchprospects.help":
        "Desligado, só admin escolhe qual missão (prospect) roda no servidor.",
    "game.icarus.allownonadminstodeleteprospects.label": "Jogador comum pode apagar prospect",
    "game.icarus.allownonadminstodeleteprospects.help": "Cuidado: apagar prospect apaga o progresso dele.",
    "game.icarus.shutdownifnotjoinedfor.label": "Desliga se ninguém entrar",
    "game.icarus.shutdownifnotjoinedfor.help":
        "Segundos sem NENHUMA conexão até o servidor se encerrar. O systemd reinicia logo depois; aumente para "
        "manter de pé.",
    "game.icarus.shutdownifemptyfor.label": "Desliga ao ficar vazio",
    "game.icarus.shutdownifemptyfor.help": "Segundos com o servidor vazio até ele se encerrar.",
    "game.icarus.resumeprospect.label": "Retomar prospect",
    "game.icarus.resumeprospect.help": "Ligado, o servidor volta sozinho para a missão que estava rodando.",
    "game.icarus.loadprospect.label": "Prospect a carregar",
    "game.icarus.loadprospect.help": "Nome do prospect salvo que deve ser aberto.",
    "game.icarus.createprospect.label": "Prospect a criar",
    "game.icarus.createprospect.help": "Cria uma missão nova com este nome ao subir.",
    "game.icarus.lastprospectname.label": "Último prospect",
    "game.icarus.lastprospectname.help": "Preenchido pelo próprio jogo. Não edite à mão.",
    "game.palworld.servername.help": "Como ele aparece na lista da comunidade.",
    "game.palworld.serverpassword.help": "Vazio = servidor aberto.",
    "game.palworld.adminpassword.help": "Usada nos comandos administrativos e na API REST.",
    "game.palworld.serverplayermaxnum.label": "Vagas",
    "game.palworld.serverplayermaxnum.help": "Máximo de jogadores simultâneos (limite de 32).",
    "game.palworld.publicport.label": "Porta pública",
    "game.palworld.publicport.help": "Precisa bater com a porta redirecionada no roteador.",
    "game.palworld.restapienabled.label": "API REST",
    "game.palworld.restapienabled.help": "Liga a API que o painel usa para mostrar os NOMES dos jogadores.",
    "game.palworld.restapiport.label": "Porta da API REST",
    "game.palworld.restapiport.help": "Nunca redirecione esta porta no roteador.",
    "game.palworld.rconenabled.label": "RCON",
    "game.palworld.rconenabled.help": "Console remoto. Depreciado pela Pocketpair em favor da API REST.",
    "game.palworld.deathpenalty.label": "Penalidade de morte",
    "game.palworld.deathpenalty.help": "O que você perde ao morrer.",
    "game.palworld.deathpenalty.opt.none": "Nada",
    "game.palworld.deathpenalty.opt.item": "Itens (sem equipamento)",
    "game.palworld.deathpenalty.opt.itemandequipment": "Itens e equipamento",
    "game.palworld.deathpenalty.opt.all": "Tudo (inclui Pals)",
    "game.palworld.daytimespeedrate.label": "Velocidade do dia",
    "game.palworld.daytimespeedrate.help": "Maior = dia passa mais rápido.",
    "game.palworld.nighttimespeedrate.label": "Velocidade da noite",
    "game.palworld.nighttimespeedrate.help": "Maior = noite passa mais rápido.",
    "game.palworld.exprate.label": "Ganho de XP",
    "game.palworld.exprate.help": "Multiplica toda a experiência recebida.",
    "game.palworld.palcapturerate.label": "Taxa de captura",
    "game.palworld.palcapturerate.help": "Multiplica a chance de capturar Pals.",
    "game.palworld.palspawnnumrate.label": "Quantidade de Pals",
    "game.palworld.palspawnnumrate.help": "Multiplica quantos Pals aparecem no mundo.",
    "game.palworld.paldamagerateattack.label": "Dano dos Pals",
    "game.palworld.paldamagerateattack.help": "Multiplica o dano causado pelos Pals.",
    "game.palworld.paldamageratedefense.label": "Defesa dos Pals",
    "game.palworld.paldamageratedefense.help": "Multiplica a resistência dos Pals.",
    "game.palworld.playerdamagerateattack.label": "Dano do jogador",
    "game.palworld.playerdamagerateattack.help": "Multiplica o dano que você causa.",
    "game.palworld.playerdamageratedefense.label": "Defesa do jogador",
    "game.palworld.playerdamageratedefense.help": "Multiplica sua resistência.",
    "game.palworld.collectiondroprate.label": "Recursos coletados",
    "game.palworld.collectiondroprate.help": "Multiplica o que cai ao coletar.",
    "game.palworld.enableplayertoplayerdamage.label": "PvP",
    "game.palworld.enableplayertoplayerdamage.help": "Permite jogadores se atacarem.",
    "game.palworld.benabledefenseotherguild.label": "Defesa de outras guildas",
    "game.palworld.benabledefenseotherguild.help": "Permite que sua base seja atacada por outras guildas.",
}
