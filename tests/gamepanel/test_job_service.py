"""A politica do historico: rotulo e quem pode ler a saida de cada acao."""
from __future__ import annotations

import pytest

from gamepanel import app as panel
from gamepanel import i18n
from gamepanel.services import job_service


def test_o_rotulo_de_toda_acao_e_uma_CHAVE_de_catalogo():
    """Texto pronto aqui aparece em portugues tambem na tela em ingles — e ja apareceu:
    "Jogo adicionado ao catalogo" era literal ate ganhar a chave `job.game_added`."""
    fora = sorted(k for k, v in job_service.EXTRA_LABELS.items()
                  if v not in i18n.CATALOGS["pt"])
    assert fora == [], f"rotulo que nao e chave de catalogo: {fora}"


def test_os_dois_idiomas_tem_todos_os_rotulos():
    faltando = sorted(v for v in job_service.EXTRA_LABELS.values()
                      if v not in i18n.CATALOGS["en"])
    assert faltando == []


def test_o_admin_nao_paga_por_filtro_nenhum():
    """Sem clausula, e nao uma que aceita tudo: a consulta do admin nao carrega um
    `NOT IN` com doze valores a toa."""
    assert job_service.hidden_filter(is_admin=True) == ("", ())


def test_o_operador_recebe_a_lista_inteira_das_restritas():
    where, values = job_service.hidden_filter(is_admin=False)
    assert where.startswith(" AND action NOT IN (")
    assert set(values) == job_service.ADMIN_ONLY_ACTIONS
    # Um marcador por valor: a menos que batam, o sqlite recusa a consulta.
    assert where.count("?") == len(values)


@pytest.mark.parametrize("action", ["shell", "terminal", "download-file", "broker-criar"])
def test_saida_que_carrega_segredo_e_so_de_admin(action):
    """Console e terminal levam o comando digitado; o broker leva IP, CTID e portas."""
    assert job_service.is_restricted(action)


@pytest.mark.parametrize("action", ["backup", "edit-config", "player-action", "restart"])
def test_o_que_o_operador_dispara_ele_tambem_le(action):
    """Barrar a leitura do que ele mesmo pode disparar so esconderia o resultado do
    proprio clique."""
    assert not job_service.is_restricted(action)


def test_a_lista_do_app_e_a_do_service():
    """Duas copias divergem em silencio: o `app.py` so apelida."""
    assert panel.JOB_ACTIONS_ADMIN is job_service.ADMIN_ONLY_ACTIONS


def test_toda_acao_de_botao_tem_rotulo(database):
    """Acao com botao e sem rotulo aparece no historico como a chave crua."""
    sem_rotulo = sorted(k for k in panel.COMMANDS if k not in panel.JOB_LABELS)
    assert sem_rotulo == []
