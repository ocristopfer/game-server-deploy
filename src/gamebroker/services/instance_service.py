"""Orchestration: reserves, creates, installs, opens the firewall and undoes if something goes wrong.

All the business rules live here; `api.py` only translates HTTP and `backends.py` only talks
to the outside world. Swapping a backend changes nothing in this file.
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
    # Non-zero: the CTID comes from the IP (`ctid_base` + last number) and `ctids` is not used.
    ctid_base: int = 0
    # Broker-only range for `shiftable` games; must not overlap the ports of the older servers.
    ports: range = range(31000, 32000)
    max_instances: int = 8
    max_creations_per_hour: int = 4


def _in_thread(task: Callable[[], None]) -> None:
    threading.Thread(target=task, daemon=True, name="broker-operacao").start()


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _actor_of(bruto: str) -> str:
    # The panel says who clicked; the broker trusts it enough to record, never to decide.
    return bruto if _ACTOR_RE.fullmatch(bruto or "") else UNKNOWN_ACTOR


class Service:
    # INJECTION constructor: the 9 are collaborators, not data. Wrapping them in an object
    # would hide from the reader the list of what the service depends on - which is the most
    # important thing to know here. The CLAUDE.md rule is 'more than 13 parameters: pass an object'.
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
        # Two simultaneous creations would pick the same IP before either one wrote it.
        self._trava = threading.Lock()
        # Cancellation request for each creation IN PROGRESS IN THIS PROCESS. Memory and not the
        # database on purpose: whoever obeys the request is the thread doing the installation, and
        # it only exists here. After a restart the old operation has no thread at all, and
        # "cancel" would have nobody to tell (the broker runs with a single worker).
        self._cancels: dict[str, threading.Event] = {}

    # --- queries ----------------------------------------------------------

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
        """Returns the restored curated game, or `{}` when the game no longer exists."""
        restored = self.catalog.remove(key)
        action = "catalogo-restaurar" if restored is not None else "catalogo-apagar"
        self.db.audit(_actor_of(actor), action, key, "ok")
        return restored.as_public() if restored is not None else {}

    # --- create -----------------------------------------------------------

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
        """What a creation of this game would get NOW: CT, IP and ports. Nothing is reserved.

        The same computation as the creation (`_choose`), not a copy of it: a preview that
        computes differently lies exactly when someone looks at it - when the expected number
        is not the one that comes out.
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
        # Snapshot from outside (Proxmox, OPNsense) + what the database already reserved: the CT
        # may have been created by hand, and so may the NAT rule.
        handles_px, ips_px = self.compute.handles_and_ips()
        handles_db, ips_db, ports_db = self.db.taken()
        # The CTID arithmetic is Proxmox's and stays here on purpose: moving it into the
        # backend (section 1.5 of the Docker plan) only pays off once there is a second
        # backend, and section 0 of the plan itself says abstraction designed before the
        # first real creation encodes a guess. What goes up through the service is already `handle`.
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
            # Between one phase and the next: creating the CT and starting it are Proxmox API
            # calls, which cannot be interrupted midway. The installation (the slow part) stops on its own.
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
            # The firewall opens last: the game is not exposed while it is still installing.
            log("abrindo as portas no firewall")
            self.ingress.open_ports(str(inst["handle"]), inst["ip"], ports)
        except Exception as error:  # noqa: BLE001
            # When cancelled, the error that bubbles up is the killed process's ("codigo -9"): the
            # real reason is the request, and that is what goes to the log and the audit.
            reason = CANCELLED if stop.is_set() else str(error)
            self._undo(op_id, inst, created, reason)
            self.db.audit(actor, "criar", inst["name"], "cancelado" if stop.is_set() else "falhou", reason)
            return
        self.db.set_state(instance_id, STATE_ACTIVE)
        self.db.finish_operation(op_id, OP_OK, record_for_the_panel(inst, game, ports))
        self.db.audit(actor, "criar", inst["name"], "ok", f"handle {inst['handle']}")

    def cancel(self, op_id: str, actor: str) -> dict:
        """Asks the creation in progress to stop. Stopping and undoing is done by the creation
        thread itself: the CT is deleted and IP, CTID and ports become free again."""
        actor = _actor_of(actor)
        op = self.db.operation(op_id)
        if op is None:
            raise NotFound("operacao desconhecida")
        stop = self._cancels.get(op_id)
        if op["state"] != OP_RUNNING or stop is None:
            raise Conflict("essa operacao nao esta em andamento; nao ha o que cancelar")
        if not stop.is_set():
            # Write BEFORE signaling: the creation thread reacts immediately, and the request would
            # show up in the log after the "reserva liberada" it caused.
            self.db.append_log(op_id, f"CANCELAMENTO pedido por {actor}: interrompendo e desfazendo")
            self.db.audit(actor, "cancelar", op_id, "aceito")
            stop.set()
        return {"operation_id": op_id, "cancelling": True}

    def _logger(self, op_id: str) -> Callable[[str], None]:
        return lambda line: self.db.append_log(op_id, line)

    def _undo(self, op_id: str, inst: dict, created: bool, error: str) -> None:
        """Goes back to the previous state. If even the undo fails, the reservation is marked
        as `falhou` (it does not vanish): IP and ports stay blocked until someone removes it."""
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

    # --- deactivate / remove ----------------------------------------------

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
            return  # the creation never even made it into the pool: there is no CT of ours to destroy
        # "Not in the pool" may be a CT deleted by hand OR a CT moved/owned by someone else, and the
        # token only sees the pool: the two cases are indistinguishable (both give 403). Releasing
        # the CTID/IP in that case could free a CT that still exists; so only on explicit request.
        raise Conflict(
            f"o CT {handle} nao pertence ao broker (nao esta no pool); nada foi alterado. Se ele nao "
            "existe mais no Proxmox, remova de novo com db_only para limpar so o registro")

    def _instance(self, instance_id: int) -> dict:
        inst = self.db.instance(instance_id)
        if inst is None:
            raise NotFound("instancia desconhecida")
        return inst

    def _require_from_broker(self, handle: str) -> None:
        # The Proxmox token sees the whole pool; the tag and the database row are what stop
        # the broker from touching a CT that is not its own.
        if not self.compute.belongs_to_broker(handle):
            raise Conflict(f"o CT {handle} nao pertence ao broker; nada foi alterado")


def record_for_the_panel(inst: dict, game: Game, ports: list[AllocatedPort]) -> dict:
    """The panel's `DeployServer` fields: with them it calls `ensure_server`."""
    return {
        "broker_id": inst["id"], "name": inst["name"], "host": inst["ip"],
        "service": f"{game.key}.service",
        "game_port": alocador.port_with_role(ports, alocador.ROLE_GAME),
        # By BASE, not by role: in Enshrouded the query is the game port itself (15637), which
        # gets the game role - by role the panel received 0 and the server was born without
        # A2S counting.
        "query_port": (alocador.port_from_base(ports, game.query_port)
                       if game.query_port else 0),
        "ports": [str(p) for p in ports],
        "config_path": game.config_path, "config_files": list(game.config_files),
        "backup_paths": list(game.backup_paths), "player_source": game.player_source,
        "join_re": game.join_re, "leave_re": game.leave_re, "log_path": game.log_path,
        "max_players": game.max_players,
        "notes": f"Criado pelo broker (CT {inst['handle']})",
    }
