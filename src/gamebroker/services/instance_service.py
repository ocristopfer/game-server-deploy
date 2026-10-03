"""Orquestracao: reserva, cria, instala, abre o firewall e desfaz se der errado.

Aqui mora toda a regra de negocio; `api.py` so traduz HTTP e `backends.py` so fala com o
mundo de fora. Trocar um backend nao muda nada deste arquivo.
"""
from __future__ import annotations

import re
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

import gamebroker.services.allocator as alocador
from gamebroker.domain import wire
from gamebroker.domain.exceptions import Conflict, NotFound, QuotaExceeded, ValidationError
from gamebroker.persistence.db import (
    OP_FAILED,
    OP_OK,
    OP_RUNNING,
    STATE_ACTIVE,
    STATE_DEACTIVATED,
    STATE_FAILED,
    Db,
)
from gamebroker.runtime.base import Compute, Ingress, Installer, InstanceSpec, Network
from gamebroker.services.allocator import AllocatedPort
from gamebroker.services.catalog import NAME_RE, Catalog, Game

_ACTOR_RE = re.compile(r"[A-Za-z0-9._-]{1,32}", re.ASCII)
UNKNOWN_ACTOR = "desconhecido"
ERROR_MAX = 300
CANCELLED = "instalacao cancelada a pedido"


@dataclass(frozen=True)
class Config:
    ctids: range = range(300, 400)
    ips: tuple[str, ...] = ()
    # Diferente de 0: o CTID sai do IP (`ctid_base` + ultimo numero) e `ctids` nao e usado.
    ctid_base: int = 0
    # Faixa so do broker para jogos `shiftable`; nao pode cruzar com as portas dos servidores antigos.
    ports: range = range(31000, 32000)
    max_instances: int = 8
    max_creations_per_hour: int = 4


def _in_thread(task: Callable[[], None]) -> None:
    threading.Thread(target=task, daemon=True, name="broker-operacao").start()


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _actor_of(bruto: str) -> str:
    # O painel diz quem clicou; o broker so confia o bastante para registrar, nunca para decidir.
    return bruto if _ACTOR_RE.fullmatch(bruto or "") else UNKNOWN_ACTOR


class Service:
    # Construtor de INJECAO: os 9 sao colaboradores, nao dados. Embrulha-los num objeto
    # esconderia de quem le a lista do que o servico depende — que e a coisa que mais
    # importa saber aqui. A regra do CLAUDE.md e 'mais de 13 parametros: passe um objeto'.
    def __init__(self, db: Db, catalog: Catalog, compute: Compute,  # noqa: PLR0913, PLR0917
                 ingress: Ingress,
                 installer: Installer, network: Network, config: Config,
                 run: Callable[[Callable[[], None]], None] = _in_thread,
                 clock: Callable[[], datetime] = _now_utc):
        self.db = db
        self.catalog = catalog
        self.compute = compute
        self.ingress = ingress
        self.installer = installer
        self.network = network
        self.config = config
        self._executar = run
        self._now = clock
        # Duas criacoes ao mesmo tempo escolheriam o mesmo IP antes de qualquer uma gravar.
        self._trava = threading.Lock()
        # Pedido de cancelamento de cada criacao EM ANDAMENTO NESTE PROCESSO. Memoria e nao
        # banco de proposito: quem obedece ao pedido e a thread que esta instalando, e ela
        # so existe aqui. Depois de um restart a operacao antiga nao tem thread nenhuma, e
        # "cancelar" nao teria a quem avisar (o broker roda com um worker so).
        self._cancels: dict[str, threading.Event] = {}

    # --- consultas --------------------------------------------------------

    def health(self) -> dict:
        return {"broker": True, "proxmox": self.compute.reachable(),
                "opnsense": self.ingress.reachable(),
                "catalog_errors": list(self.catalog.errors)}

    def instances(self) -> list[dict]:
        return [wire.instance(r) for r in self.db.instances()]

    def operation(self, op_id: str) -> dict:
        op = self.db.operation(op_id)
        if op is None:
            raise NotFound("operacao desconhecida")
        return wire.operation(op)

    def add_game(self, data: object, actor: str) -> dict:
        game = self.catalog.add_dynamic(data)
        self.db.audit(_actor_of(actor), "catalogo-adicionar", game.key, "ok")
        return game.as_public()

    def update_game(self, key: str, data: object, actor: str) -> dict:
        game = self.catalog.update(key, data)
        self.db.audit(_actor_of(actor), "catalogo-editar", game.key, "ok")
        return game.as_public()

    def remove_game(self, key: str, actor: str) -> dict:
        """Devolve o curado restaurado, ou `{}` quando o jogo deixou de existir."""
        restored = self.catalog.remove(key)
        action = "catalogo-restaurar" if restored is not None else "catalogo-apagar"
        self.db.audit(_actor_of(actor), action, key, "ok")
        return restored.as_public() if restored is not None else {}

    # --- criar ------------------------------------------------------------

    def create(self, game_key: str, name: str, actor: str) -> dict:
        actor = _actor_of(actor)
        name = self._valid_name(name)
        game = self.catalog.get(game_key)
        if not game.creatable:
            raise Conflict(f"{game.name} nao pode ser criado pela API: {game.reason}")
        with self._trava:
            self._check_quotas()
            instance_id, ports = self._reserve(game, name, actor)
            op_id = self.db.create_operation(instance_id, "criar")
            self._cancels[op_id] = threading.Event()
        self.db.audit(actor, "criar", f"{game.key}:{name}", "aceito", f"instancia {instance_id}")
        self._executar(lambda: self._build(op_id, instance_id, game, ports, actor))
        return {"operation_id": op_id, "instance_id": instance_id}

    @staticmethod
    def _valid_name(name: object) -> str:
        if not isinstance(name, str) or not NAME_RE.fullmatch(name):
            raise ValidationError("nome", "use letras, numeros, espaco, ponto, hifen ou sublinhado (ate 40)")
        return name

    def _check_quotas(self) -> None:
        if self.db.operation_in_progress():
            raise QuotaExceeded("ja ha uma operacao em andamento; aguarde ela terminar")
        if self.db.count_instances() >= self.config.max_instances:
            raise QuotaExceeded(f"limite de {self.config.max_instances} instancias atingido")
        since = (self._now() - timedelta(hours=1)).isoformat(timespec="seconds")
        if self.db.creations_since(since) >= self.config.max_creations_per_hour:
            raise QuotaExceeded(f"limite de {self.config.max_creations_per_hour} criacoes por hora atingido")

    def preview(self, game_key: str) -> dict:
        """O que uma criacao deste jogo receberia AGORA: CT, IP e portas. Nada e reservado.

        Mesma conta da criacao (`_choose`), e nao uma copia dela: uma previa que calcula de
        outro jeito mente justamente no caso em que alguem a consulta — quando o numero
        esperado nao e o que sai.
        """
        game = self.catalog.get(game_key)
        if not game.creatable:
            raise Conflict(f"{game.name} nao pode ser criado pela API: {game.reason}")
        handle, ip, ports = self._choose(game)
        return {"game": game.key, "handle": handle, "ip": ip,
                "ports": [wire.port(asdict(p)) for p in ports]}

    def _reserve(self, game: Game, name: str, actor: str) -> tuple[int, list[AllocatedPort]]:
        handle, ip, ports = self._choose(game)
        instance_id = self.db.reserve(handle, ip, game.key, name, f"{game.key}-{handle}",
                                      actor, ports)
        return instance_id, ports

    def _choose(self, game: Game) -> tuple[str, str, list[AllocatedPort]]:
        # Snapshot de fora (Proxmox, OPNsense) + o que o banco ja reservou: o CT pode ter
        # sido criado na mao, e a regra de NAT tambem.
        handles_px, ips_px = self.compute.handles_and_ips()
        handles_db, ips_db, ports_db = self.db.taken()
        # A aritmetica do CTID e do Proxmox e continua aqui de proposito: leva-la para
        # dentro do backend (secao 1.5 do plano do Docker) so paga quando houver um
        # segundo backend, e a secao 0 do proprio plano diz que abstracao desenhada antes
        # da primeira criacao real codifica palpite. O que sobe pelo servico ja e `handle`.
        taken_handles = handles_px | handles_db
        if self.config.ctid_base:
            ip, ctid = alocador.pick_ip_and_ctid(self.config.ips, self.config.ctid_base,
                                                   {int(h) for h in taken_handles if h.isdigit()},
                                                   ips_px | ips_db, self.network.answers)
        else:
            ctid = alocador.pick_ctid(self.config.ctids,
                                      {int(h) for h in taken_handles if h.isdigit()})
            ip = alocador.pick_ip(self.config.ips, ips_px | ips_db, self.network.answers)
        ports = alocador.allocate_ports(game, self.ingress.external_ports() | ports_db, self.config.ports)
        return str(ctid), ip, ports

    def _build(self, op_id: str, instance_id: int, game: Game, ports: list[AllocatedPort],
                   actor: str) -> None:
        stop = self._cancels.get(op_id) or threading.Event()
        try:
            self._build_steps(op_id, instance_id, game, ports, actor, stop)
        finally:
            self._cancels.pop(op_id, None)

    def _build_steps(self, op_id: str, instance_id: int, game: Game,
                     ports: list[AllocatedPort], actor: str, stop: threading.Event) -> None:
        inst = self.db.instance(instance_id)
        if inst is None:
            return
        log = self._logger(op_id)
        created = False

        def check() -> None:
            # Entre uma fase e outra: criar o CT e liga-lo sao chamadas a API do Proxmox,
            # que nao se interrompem no meio. A instalacao (a parte demorada) para sozinha.
            if stop.is_set():
                raise RuntimeError(CANCELLED)

        try:
            check()
            log(f"criando o container {inst['handle']} ({inst['ip']})")
            self.compute.create(InstanceSpec(
                handle=str(inst["handle"]), hostname=inst["hostname"], ip=inst["ip"], game=game.key,
                memory_mb=game.memory_mb, cores=game.cores, disk_gb=game.disk_gb))
            created = True
            check()
            self.compute.start(str(inst["handle"]))
            check()
            self.installer.install(inst["ip"], game, ports, log, stop)
            check()
            # O firewall abre por ultimo: o jogo nao fica exposto enquanto ainda instala.
            log("abrindo as portas no firewall")
            self.ingress.open_ports(str(inst["handle"]), inst["ip"], ports)
        except Exception as error:  # noqa: BLE001
            # Cancelado, o erro que sobe e o do processo morto ("codigo -9"): o motivo de
            # verdade e o pedido, e e ele que vai para o log e para a auditoria.
            reason = CANCELLED if stop.is_set() else str(error)
            self._undo(op_id, inst, created, reason)
            self.db.audit(actor, "criar", inst["name"], "cancelado" if stop.is_set() else "falhou", reason)
            return
        self.db.set_state(instance_id, STATE_ACTIVE)
        self.db.finish_operation(op_id, OP_OK, record_for_the_panel(inst, game, ports))
        self.db.audit(actor, "criar", inst["name"], "ok", f"handle {inst['handle']}")

    def cancel(self, op_id: str, actor: str) -> dict:
        """Pede para a criacao em andamento parar. Quem para e desfaz e a propria thread
        da criacao: o CT e apagado e IP, CTID e portas voltam a ficar livres."""
        actor = _actor_of(actor)
        op = self.db.operation(op_id)
        if op is None:
            raise NotFound("operacao desconhecida")
        stop = self._cancels.get(op_id)
        if op["state"] != OP_RUNNING or stop is None:
            raise Conflict("essa operacao nao esta em andamento; nao ha o que cancelar")
        if not stop.is_set():
            # Escreve ANTES de sinalizar: a thread da criacao reage na hora, e o pedido sairia
            # no log depois do "reserva liberada" que ele mesmo causou.
            self.db.append_log(op_id, f"CANCELAMENTO pedido por {actor}: interrompendo e desfazendo")
            self.db.audit(actor, "cancelar", op_id, "aceito")
            stop.set()
        return {"operation_id": op_id, "cancelling": True}

    def _logger(self, op_id: str) -> Callable[[str], None]:
        return lambda line: self.db.append_log(op_id, line)

    def _undo(self, op_id: str, inst: dict, created: bool, error: str) -> None:
        """Volta ao estado anterior. Se nem o desfazer der certo, a reserva fica marcada
        como `falhou` (nao some): IP e portas continuam bloqueados ate alguem remover."""
        log = self._logger(op_id)
        log(f"ERRO: {error[:ERROR_MAX]}")
        cleaned = True
        try:
            self.ingress.close_ports(str(inst["handle"]))
            if created:
                self.compute.destroy(str(inst["handle"]))
        except Exception as failure:  # noqa: BLE001
            cleaned = False
            log(f"nao consegui desfazer tudo: {str(failure)[:ERROR_MAX]}")
        if cleaned:
            self.db.delete_instance(inst["id"])
            log("reserva liberada")
        else:
            self.db.set_state(inst["id"], STATE_FAILED, error)
        self.db.finish_operation(op_id, OP_FAILED)

    # --- desativar / remover ---------------------------------------------

    def deactivate(self, instance_id: int, actor: str) -> dict:
        actor = _actor_of(actor)
        inst = self._instance(instance_id)
        if inst["state"] != STATE_ACTIVE:
            raise Conflict("so uma instancia ativa pode ser desativada")
        self._require_from_broker(str(inst["handle"]))
        self.ingress.close_ports(str(inst["handle"]))
        self.compute.stop(str(inst["handle"]))
        self.db.set_state(instance_id, STATE_DEACTIVATED)
        self.db.audit(actor, "desativar", inst["name"], "ok")
        return {"id": instance_id, "state": STATE_DEACTIVATED}

    def remove(self, instance_id: int, confirmation: object, actor: str,
                db_only: bool = False) -> dict:
        actor = _actor_of(actor)
        inst = self._instance(instance_id)
        if inst["state"] not in (STATE_DEACTIVATED, STATE_FAILED):
            raise Conflict("desative a instancia antes de remover")
        if confirmation != inst["name"]:
            raise ValidationError("confirma", "digite o nome exato da instancia para confirmar")
        self.ingress.close_ports(str(inst["handle"]))
        if not db_only:
            self._destroy_ct(inst)
        self.db.delete_instance(instance_id)
        self.db.audit(actor, "esquecer" if db_only else "remover", inst["name"], "ok")
        return {"id": instance_id, "removed": True, "db_only": db_only}

    def _destroy_ct(self, inst: dict) -> None:
        handle = str(inst["handle"])
        if self.compute.belongs_to_broker(handle):
            self.compute.destroy(handle)
            return
        if inst["state"] == STATE_FAILED:
            return  # a criacao nem chegou a existir no pool: nao ha CT nosso para destruir
        # "Nao esta no pool" pode ser CT apagado a mao OU CT movido/de outro dono, e o token
        # so enxerga o pool: os dois casos sao indistinguiveis (ambos dao 403). Liberar o
        # CTID/IP nesse caso poderia soltar um CT que ainda existe; entao so com pedido explicito.
        raise Conflict(
            f"o CT {handle} nao pertence ao broker (nao esta no pool); nada foi alterado. Se ele nao "
            "existe mais no Proxmox, remova de novo com db_only para limpar so o registro")

    def _instance(self, instance_id: int) -> dict:
        inst = self.db.instance(instance_id)
        if inst is None:
            raise NotFound("instancia desconhecida")
        return inst

    def _require_from_broker(self, handle: str) -> None:
        # O token do Proxmox enxerga o pool inteiro; a tag e a linha no banco sao o que
        # impede o broker de mexer num CT que nao e dele.
        if not self.compute.belongs_to_broker(handle):
            raise Conflict(f"o CT {handle} nao pertence ao broker; nada foi alterado")


def record_for_the_panel(inst: dict, game: Game, ports: list[AllocatedPort]) -> dict:
    """Os campos de `DeployServer` do painel: com isso ele chama `ensure_server`."""
    return {
        "broker_id": inst["id"], "name": inst["name"], "host": inst["ip"],
        "service": f"{game.key}.service",
        "game_port": alocador.port_with_role(ports, alocador.ROLE_GAME),
        # Pela BASE, e nao pelo papel: no Enshrouded a consulta e a propria porta do jogo
        # (15637), que fica com o papel de jogo - pelo papel o painel recebia 0 e nascia sem
        # contagem A2S.
        "query_port": (alocador.port_from_base(ports, game.query_port)
                       if game.query_port else 0),
        "ports": [str(p) for p in ports],
        "config_path": game.config_path, "config_files": list(game.config_files),
        "backup_paths": list(game.backup_paths), "player_source": game.player_source,
        "join_re": game.join_re, "leave_re": game.leave_re, "log_path": game.log_path,
        "max_players": game.max_players,
        "notes": f"Criado pelo broker (CT {inst['handle']})",
    }
