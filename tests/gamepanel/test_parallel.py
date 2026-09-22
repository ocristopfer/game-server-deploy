"""Leitura em paralelo por servidor (gamepanel.services.parallel).

Era a mesma trinta linhas escrita tres vezes (status, recursos, jogadores) antes da
Fase 4 — e nenhuma das tres tinha teste proprio. O que importa aqui e o que so aparece
com servidor lento ou fora do ar: quem nao volta a tempo nao pode sumir da tela, e o
valor de reserva nao pode ser o MESMO objeto em varias chaves.
"""
from __future__ import annotations

import time

from gamepanel.services import parallel

RESERVA = {"error": "tempo esgotado"}


def servidores(*ids: int) -> list[dict]:
    return [{"id": i} for i in ids]


def test_junta_a_resposta_de_cada_um_pelo_id():
    out = parallel.per_server(lambda s: {"n": int(s["id"]) * 2}, servidores(1, 2, 3), 5, RESERVA)
    assert out == {1: {"n": 2}, 2: {"n": 4}, 3: {"n": 6}}


def test_lista_vazia_devolve_vazio():
    assert parallel.per_server(lambda s: {}, [], 5, RESERVA) == {}


def test_quem_nao_volta_a_tempo_entra_com_a_reserva():
    def devagar(s):
        if int(s["id"]) == 2:
            time.sleep(0.5)
        return {"ok": True}

    out = parallel.per_server(devagar, servidores(1, 2), 0.05, RESERVA)
    assert out[1] == {"ok": True}
    assert out[2] == {"error": "tempo esgotado"}


def test_a_reserva_e_uma_copia_por_servidor():
    """Escrever no resultado de um servidor nao pode aparecer no do outro."""
    out = parallel.per_server(lambda s: time.sleep(0.5), servidores(1, 2), 0.05, RESERVA)
    out[1]["error"] = "mexido"
    assert out[2]["error"] == "tempo esgotado"
    # E nem no dicionario original de reserva.
    assert RESERVA["error"] == "tempo esgotado"


def test_roda_de_verdade_em_paralelo():
    """Em serie, tres esperas de 0.2s nao caberiam num prazo de 0.5s."""
    def espera(s):
        time.sleep(0.2)
        return {"ok": True}

    comeco = time.monotonic()
    out = parallel.per_server(espera, servidores(1, 2, 3), 2, RESERVA)
    assert all(v == {"ok": True} for v in out.values())
    assert time.monotonic() - comeco < 0.5
