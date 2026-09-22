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
from gamebroker.domain.exceptions import Conflito, CotaExcedida, ErroDeValidacao, NaoEncontrado
from gamebroker.persistence.db import ESTADO_ATIVA, ESTADO_DESATIVADA, ESTADO_FALHOU, OP_ERRO, OP_OK, Banco
from gamebroker.runtime.base import EspecificacaoDeCt, Instalador, Opnsense, Proxmox, Rede
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
    def __init__(self, db: Banco, catalog: Catalog, proxmox: Proxmox, opnsense: Opnsense,
                 installer: Instalador, network: Rede, config: Config,
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
        return {"broker": True, "proxmox": self.proxmox.acessivel(),
                "opnsense": self.opnsense.acessivel(),
                "catalogo_erros": list(self.catalog.errors)}

    def instances(self) -> list[dict]:
        return self.db.instances()

    def operation(self, op_id: str) -> dict:
        op = self.db.operation(op_id)
        if op is None:
            raise NaoEncontrado("operacao desconhecida")
        return op

    def add_game(self, dados: object, actor: str) -> dict:
        jogo = self.catalog.add_dynamic(dados)
        self.db.auditar(_actor_of(actor), "catalogo-adicionar", jogo.key, "ok")
        return jogo.as_public()

    # --- criar ------------------------------------------------------------

    def create(self, game_key: str, name: str, actor: str) -> dict:
        actor = _actor_of(actor)
        name = self._valid_name(name)
        jogo = self.catalog.get(game_key)
        if not jogo.creatable:
            raise Conflito(f"{jogo.name} nao pode ser criado pela API: {jogo.reason}")
        with self._trava:
            self._check_quotas()
            instance_id, ports = self._reserve(jogo, name, actor)
            op_id = self.db.criar_operacao(instance_id, "criar")
        self.db.auditar(actor, "criar", f"{jogo.key}:{name}", "aceito", f"instancia {instance_id}")
        self._executar(lambda: self._build(op_id, instance_id, jogo, ports, actor))
        return {"operacao_id": op_id, "instancia_id": instance_id}

    @staticmethod
    def _valid_name(name: object) -> str:
        if not isinstance(name, str) or not NAME_RE.fullmatch(name):
            raise ErroDeValidacao("nome", "use letras, numeros, espaco, ponto, hifen ou sublinhado (ate 40)")
        return name

    def _check_quotas(self) -> None:
        if self.db.operacao_em_andamento():
            raise CotaExcedida("ja ha uma operacao em andamento; aguarde ela terminar")
        if self.db.contar_instancias() >= self.config.max_instances:
            raise CotaExcedida(f"limite de {self.config.max_instances} instancias atingido")
        desde = (self._agora() - timedelta(hours=1)).isoformat(timespec="seconds")
        if self.db.criacoes_desde(desde) >= self.config.max_creations_per_hour:
            raise CotaExcedida(f"limite de {self.config.max_creations_per_hour} criacoes por hora atingido")

    def _reserve(self, jogo: Game, name: str, actor: str) -> tuple[int, list[AllocatedPort]]:
        # Snapshot de fora (Proxmox, OPNsense) + o que o banco ja reservou: o CT pode ter
        # sido criado na mao, e a regra de NAT tambem.
        ctids_px, ips_px = self.proxmox.ctids_e_ips()
        ctids_db, ips_db, portas_db = self.db.usados()
        if self.config.ctid_base:
            ip, ctid = alocador.pick_ip_and_ctid(self.config.ips, self.config.ctid_base,
                                                   ctids_px | ctids_db, ips_px | ips_db, self.network.responde)
        else:
            ctid = alocador.pick_ctid(self.config.ctids, ctids_px | ctids_db)
            ip = alocador.pick_ip(self.config.ips, ips_px | ips_db, self.network.responde)
        ports = alocador.allocate_ports(jogo, self.opnsense.portas_externas() | portas_db, self.config.ports)
        instance_id = self.db.reservar(ctid, ip, jogo.key, name, f"{jogo.key}-{ctid}", actor, ports)
        return instance_id, ports

    def _build(self, op_id: str, instance_id: int, jogo: Game, ports: list[AllocatedPort],
                   actor: str) -> None:
        inst = self.db.instancia(instance_id)
        if inst is None:
            return
        log = self._logger(op_id)
        created = False
        try:
            log(f"criando o container {inst['ctid']} ({inst['ip']})")
            self.proxmox.criar_ct(EspecificacaoDeCt(
                ctid=inst["ctid"], hostname=inst["hostname"], ip=inst["ip"], jogo=jogo.key,
                memory_mb=jogo.memory_mb, cores=jogo.cores, disk_gb=jogo.disk_gb))
            created = True
            self.proxmox.iniciar(inst["ctid"])
            self.installer.instalar(inst["ip"], jogo, ports, log)
            # O firewall abre por ultimo: o jogo nao fica exposto enquanto ainda instala.
            log("abrindo as portas no firewall")
            self.opnsense.abrir(inst["ctid"], inst["ip"], ports)
        except Exception as erro:  # noqa: BLE001
            self._undo(op_id, inst, created, str(erro))
            self.db.auditar(actor, "criar", inst["nome"], "falhou", str(erro))
            return
        self.db.mudar_estado(instance_id, ESTADO_ATIVA)
        self.db.terminar_operacao(op_id, OP_OK, record_for_the_panel(inst, jogo, ports))
        self.db.auditar(actor, "criar", inst["nome"], "ok", f"ctid {inst['ctid']}")

    def _logger(self, op_id: str) -> Callable[[str], None]:
        return lambda linha: self.db.anexar_log(op_id, linha)

    def _undo(self, op_id: str, inst: dict, created: bool, erro: str) -> None:
        """Volta ao estado anterior. Se nem o desfazer der certo, a reserva fica marcada
        como `falhou` (nao some): IP e portas continuam bloqueados ate alguem remover."""
        log = self._logger(op_id)
        log(f"ERRO: {erro[:ERROR_MAX]}")
        limpou = True
        try:
            self.opnsense.fechar(inst["ctid"])
            if created:
                self.proxmox.destruir(inst["ctid"])
        except Exception as falha:  # noqa: BLE001
            limpou = False
            log(f"nao consegui desfazer tudo: {str(falha)[:ERROR_MAX]}")
        if limpou:
            self.db.apagar_instancia(inst["id"])
            log("reserva liberada")
        else:
            self.db.mudar_estado(inst["id"], ESTADO_FALHOU, erro)
        self.db.terminar_operacao(op_id, OP_ERRO)

    # --- desativar / remover ---------------------------------------------

    def deactivate(self, instance_id: int, actor: str) -> dict:
        actor = _actor_of(actor)
        inst = self._instance(instance_id)
        if inst["estado"] != ESTADO_ATIVA:
            raise Conflito("so uma instancia ativa pode ser desativada")
        self._require_from_broker(inst["ctid"])
        self.opnsense.fechar(inst["ctid"])
        self.proxmox.parar(inst["ctid"])
        self.db.mudar_estado(instance_id, ESTADO_DESATIVADA)
        self.db.auditar(actor, "desativar", inst["nome"], "ok")
        return {"id": instance_id, "estado": ESTADO_DESATIVADA}

    def remove(self, instance_id: int, confirmation: object, actor: str,
                db_only: bool = False) -> dict:
        actor = _actor_of(actor)
        inst = self._instance(instance_id)
        if inst["estado"] not in (ESTADO_DESATIVADA, ESTADO_FALHOU):
            raise Conflito("desative a instancia antes de remover")
        if confirmation != inst["nome"]:
            raise ErroDeValidacao("confirma", "digite o nome exato da instancia para confirmar")
        self.opnsense.fechar(inst["ctid"])
        if not db_only:
            self._destroy_ct(inst)
        self.db.apagar_instancia(instance_id)
        self.db.auditar(actor, "esquecer" if db_only else "remover", inst["nome"], "ok")
        return {"id": instance_id, "removida": True, "somente_banco": db_only}

    def _destroy_ct(self, inst: dict) -> None:
        ctid = inst["ctid"]
        if self.proxmox.pertence_ao_broker(ctid):
            self.proxmox.destruir(ctid)
            return
        if inst["estado"] == ESTADO_FALHOU:
            return  # a criacao nem chegou a existir no pool: nao ha CT nosso para destruir
        # "Nao esta no pool" pode ser CT apagado a mao OU CT movido/de outro dono, e o token
        # so enxerga o pool: os dois casos sao indistinguiveis (ambos dao 403). Liberar o
        # CTID/IP nesse caso poderia soltar um CT que ainda existe; entao so com pedido explicito.
        raise Conflito(
            f"o CT {ctid} nao pertence ao broker (nao esta no pool); nada foi alterado. Se ele nao "
            "existe mais no Proxmox, remova de novo com somente_banco para limpar so o registro")

    def _instance(self, instance_id: int) -> dict:
        inst = self.db.instancia(instance_id)
        if inst is None:
            raise NaoEncontrado("instancia desconhecida")
        return inst

    def _require_from_broker(self, ctid: int) -> None:
        # O token do Proxmox enxerga o pool inteiro; a tag e a linha no banco sao o que
        # impede o broker de mexer num CT que nao e dele.
        if not self.proxmox.pertence_ao_broker(ctid):
            raise Conflito(f"o CT {ctid} nao pertence ao broker; nada foi alterado")


def record_for_the_panel(inst: dict, jogo: Game, ports: list[AllocatedPort]) -> dict:
    """Os campos de `ServidorDoDeploy` do painel: com isso ele chama `ensure_server`."""
    return {
        "broker_id": inst["id"], "name": inst["nome"], "host": inst["ip"],
        "service": f"{jogo.key}.service",
        "game_port": alocador.port_with_role(ports, alocador.ROLE_GAME),
        "query_port": alocador.port_with_role(ports, alocador.ROLE_QUERY),
        "ports": [str(p) for p in ports],
        "config_path": jogo.config_path, "config_files": list(jogo.config_files),
        "backup_paths": list(jogo.backup_paths), "player_source": jogo.player_source,
        "join_re": jogo.join_re, "leave_re": jogo.leave_re, "log_path": jogo.log_path,
        "notes": f"Criado pelo broker (CT {inst['ctid']})",
    }
