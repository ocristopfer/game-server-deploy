# Plano: instâncias Docker no broker, e o vazamento do Proxmox

> Escrito depois de ler `src/gamebroker/` inteiro (~2.9k linhas) e a camada
> `src/gamepanel/runtime/`. Nada foi movido nem editado para produzir este documento.
> Ele existe para ser aprovado antes de alguém mexer em arquivo.
>
> Companheiro de [`architecture-analysis.md`](architecture-analysis.md) e
> [`architecture-proposal.md`](architecture-proposal.md), que descrevem a reorganização
> de pastas (Fases 1-4). Este aqui é sobre **o que o broker cria**, não sobre onde o
> código mora.

---

## 0. A decisão, antes do plano

A pergunta que originou isto foi "suporto todos os modos (Proxmox, Docker, Kubernetes)
ou migro para um só?". A resposta é **nenhuma das duas**:

- **Não "suportar todos"**: ainda não houve UMA criação real de ponta a ponta contra o
  Proxmox/OPNsense de verdade. Abstração desenhada antes da primeira execução real
  codifica palpite — e o palpite depois tem que ser consertado em três implementações
  em vez de uma. Três backends não testados é pior que um testado, ainda mais num
  sistema em que o painel tem root dentro dos containers.
- **Não "migrar para K8s"**: K8s vende agendamento entre nós. Há **um** host Proxmox e
  **um** OPNsense. Num host só o custo de operação é alto e a rede piora: o invariante
  "porta interna == externa, sempre" (correto — o jogo anuncia a própria porta na lista
  da Steam) briga com NodePort, que vive em 30000-32767, em cima da faixa 31000-31999
  do broker.

O que este plano faz: **mantém o Proxmox como único backend em produção, tira o
vocabulário dele de onde é caro mudar depois, e acrescenta Docker como o SEGUNDO
backend** — porque dois backends é o número que prova uma abstração. Um é chute, três é
imposto.

### O que "escala" quer dizer aqui

Vale registrar o que NÃO limita escala hoje, para o Docker não ser vendido como cura do
que ele não cura:

| limite atual | onde |
|---|---|
| 8 instâncias, 4 criações/hora | `instance_service.Config` |
| uma operação por vez, global | `db.Db.operation_in_progress` |
| 1 worker gunicorn (a trava de IP mora na memória) | `provision-broker-lxc.sh` |
| ~1000 portas na faixa, 1 IP WAN | `BROKER_PORT_INICIO/FIM` |
| disco cheio por instância (SteamCMD inteiro) | o `disk_gb` de cada jogo |

Trocar de backend não mexe nos quatro primeiros. Mexe no quinto — e é aí que mora o
**único argumento técnico bom** a favor do Docker: camadas compartilhadas, criação em
segundos em vez de um SteamCMD completo, sem SO por instância.

---

## 1. Fase 0 (bloqueio): a criação real no Proxmox

**Nada deste plano começa antes disso.** É o item que já está listado como "o que sobra"
no `architecture-proposal.md`. Motivo: a primeira criação de verdade é o que decide se o
backend de compute precisa de mais um verbo, se o instalador precisa de retry, se a
sonda de saúde precisa de outro prazo. Descobrir isso com dois backends escritos custa o
dobro.

Se a criação real revelar algo que muda a forma das interfaces, **este documento é
atualizado antes da Fase 1 continuar**.

---

## 2. Qual Docker: "máquina pequena" ou "container idiomático"

Existem dois desenhos possíveis, e a diferença entre eles é a diferença entre um plano
de dias e um de meses.

### Modelo A — container como máquina pequena (RECOMENDADO)

O container roda `sshd` e tem um `systemctl` de verdade (ou o shim), o jogo é uma unit,
e cada instância ganha um IP da LAN (rede `macvlan` ou bridge com IP fixo).

Do ponto de vista do painel, **é indistinguível de um CT**:

- a tabela de comandos do painel (`systemctl start/restart/stop`) continua valendo;
- `status_service` (`systemctl show`), `metrics_probe` (o `MainPID`), `log_probe`,
  `backups`, `files` e `terminal` continuam valendo;
- a tabela `servers` (`host`, `ssh_port`, `ssh_user`, `service`) continua valendo;
- porta interna == externa continua valendo, e o NAT do OPNsense continua apontando
  para um IP da LAN.

Isso não é teoria: `ssh.py` já abre dizendo que fala com o container de jogo "(LXC ou
Docker)", e o `docker compose` de desenvolvimento já sobe dois containers de jogo com
sshd e `systemctl` falso. **O painel não muda em nada** — zero dos 964 testes em risco.

Onde está o ganho de escala: a instalação (`ct-phases.sh`) deixa de ser um passo
pós-criação por SSH e vira o **build de uma imagem por jogo**. Instala-se o Palworld uma
vez; a décima instância nasce em segundos e divide as camadas em disco.

### Modelo B — container idiomático

Uma imagem por jogo com PID 1 = o jogo, sem sshd, sem systemd, log por `docker logs`,
shell por `docker exec`, arquivo por volume.

Mais "correto" em espírito, e é o degrau obrigatório se um dia for K8s. Mas cobra o
preço inteiro: as oito sondas de `gamepanel/runtime/` precisam de um segundo
**transporte**, e a tabela de comandos precisa deixar de ser uma lista de linhas de
`systemctl`. Isso é reescrever o lado de 964 testes do repositório, não o de 901.

### Decisão

**Modelo A agora. Modelo B fica registrado como uma decisão futura**, condicionada a
"preciso de mais de um host" — e nesse dia o passo 1 é o transporte do painel, não o
backend do broker.

Consequência importante: **com o Modelo A, a alocação de IP, a alocação de portas e o
OPNsense não mudam nada.** O backend Docker precisa apenas de: criar, iniciar, parar,
destruir, dizer se um container é dele, e dizer o que já está ocupado.

---

## 3. Fase 1 — tirar o Proxmox do vocabulário (só broker)

> **Estado: 1.1 a 1.4 feitos; 1.5 a 1.7 adiados, de propósito.** O corte não foi por
> cansaço: 1.1–1.4 mudam **dado e contrato**, que é o que fica caro depois que houver
> instância em produção. 1.5, 1.6 e 1.7 desenham interface para um backend que ainda não
> existe — e a seção 0 deste documento diz, com razão, que abstração antes da primeira
> criação real codifica palpite. `propose_handle`/`taken_handles` com uma implementação só
> esconderia que o serviço continua sabendo de `ctid_base`; o `BROKER_BACKEND` seria uma
> variável com um valor válido.
>
> **Duas coisas que o plano não previu e que a execução encontrou:**
>
> 1. **`ALTER TABLE ... RENAME COLUMN` preserva a AFINIDADE.** A coluna continua declarada
>    `INTEGER`, então num banco migrado o CTID antigo volta do `SELECT` como `int`, e um
>    `CAST(... AS TEXT)` não adianta — a afinidade converte de volta ao gravar (conferido
>    no sqlite3 desta máquina). Um handle não-numérico, como `palworld-1`, entra como texto
>    normalmente: a afinidade só converte o que *parece* número. Sem tratar isso a coluna
>    fica de tipo misto e `{"307"} | {307}` não se deduplica — a checagem de handle ocupado
>    passaria quando não devia. Reconstruir a tabela corrigiria a declaração e custa caro
>    (`ports` tem `ON DELETE CASCADE` para `instances`), então a saída é normalizar na
>    leitura, com `str()`, em `db.taken` e `wire.instance`. Há teste para os dois lados.
> 2. **O `int(ctid)` do `instance_description` era um guard.** Era ele que recusava
>    `"300; drop"`, e com o handle opaco ele sairia junto — o teste da descrição pegou.
>    A descrição vai para o campo `descr` da regra e o `close_ports` a casa por IGUALDADE:
>    um handle estranho não viraria injeção de shell, mas quebraria o casamento e deixaria
>    **regra órfã no firewall**, que é o jeito silencioso de uma porta ficar aberta para um
>    container que não existe mais. Hoje há `HANDLE_RE` (token simples, `re.ASCII`).
>
> Provado contra o broker de brinquedo do compose, ao vivo: uma instância criada com o
> esquema antigo (`ctid=302`, INTEGER) sobrevive à migration e volta no fio como
> `handle: "302"` **str**, ao lado de uma nova `"303"`; e a tela mostra `proxmox 303` no
> lugar do antigo `CT 300`.

A camada de portas já existe e está limpa: `base.py` define quatro Protocols e
`instance_service.py` não conhece mais nada. O problema não é a interface, é o
**substantivo**: `ctid` atravessou o serviço, o banco e o contrato da API.

Cada item abaixo é caro depois e barato hoje (zero instâncias em produção).

### 1.1 `base.py` — os nomes das interfaces

| hoje | vira | por quê |
|---|---|---|
| `Proxmox` | `Compute` | o Protocol descreve "onde a instância roda", não um produto |
| `Opnsense` | `Ingress` | idem: "quem abre a porta para a internet" |
| `CtSpec` | `InstanceSpec` | CT é LXC; Docker não tem CT |
| o campo `ctid: int` | o campo `handle: str` | opaco: `"307"` no Proxmox, nome do container no Docker |
| `Installer` | (ver 1.6) | é o único que não generaliza |

`Network` fica como está.

### 1.2 O `handle` sobe pelo serviço inteiro

`instance_service` hoje escreve `inst["ctid"]` em oito lugares (criar, desfazer,
desativar, remover, a checagem de dono e a destruição). Todos passam a `handle`.

A assinatura de abrir/fechar portas muda junto — e com ela a descrição da regra no
OPNsense, que hoje é `gamepanel:<ctid>` e passa a ser `gamepanel:<handle>`.

> **Armadilha**: `opnsense.close_ports` casa a descrição por **igualdade** (de
> propósito — por prefixo, apagar o 30 levaria o 300 junto). Mudar o formato da
> descrição **órfã qualquer regra já criada**. Com zero instâncias isso é de graça;
> com dez, é uma limpeza manual no OPNsense. É mais um motivo para fazer agora.

### 1.3 Banco: `handle` e `backend`

Em `db.py`:

```sql
ctid INTEGER NOT NULL UNIQUE   -->   handle  TEXT NOT NULL UNIQUE
                                     backend TEXT NOT NULL DEFAULT 'proxmox'
```

Precisa de migration no mesmo espírito do `_migrate_names` que já existe (a pergunta
dele é "a tabela ainda tem o nome velho?"; a nova é "ainda existe a coluna `ctid`?").
SQLite faz `ALTER TABLE ... RENAME COLUMN`, que preserva os dados — tabela nova mais
cópia é onde se perde linha.

`backend` tem default para que o banco de quem já rodava continue válido sem
adivinhação.

Teste: `test_migration.py` monta o esquema antigo à mão; ganha um caso novo. Os outros
testes vivem num banco novo e não exercitam migration nenhuma.

### 1.4 `wire.py` — o contrato com o painel

O formato de fio da instância passa a levar `handle` e `backend` **no lugar de** `ctid`.

O painel lê `ctid` em **um** lugar só: `instances.html`, na linha que mostra
`{{ i.game }} · {{ i.ip }} · CT {{ i.ctid }}`. Por isso a troca pode ser limpa em vez de
ter um período de compatibilidade com os dois campos — e um campo de compatibilidade que
ninguém remove é como um `SELECT *` volta pela porta dos fundos.

> É exatamente para isto que a camada de fio foi criada: o formato muda com o painel
> junto, o esquema do banco muda com uma migration, e os dois não se arrastam.

### 1.5 `allocator.py` — a regra "CTID = 300 + octeto" é do Proxmox

`allocator.pick_ip_and_ctid` codifica uma convenção ótima e **específica do Proxmox**:
ler o IP e saber o CTID de cabeça. No Docker não há número nenhum para derivar.

Proposta: o allocator continua puro e ganha a forma genérica; quem decide o handle é o
backend, por dois verbos novos no Protocol de compute:

```
propose_handle(ip)  ->  str     # proxmox: str(ctid_base + octeto); docker: o hostname
taken_handles()     ->  set     # substitui a metade "ctids" do que hoje é ctids_and_ips
```

`pick_ip_and_ctid` vira uma escolha de endereço genérica — mesma lógica ("um IP só serve
se o handle dele também estiver livre"), sem a aritmética do CTID dentro. A aritmética
mora em `proxmox.py`, que é de quem ela é.

`BROKER_CTID_BASE` / `BROKER_CTID_INICIO` / `BROKER_CTID_FIM` continuam com esses nomes:
variável de ambiente é **dado gravado em disco**, e renomear exige mexer no
`deploy-broker.ps1`, no `provision-broker-lxc.sh` e no `broker.env` de quem já fez
deploy. Elas passam a ser lidas só pelo backend Proxmox.

### 1.6 O instalador é o Protocol que não generaliza

O `Installer` recebe um IP e fala SSH, porque o modelo é "sobe um CT vazio e instala
dentro". No Modelo A de Docker **não existe etapa de instalação em runtime** — a imagem
já é o jogo instalado.

Proposta: ele deixa de ser um parâmetro do serviço e passa a ser detalhe de quem
implementa o compute. Quem materializa a instância é quem sabe como o jogo chega lá:

- o backend Proxmox recebe o instalador por SSH no construtor e o chama dentro do
  `create`;
- o backend Docker não recebe nada: a imagem já traz tudo.

O `_build` do serviço fica com um passo a menos (cria → inicia → abre firewall), e o
`log` de progresso passa a ser argumento do `create`, para a tela continuar mostrando em
que fase a instalação está.

> Alternativa considerada e descartada: manter o Protocol e dar um no-op ao Docker.
> Descartada porque um no-op é uma mentira barata que sobrevive por anos — e porque o
> log de fases ficaria vazio no Docker sem ninguém entender por quê.

### 1.7 `config.py` — escolher o backend

Uma variável nova, `BROKER_BACKEND` (`proxmox` | `docker`, padrão `proxmox`), lida no
mesmo desenho que já existe: **lista TODOS os problemas de uma vez, só pelo NOME da
variável**, nunca o valor, e config ruim derruba o START (`SystemExit(2)`), nunca um
pedido.

Cada backend exige um conjunto próprio de variáveis. A validação tem que ser
**condicional ao backend escolhido** — cobrar a URL do Proxmox de quem escolheu Docker
transformaria a mensagem de erro em ruído, que é justamente o que esse desenho existe
para evitar.

---

## 4. Fase 2 — o backend Docker

Arquivo novo: `src/gamebroker/runtime/docker.py`, implementando o Protocol de compute.

### 4.1 Como ele fala com o Docker

**Por HTTP, reusando `http_client.Client`** — não pela CLI e não pela biblioteca `docker`
do PyPI (o broker em produção também não baixa pacote de lugar nenhum; a regra de "só
stdlib + o flask do apt" vale para os dois pacotes).

A API do Docker fala HTTP sobre um socket unix. O cliente hoje é HTTPS com impressão
fixada; ele ganharia um modo "socket unix" — e aí a trava de segurança deixa de ser a
impressão do certificado e passa a ser **a permissão do socket**, que é uma coisa
diferente e precisa estar escrita no código.

> **Decisão de segurança a tomar ANTES de escrever o arquivo.** Acesso ao socket do
> Docker é equivalente a root no host. Hoje o broker fala com um Proxmox REMOTO por token
> com escopo de pool — o raio de ação é limitado pelo que o token enxerga. Com o socket
> local não há escopo nenhum: um defeito no broker vira root no host inteiro, e o host é
> onde o próprio broker mora.
>
> Opções, em ordem de preferência:
> 1. **Docker num host separado**, por TCP com TLS e impressão fixada — que é exatamente
>    o que o `http_client` já sabe fazer, e mantém a simetria com o Proxmox.
> 2. Proxy de socket com lista fechada de endpoints.
> 3. Socket direto (só aceitável em desenvolvimento).

### 4.2 O que cada verbo faz

| verbo | Docker |
|---|---|
| `create` | `POST /containers/create`: imagem do jogo, rede macvlan com IP fixo, limites de memória/cpu, `restart=unless-stopped` |
| `start` / `stop` / `destroy` | `POST /containers/{id}/start`, `/stop`, `DELETE /containers/{id}` |
| `belongs_to_broker` | **label** `gamebroker=1` — o equivalente do pool do Proxmox |
| `taken_handles` / endereços ocupados | `GET /containers/json?all=1` |
| `propose_handle` | o hostname da instância (`<jogo>-<n>`), já único pelo índice do banco |
| `reachable` | `GET /_ping`, com prazo curto |

> **Armadilha herdada**: a identidade de um CT do broker é o **pool**, não a tag (a tag é
> gravada depois; o token nem pode gravá-la na criação). No Docker a label pode ser
> aplicada na criação, então a identidade é a label — mas ela é escrita por quem cria, e
> um container feito à mão com a mesma label seria adotado. O `belongs_to_broker` do
> Docker deve exigir **label E linha no banco**, que é o que o Proxmox já faz na prática.

Prazo curto na sonda de saúde vale aqui também: um firewall que descarta pacote não pode
fazer a saúde demorar 30 s.

### 4.3 A imagem do jogo

`ct-phases.sh` ganha um **terceiro consumidor**. Hoje são dois: `provision-game-lxc.sh`
(no host, por `pct exec`) e `ct-install.sh` (dentro do CT, o que o broker roda por SSH).
O terceiro é um `Dockerfile` que roda as mesmas fases num `RUN`.

Regras que continuam valendo e precisam de atenção:

- `install.env` é sempre `shlex.quote`; receita desconhecida derruba a instalação;
- hook (`PRE/POST_INSTALL_CMD`) só existe no catálogo curado, nunca em jogo da API;
- escrever texto para o bash no Windows exige `newline="\n"` (o `\r` aparece depois como
  `WINDOWS_RUNTIME invalido: ''`).

**A chave SSH do broker não entra na imagem.** No CT ela é removida no fim (a limpeza
roda sempre, e se ela não sair a criação FALHA); numa imagem ela ficaria em camada,
visível por `docker history` para sempre. O acesso do painel usa a chave do PAINEL,
injetada na criação do container (`authorized_keys` por volume ou variável), nunca assada
na imagem.

### 4.4 Prova

`docker/ct-sandbox/compare.sh` hoje compara "antes x depois" do instalador para 8 jogos
com `pct`, `systemctl`, `apt-get` e SteamCMD falsos. Ele ganha um terceiro eixo: **host x
broker x imagem Docker** — as três rotas têm que produzir o mesmo `install.env` e a mesma
unit systemd. Sem isso a Fase 2 é no escuro: **não existe teste de shell no
repositório**, a prova são os sandboxes.

Do lado Python: `fakes.py` ganha um dobrê de Docker (ao lado de `FakeProxmox`,
`FakeOpnsense`, `FakeInstaller` e `FakeNetwork`), e `fake_http.py` ganha um servidor
falso que responde a API do Docker — no mesmo desenho do falso do Proxmox, **repetindo as
regras que o Docker real impõe**, para que regredir quebre teste.

---

## 5. Fase 3 — o lado do painel

Pequena, e só depois que a Fase 1 estiver no `main`.

- `instances.html`: `CT {{ i.ctid }}` vira o par backend + handle. Lembrar da regra de
  tabela no celular: **uma coluna** — com estado e ações em colunas próprias, as ações
  saem da tela.
- `i18n/pt.py` e `i18n/en.py`: chave nova para o rótulo do backend, **mesmas chaves nos
  dois** (`test_i18n.py` cobra a paridade). Chave em inglês, no formato `area.assunto`,
  nunca o português virado slug.
- `broker_service.py`: repassar os campos novos. Nada além disso — quem decide é o
  broker.
- A tabela `servers` **não muda**. É o ponto todo do Modelo A.

---

## 6. O que precisa passar antes de dizer que terminou

1. `uv run pytest` — a suíte inteira, da raiz (964 do painel + 901 do broker).
2. `MSYS_NO_PATHCONV=1 docker compose exec -T -w /workspace panel python3 -m pytest -q`
   — no container, que é a verdade.
3. `bash docker/ct-sandbox/compare.sh` — obrigatório, porque a Fase 2 mexe em fase de
   instalação.
4. `bash docker/ct-sandbox/broker.sh` — se `config.py` ou o provisionamento mudarem.
5. A varredura de `curl` por todas as telas, como admin **e como operador** — template
   quebrado não aparece em teste nenhum, e o 403 do operador mora ali.
6. Uma criação real por backend, ponta a ponta. Backend que nunca criou nada de verdade
   não está pronto, por mais verde que a suíte esteja.

---

## 7. Fora do escopo, explicitamente

- **Kubernetes.** Volta à mesa quando houver mais de um host. O passo anterior a ele é o
  Modelo B (transporte não-SSH no painel), não este plano.
- **Modelo B de Docker** (PID 1 = jogo, sem sshd). Registrado na seção 2, com o motivo.
- **Os limites de escala da seção 0** (uma operação por vez, 1 worker, faixa de portas).
  São reais, mas independem de backend e merecem decisão própria.
- **Migrar instâncias existentes entre backends.** Um CT não vira container; é criar de
  novo e restaurar backup.

---

## 8. Coordenação

Há outra sessão trabalhando na Fase 4 (`src/gamepanel/games/` — o catálogo de campos
virando `adapters/` + `registry.py`). As áreas quase não se cruzam: este plano é
`src/gamebroker/**` mais três arquivos do painel, e só na Fase 3.

Os dois pontos de encontro:

- **`src/gamepanel/app.py`** — as duas frentes mexem, por motivos diferentes. Rebase,
  não merge cego.
- **`i18n/pt.py` / `en.py`** — as duas acrescentam chave. Conflito de acréscimo é fácil,
  desde que a paridade entre os dois catálogos continue.

Por isso a Fase 1 e a Fase 2 são **só do broker** e podem entrar sozinhas; a Fase 3 (a
única que toca o painel) fica para depois que a Fase 4 aterrissar.
