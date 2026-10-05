"""The history policy: the label, and who may read the output of each action."""
from __future__ import annotations

import pytest

from gamepanel import app as panel
from gamepanel import i18n
from gamepanel.services import job_service


def test_o_rotulo_de_toda_acao_e_uma_CHAVE_de_catalogo():
    """Ready-made text here shows up in Portuguese on the English screen too - and it already
    did: "Jogo adicionado ao catalogo" was a literal until it got the `job.game_added` key."""
    fora = sorted(k for k, v in job_service.EXTRA_LABELS.items()
                  if v not in i18n.CATALOGS["pt"])
    assert fora == [], f"rotulo que nao e chave de catalogo: {fora}"


def test_os_dois_idiomas_tem_todos_os_rotulos():
    faltando = sorted(v for v in job_service.EXTRA_LABELS.values()
                      if v not in i18n.CATALOGS["en"])
    assert faltando == []


def test_o_admin_nao_paga_por_filtro_nenhum():
    """No clause, rather than one that accepts everything: the admin query does not carry a
    twelve-value `NOT IN` for nothing."""
    assert job_service.hidden_filter(is_admin=True) == ("", ())


def test_o_operador_recebe_a_lista_inteira_das_restritas():
    where, values = job_service.hidden_filter(is_admin=False)
    assert where.startswith(" AND action NOT IN (")
    assert set(values) == job_service.ADMIN_ONLY_ACTIONS
    # One placeholder per value: unless they match, sqlite rejects the query.
    assert where.count("?") == len(values)


@pytest.mark.parametrize("action", ["shell", "terminal", "download-file", "broker-criar"])
def test_saida_que_carrega_segredo_e_so_de_admin(action):
    """Console and terminal carry the typed command; the broker carries IP, CTID and ports."""
    assert job_service.is_restricted(action)


@pytest.mark.parametrize("action", ["backup", "edit-config", "player-action", "restart"])
def test_o_que_o_operador_dispara_ele_tambem_le(action):
    """Blocking the reading of what they can trigger themselves would only hide the result
    of their own click."""
    assert not job_service.is_restricted(action)


def test_a_lista_do_app_e_a_do_service():
    """Two copies diverge silently: `app.py` only aliases it."""
    assert panel.JOB_ACTIONS_ADMIN is job_service.ADMIN_ONLY_ACTIONS


def test_toda_acao_de_botao_tem_rotulo(database):
    """An action with a button and no label shows up in the history as the raw key."""
    without_label = sorted(k for k in panel.COMMANDS if k not in panel.JOB_LABELS)
    assert without_label == []
