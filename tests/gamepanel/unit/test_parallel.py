"""Parallel reading per server (gamepanel.services.parallel).

It was the same thirty lines written three times (status, resources, players) before
Phase 4 - and none of the three had its own test. What matters here is what only shows
up with a slow or downed server: whoever does not come back in time must not disappear
from the screen, and the fallback value must not be the SAME object under several keys.
"""
from __future__ import annotations

import time

from gamepanel.services import parallel

SPARE = {"error": "tempo esgotado"}


def servers(*ids: int) -> list[dict]:
    return [{"id": i} for i in ids]


def test_junta_a_resposta_de_cada_um_pelo_id():
    out = parallel.per_server(lambda s: {"n": int(s["id"]) * 2}, servers(1, 2, 3), 5, SPARE)
    assert out == {1: {"n": 2}, 2: {"n": 4}, 3: {"n": 6}}


def test_lista_vazia_devolve_vazio():
    assert parallel.per_server(lambda s: {}, [], 5, SPARE) == {}


def test_quem_nao_volta_a_tempo_entra_com_a_reserva():
    def slow(s):
        if int(s["id"]) == 2:
            time.sleep(0.5)
        return {"ok": True}

    out = parallel.per_server(slow, servers(1, 2), 0.05, SPARE)
    assert out[1] == {"ok": True}
    assert out[2] == {"error": "tempo esgotado"}


def test_a_reserva_e_uma_copia_por_servidor():
    """Writing into one server's result must not show up in another's."""
    out = parallel.per_server(lambda s: time.sleep(0.5), servers(1, 2), 0.05, SPARE)
    out[1]["error"] = "mexido"
    assert out[2]["error"] == "tempo esgotado"
    # Nor in the original fallback dictionary.
    assert SPARE["error"] == "tempo esgotado"


def test_roda_de_verdade_em_paralelo():
    """In series, three 0.2s waits would not fit in a 0.5s deadline."""
    def wait_for(s):
        time.sleep(0.2)
        return {"ok": True}

    beginning = time.monotonic()
    out = parallel.per_server(wait_for, servers(1, 2, 3), 2, SPARE)
    assert all(v == {"ok": True} for v in out.values())
    assert time.monotonic() - beginning < 0.5
