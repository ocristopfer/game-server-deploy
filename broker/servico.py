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

from . import alocador
from .alocador import PortaAlocada
from .backends import EspecificacaoDeCt, Instalador, Opnsense, Proxmox, Rede
from .banco import (ESTADO_ATIVA, ESTADO_DESATIVADA, ESTADO_FALHOU, OP_ERRO, OP_OK, Banco)
from .catalogo import NOME_RE, Catalogo, Jogo
from .erros import Conflito, CotaExcedida, ErroDeValidacao, NaoEncontrado

_ATOR_RE = re.compile(r"[A-Za-z0-9._-]{1,32}", re.ASCII)
ATOR_DESCONHECIDO = "desconhecido"
ERRO_MAX = 300


@dataclass(frozen=True)
class Config:
    ctids: range = range(300, 400)
    ips: tuple[str, ...] = ()
    max_instancias: int = 8
    max_criacoes_por_hora: int = 4


def _em_thread(tarefa: Callable[[], None]) -> None:
    threading.Thread(target=tarefa, daemon=True, name="broker-operacao").start()


def _agora_utc() -> datetime:
    return datetime.now(timezone.utc)


def _ator(bruto: str) -> str:
    # O painel diz quem clicou; o broker so confia o bastante para registrar, nunca para decidir.
    return bruto if _ATOR_RE.fullmatch(bruto or "") else ATOR_DESCONHECIDO


class Servico:
    def __init__(self, banco: Banco, catalogo: Catalogo, proxmox: Proxmox, opnsense: Opnsense,
                 instalador: Instalador, rede: Rede, config: Config,
                 executar: Callable[[Callable[[], None]], None] = _em_thread,
                 relogio: Callable[[], datetime] = _agora_utc):
        self.banco = banco
        self.catalogo = catalogo
        self.proxmox = proxmox
        self.opnsense = opnsense
        self.instalador = instalador
        self.rede = rede
        self.config = config
        self._executar = executar
        self._agora = relogio
        # Duas criacoes ao mesmo tempo escolheriam o mesmo IP antes de qualquer uma gravar.
        self._trava = threading.Lock()

    # --- consultas --------------------------------------------------------

    def saude(self) -> dict:
        return {"broker": True, "proxmox": self.proxmox.acessivel(),
                "opnsense": self.opnsense.acessivel(),
                "catalogo_erros": list(self.catalogo.erros)}

    def instancias(self) -> list[dict]:
        return self.banco.instancias()

    def operacao(self, op_id: str) -> dict:
        op = self.banco.operacao(op_id)
        if op is None:
            raise NaoEncontrado("operacao desconhecida")
        return op

    def adicionar_jogo(self, dados: object, ator: str) -> dict:
        jogo = self.catalogo.adicionar_dinamico(dados)
        self.banco.auditar(_ator(ator), "catalogo-adicionar", jogo.chave, "ok")
        return jogo.publico()

    # --- criar ------------------------------------------------------------

    def criar(self, chave_do_jogo: str, nome: str, ator: str) -> dict:
        ator = _ator(ator)
        nome = self._nome_valido(nome)
        jogo = self.catalogo.obter(chave_do_jogo)
        if not jogo.criavel:
            raise Conflito(f"{jogo.nome} nao pode ser criado pela API: {jogo.motivo}")
        with self._trava:
            self._checar_cotas()
            instancia_id, portas = self._reservar(jogo, nome, ator)
            op_id = self.banco.criar_operacao(instancia_id, "criar")
        self.banco.auditar(ator, "criar", f"{jogo.chave}:{nome}", "aceito", f"instancia {instancia_id}")
        self._executar(lambda: self._construir(op_id, instancia_id, jogo, portas, ator))
        return {"operacao_id": op_id, "instancia_id": instancia_id}

    @staticmethod
    def _nome_valido(nome: object) -> str:
        if not isinstance(nome, str) or not NOME_RE.fullmatch(nome):
            raise ErroDeValidacao("nome", "use letras, numeros, espaco, ponto, hifen ou sublinhado (ate 40)")
        return nome

    def _checar_cotas(self) -> None:
        if self.banco.operacao_em_andamento():
            raise CotaExcedida("ja ha uma operacao em andamento; aguarde ela terminar")
        if self.banco.contar_instancias() >= self.config.max_instancias:
            raise CotaExcedida(f"limite de {self.config.max_instancias} instancias atingido")
        desde = (self._agora() - timedelta(hours=1)).isoformat(timespec="seconds")
        if self.banco.criacoes_desde(desde) >= self.config.max_criacoes_por_hora:
            raise CotaExcedida(f"limite de {self.config.max_criacoes_por_hora} criacoes por hora atingido")

    def _reservar(self, jogo: Jogo, nome: str, ator: str) -> tuple[int, list[PortaAlocada]]:
        # Snapshot de fora (Proxmox, OPNsense) + o que o banco ja reservou: o CT pode ter
        # sido criado na mao, e a regra de NAT tambem.
        ctids_px, ips_px = self.proxmox.ctids_e_ips()
        ctids_db, ips_db, portas_db = self.banco.usados()
        ctid = alocador.escolher_ctid(self.config.ctids, ctids_px | ctids_db)
        ip = alocador.escolher_ip(self.config.ips, ips_px | ips_db, self.rede.responde)
        portas = alocador.alocar_portas(jogo, self.opnsense.portas_externas() | portas_db)
        instancia_id = self.banco.reservar(ctid, ip, jogo.chave, nome, f"{jogo.chave}-{ctid}", ator, portas)
        return instancia_id, portas

    def _construir(self, op_id: str, instancia_id: int, jogo: Jogo, portas: list[PortaAlocada],
                   ator: str) -> None:
        inst = self.banco.instancia(instancia_id)
        if inst is None:
            return
        log = self._logger(op_id)
        criado = False
        try:
            log(f"criando o container {inst['ctid']} ({inst['ip']})")
            self.proxmox.criar_ct(EspecificacaoDeCt(
                ctid=inst["ctid"], hostname=inst["hostname"], ip=inst["ip"], jogo=jogo.chave,
                memoria_mb=jogo.memoria_mb, cores=jogo.cores, disco_gb=jogo.disco_gb))
            criado = True
            self.proxmox.iniciar(inst["ctid"])
            self.instalador.instalar(inst["ip"], jogo, portas, log)
            # O firewall abre por ultimo: o jogo nao fica exposto enquanto ainda instala.
            log("abrindo as portas no firewall")
            self.opnsense.abrir(inst["ctid"], inst["ip"], portas)
        except Exception as erro:  # noqa: BLE001
            self._desfazer(op_id, inst, criado, str(erro))
            self.banco.auditar(ator, "criar", inst["nome"], "falhou", str(erro))
            return
        self.banco.mudar_estado(instancia_id, ESTADO_ATIVA)
        self.banco.terminar_operacao(op_id, OP_OK, registro_para_o_painel(inst, jogo, portas))
        self.banco.auditar(ator, "criar", inst["nome"], "ok", f"ctid {inst['ctid']}")

    def _logger(self, op_id: str) -> Callable[[str], None]:
        return lambda linha: self.banco.anexar_log(op_id, linha)

    def _desfazer(self, op_id: str, inst: dict, criado: bool, erro: str) -> None:
        """Volta ao estado anterior. Se nem o desfazer der certo, a reserva fica marcada
        como `falhou` (nao some): IP e portas continuam bloqueados ate alguem remover."""
        log = self._logger(op_id)
        log(f"ERRO: {erro[:ERRO_MAX]}")
        limpou = True
        try:
            self.opnsense.fechar(inst["ctid"])
            if criado:
                self.proxmox.destruir(inst["ctid"])
        except Exception as falha:  # noqa: BLE001
            limpou = False
            log(f"nao consegui desfazer tudo: {str(falha)[:ERRO_MAX]}")
        if limpou:
            self.banco.apagar_instancia(inst["id"])
            log("reserva liberada")
        else:
            self.banco.mudar_estado(inst["id"], ESTADO_FALHOU, erro)
        self.banco.terminar_operacao(op_id, OP_ERRO)

    # --- desativar / remover ---------------------------------------------

    def desativar(self, instancia_id: int, ator: str) -> dict:
        ator = _ator(ator)
        inst = self._instancia(instancia_id)
        if inst["estado"] != ESTADO_ATIVA:
            raise Conflito("so uma instancia ativa pode ser desativada")
        self._exigir_do_broker(inst["ctid"])
        self.opnsense.fechar(inst["ctid"])
        self.proxmox.parar(inst["ctid"])
        self.banco.mudar_estado(instancia_id, ESTADO_DESATIVADA)
        self.banco.auditar(ator, "desativar", inst["nome"], "ok")
        return {"id": instancia_id, "estado": ESTADO_DESATIVADA}

    def remover(self, instancia_id: int, confirma: object, ator: str,
                somente_banco: bool = False) -> dict:
        ator = _ator(ator)
        inst = self._instancia(instancia_id)
        if inst["estado"] not in (ESTADO_DESATIVADA, ESTADO_FALHOU):
            raise Conflito("desative a instancia antes de remover")
        if confirma != inst["nome"]:
            raise ErroDeValidacao("confirma", "digite o nome exato da instancia para confirmar")
        self.opnsense.fechar(inst["ctid"])
        if not somente_banco:
            self._destruir_ct(inst)
        self.banco.apagar_instancia(instancia_id)
        self.banco.auditar(ator, "esquecer" if somente_banco else "remover", inst["nome"], "ok")
        return {"id": instancia_id, "removida": True, "somente_banco": somente_banco}

    def _destruir_ct(self, inst: dict) -> None:
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

    def _instancia(self, instancia_id: int) -> dict:
        inst = self.banco.instancia(instancia_id)
        if inst is None:
            raise NaoEncontrado("instancia desconhecida")
        return inst

    def _exigir_do_broker(self, ctid: int) -> None:
        # O token do Proxmox enxerga o pool inteiro; a tag e a linha no banco sao o que
        # impede o broker de mexer num CT que nao e dele.
        if not self.proxmox.pertence_ao_broker(ctid):
            raise Conflito(f"o CT {ctid} nao pertence ao broker; nada foi alterado")


def registro_para_o_painel(inst: dict, jogo: Jogo, portas: list[PortaAlocada]) -> dict:
    """Os campos de `ServidorDoDeploy` do painel: com isso ele chama `ensure_server`."""
    return {
        "broker_id": inst["id"], "name": inst["nome"], "host": inst["ip"],
        "service": f"{jogo.chave}.service",
        "game_port": alocador.porta_do_papel(portas, alocador.PAPEL_JOGO),
        "query_port": alocador.porta_do_papel(portas, alocador.PAPEL_QUERY),
        "ports": [str(p) for p in portas],
        "config_path": jogo.config_path, "config_files": list(jogo.config_files),
        "backup_paths": list(jogo.backup_paths), "player_source": jogo.player_source,
        "join_re": jogo.join_re, "leave_re": jogo.leave_re, "log_path": jogo.log_path,
        "notes": f"Criado pelo broker (CT {inst['ctid']})",
    }
