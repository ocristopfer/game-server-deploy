"""Orquestracao: reserva, cria, instala, abre o firewall e desfaz se der errado.

Aqui mora toda a regra de negocio; `api.py` so traduz HTTP e `backends.py` so fala com o
mundo de fora. Trocar um backend nao muda nada deste arquivo.
"""
from __future__ import annotations

import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import gamebroker.services.allocator as alocador
from gamebroker.domain import wire
from gamebroker.domain.exceptions import Conflict, NotFound, QuotaExceeded, ValidationError
from gamebroker.persistence.db import ESTADO_ATIVA, ESTADO_DESATIVADA, ESTADO_FALHOU, OP_ERRO, OP_OK, Db
from gamebroker.runtime.base import CtSpec, Installer, Network, Opnsense, Proxmox
from gamebroker.services.allocator import AllocatedPort
from gamebroker.services.catalog import NAME_RE, Catalog, Game

_ACTOR_RE = re.compile(r"[A-Za-z0-9._-]{1,32}", re.ASCII)
UNKNOWN_ACTOR = "desconhecido"
ERROR_MAX = 300


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
    return datetime.now(timezone.utc)


def _actor_of(bruto: str) -> str:
    # O painel diz quem clicou; o broker so confia o bastante para registrar, nunca para decidir.
    return bruto if _ACTOR_RE.fullmatch(bruto or "") else UNKNOWN_ACTOR


class Service:
    def __init__(self, db: Db, catalog: Catalog, proxmox: Proxmox, opnsense: Opnsense,
                 installer: Installer, network: Network, config: Config,
                 run: Callable[[Callable[[], None]], None] = _in_thread,
                 clock: Callable[[], datetime] = _now_utc):
        self.db = db
        self.catalog = catalog
        self.proxmox = proxmox
        self.opnsense = opnsense
        self.installer = installer
        self.network = network
        self.config = config
        self._executar = run
        self._agora = clock
        # Duas criacoes ao mesmo tempo escolheriam o mesmo IP antes de qualquer uma gravar.
        self._trava = threading.Lock()

    # --- consultas --------------------------------------------------------

    def health(self) -> dict:
        return {"broker": True, "proxmox": self.proxmox.reachable(),
                "opnsense": self.opnsense.reachable(),
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
        desde = (self._agora() - timedelta(hours=1)).isoformat(timespec="seconds")
        if self.db.creations_since(desde) >= self.config.max_creations_per_hour:
            raise QuotaExceeded(f"limite de {self.config.max_creations_per_hour} criacoes por hora atingido")

    def _reserve(self, game: Game, name: str, actor: str) -> tuple[int, list[AllocatedPort]]:
        # Snapshot de fora (Proxmox, OPNsense) + o que o banco ja reservou: o CT pode ter
        # sido criado na mao, e a regra de NAT tambem.
        ctids_px, ips_px = self.proxmox.ctids_and_ips()
        ctids_db, ips_db, portas_db = self.db.taken()
        if self.config.ctid_base:
            ip, ctid = alocador.pick_ip_and_ctid(self.config.ips, self.config.ctid_base,
                                                   ctids_px | ctids_db, ips_px | ips_db, self.network.answers)
        else:
            ctid = alocador.pick_ctid(self.config.ctids, ctids_px | ctids_db)
            ip = alocador.pick_ip(self.config.ips, ips_px | ips_db, self.network.answers)
        ports = alocador.allocate_ports(game, self.opnsense.external_ports() | portas_db, self.config.ports)
        instance_id = self.db.reserve(ctid, ip, game.key, name, f"{game.key}-{ctid}", actor, ports)
        return instance_id, ports

    def _build(self, op_id: str, instance_id: int, game: Game, ports: list[AllocatedPort],
                   actor: str) -> None:
        inst = self.db.instance(instance_id)
        if inst is None:
            return
        log = self._logger(op_id)
        created = False
        try:
            log(f"criando o container {inst['ctid']} ({inst['ip']})")
            self.proxmox.create_ct(CtSpec(
                ctid=inst["ctid"], hostname=inst["hostname"], ip=inst["ip"], game=game.key,
                memory_mb=game.memory_mb, cores=game.cores, disk_gb=game.disk_gb))
            created = True
            self.proxmox.start(inst["ctid"])
            self.installer.install(inst["ip"], game, ports, log)
            # O firewall abre por ultimo: o jogo nao fica exposto enquanto ainda instala.
            log("abrindo as portas no firewall")
            self.opnsense.open_ports(inst["ctid"], inst["ip"], ports)
        except Exception as error:  # noqa: BLE001
            self._undo(op_id, inst, created, str(error))
            self.db.audit(actor, "criar", inst["name"], "falhou", str(error))
            return
        self.db.set_state(instance_id, ESTADO_ATIVA)
        self.db.finish_operation(op_id, OP_OK, record_for_the_panel(inst, game, ports))
        self.db.audit(actor, "criar", inst["name"], "ok", f"ctid {inst['ctid']}")

    def _logger(self, op_id: str) -> Callable[[str], None]:
        return lambda line: self.db.append_log(op_id, line)

    def _undo(self, op_id: str, inst: dict, created: bool, error: str) -> None:
        """Volta ao estado anterior. Se nem o desfazer der certo, a reserva fica marcada
        como `falhou` (nao some): IP e portas continuam bloqueados ate alguem remover."""
        log = self._logger(op_id)
        log(f"ERRO: {error[:ERROR_MAX]}")
        limpou = True
        try:
            self.opnsense.close_ports(inst["ctid"])
            if created:
                self.proxmox.destroy(inst["ctid"])
        except Exception as failure:  # noqa: BLE001
            limpou = False
            log(f"nao consegui desfazer tudo: {str(failure)[:ERROR_MAX]}")
        if limpou:
            self.db.delete_instance(inst["id"])
            log("reserva liberada")
        else:
            self.db.set_state(inst["id"], ESTADO_FALHOU, error)
        self.db.finish_operation(op_id, OP_ERRO)

    # --- desativar / remover ---------------------------------------------

    def deactivate(self, instance_id: int, actor: str) -> dict:
        actor = _actor_of(actor)
        inst = self._instance(instance_id)
        if inst["state"] != ESTADO_ATIVA:
            raise Conflict("so uma instancia ativa pode ser desativada")
        self._require_from_broker(inst["ctid"])
        self.opnsense.close_ports(inst["ctid"])
        self.proxmox.stop(inst["ctid"])
        self.db.set_state(instance_id, ESTADO_DESATIVADA)
        self.db.audit(actor, "desativar", inst["name"], "ok")
        return {"id": instance_id, "state": ESTADO_DESATIVADA}

    def remove(self, instance_id: int, confirmation: object, actor: str,
                db_only: bool = False) -> dict:
        actor = _actor_of(actor)
        inst = self._instance(instance_id)
        if inst["state"] not in (ESTADO_DESATIVADA, ESTADO_FALHOU):
            raise Conflict("desative a instancia antes de remover")
        if confirmation != inst["name"]:
            raise ValidationError("confirma", "digite o nome exato da instancia para confirmar")
        self.opnsense.close_ports(inst["ctid"])
        if not db_only:
            self._destroy_ct(inst)
        self.db.delete_instance(instance_id)
        self.db.audit(actor, "esquecer" if db_only else "remover", inst["name"], "ok")
        return {"id": instance_id, "removed": True, "db_only": db_only}

    def _destroy_ct(self, inst: dict) -> None:
        ctid = inst["ctid"]
        if self.proxmox.belongs_to_broker(ctid):
            self.proxmox.destroy(ctid)
            return
        if inst["state"] == ESTADO_FALHOU:
            return  # a criacao nem chegou a existir no pool: nao ha CT nosso para destruir
        # "Nao esta no pool" pode ser CT apagado a mao OU CT movido/de outro dono, e o token
        # so enxerga o pool: os dois casos sao indistinguiveis (ambos dao 403). Liberar o
        # CTID/IP nesse caso poderia soltar um CT que ainda existe; entao so com pedido explicito.
        raise Conflict(
            f"o CT {ctid} nao pertence ao broker (nao esta no pool); nada foi alterado. Se ele nao "
            "existe mais no Proxmox, remova de novo com db_only para limpar so o registro")

    def _instance(self, instance_id: int) -> dict:
        inst = self.db.instance(instance_id)
        if inst is None:
            raise NotFound("instancia desconhecida")
        return inst

    def _require_from_broker(self, ctid: int) -> None:
        # O token do Proxmox enxerga o pool inteiro; a tag e a linha no banco sao o que
        # impede o broker de mexer num CT que nao e dele.
        if not self.proxmox.belongs_to_broker(ctid):
            raise Conflict(f"o CT {ctid} nao pertence ao broker; nada foi alterado")


def record_for_the_panel(inst: dict, game: Game, ports: list[AllocatedPort]) -> dict:
    """Os campos de `ServidorDoDeploy` do painel: com isso ele chama `ensure_server`."""
    return {
        "broker_id": inst["id"], "name": inst["name"], "host": inst["ip"],
        "service": f"{game.key}.service",
        "game_port": alocador.port_with_role(ports, alocador.ROLE_GAME),
        "query_port": alocador.port_with_role(ports, alocador.ROLE_QUERY),
        "ports": [str(p) for p in ports],
        "config_path": game.config_path, "config_files": list(game.config_files),
        "backup_paths": list(game.backup_paths), "player_source": game.player_source,
        "join_re": game.join_re, "leave_re": game.leave_re, "log_path": game.log_path,
        "notes": f"Criado pelo broker (CT {inst['ctid']})",
    }
