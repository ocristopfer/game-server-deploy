"""Push notifications: the routes of `blueprints/push.py` and the delivery in `app.notify`.

The push service is swapped for a capturer (`panel.send_push`), like `webhooks` does for HTTP;
the subscription keys are real (RFC 8291's example device), so the validation is the real one.
"""
from __future__ import annotations

import json

import pytest

from gamepanel import app as panel
from gamepanel.i18n import Message
from gamepanel.integrations import push_client
from gamepanel.persistence.repositories import push as push_repo

UA_PUBLIC = "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"
AUTH = "BTBZMqHH6r4Tts7J_aSIgg"
FCM = "https://fcm.googleapis.com/fcm/send/abc123"


@pytest.fixture
def pushes(database, monkeypatch):
    """What would go to the push services: list of (endpoint, decoded payload)."""
    sent: list[tuple[str, dict]] = []

    def capture(device, payload, vapid):
        sent.append((device["endpoint"], json.loads(payload)))
        return push_client.Result("", gone=False)

    monkeypatch.setattr(panel, "send_push", capture)
    return sent


def _csrf(cli) -> str:
    cli.get("/account")
    with cli.session_transaction() as sess:
        return sess.get("csrf", "")


def _uid(cli) -> int:
    with cli.session_transaction() as sess:
        return sess["uid"]


def _subscribe(cli, endpoint=FCM, p256dh=UA_PUBLIC, auth=AUTH):
    return cli.post("/account/push", json={"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth},
                                           "label": "Android · Chrome"},
                    headers={"X-CSRF-Token": _csrf(cli)})


def test_inscrever_grava_o_aparelho_com_os_eventos_padrao(admin, database):
    resp = _subscribe(admin)
    assert resp.status_code == 200
    assert resp.get_json()["redirect"].endswith("/account")
    [row] = push_repo.for_user(database, _uid(admin))
    assert row["endpoint"] == FCM
    assert row["label"] == "Android · Chrome"
    assert panel.clean_events(row["events"]) == panel.clean_events(panel.ALERT_DEFAULT)


def test_inscrever_de_novo_atualiza_em_vez_de_duplicar(admin, database):
    _subscribe(admin)
    _subscribe(admin)
    assert len(push_repo.for_user(database, _uid(admin))) == 1


def test_inscricao_sem_csrf_e_recusada(admin, database):
    resp = admin.post("/account/push", json={"endpoint": FCM, "keys": {"p256dh": UA_PUBLIC, "auth": AUTH}})
    assert resp.status_code in (400, 403)
    assert push_repo.all_devices(database) == []


@pytest.mark.parametrize(("endpoint", "p256dh", "auth"), [
    # Not a push service: without the allowlist the panel would POST to any internal address.
    ("https://192.168.1.10/interno", UA_PUBLIC, AUTH),
    ("http://fcm.googleapis.com/fcm/send/x", UA_PUBLIC, AUTH),
    ("https://fcm.googleapis.com.mal.com/x", UA_PUBLIC, AUTH),
    (FCM, "AAAA", AUTH),
    (FCM, UA_PUBLIC, "curto"),
])
def test_inscricao_invalida_e_recusada(admin, database, endpoint, p256dh, auth):
    assert _subscribe(admin, endpoint, p256dh, auth).status_code == 400
    assert push_repo.all_devices(database) == []


def test_operador_tambem_pode_receber(operator, database):
    assert _subscribe(operator).status_code == 200


def test_limite_de_aparelhos_por_pessoa(admin, database, monkeypatch):
    monkeypatch.setattr(panel, "PUSH_MAX_PER_USER", 1)
    assert _subscribe(admin).status_code == 200
    assert _subscribe(admin, endpoint=FCM + "-2").status_code == 409


def test_alerta_chega_ao_aparelho_que_pediu_o_evento(admin, database, pushes, webhooks):
    _subscribe(admin)
    assert panel.notify(database, "caiu", Message("alert.server_stopped", name="Valheim"), "detalhe")
    [(endpoint, payload)] = pushes
    assert endpoint == FCM
    assert "Valheim" in payload["title"]
    assert payload["body"] == "detalhe"
    assert payload["tag"] == "caiu"
    [line] = panel.recent_alerts(database)
    assert line["status"] == "enviado"
    assert line["target"].startswith("push: chefe")


def test_evento_que_o_aparelho_nao_pediu_nao_sai(admin, database, pushes, webhooks):
    _subscribe(admin)
    assert not panel.notify(database, "jogador-entrou", "alguem entrou")
    assert pushes == []


def test_so_o_aparelho_basta_para_o_monitor_olhar(admin, database):
    # Without this the monitor would see "nobody listening" and skip the round.
    assert panel.webhook_config(database)["events"] == set()
    _subscribe(admin)
    assert "caiu" in panel.webhook_config(database)["events"]


def test_alerta_sai_no_idioma_do_dono_do_aparelho(admin, database, pushes, webhooks):
    _subscribe(admin)
    admin.post("/account/language", data={"lang": "en", "csrf": _csrf(admin)})
    panel.notify(database, "caiu", Message("alert.server_stopped", name="Valheim"))
    title = pushes[0][1]["title"]
    assert title == panel.i18n.translate(Message("alert.server_stopped", name="Valheim"), "en")


def test_inscricao_morta_e_apagada(admin, database, monkeypatch, webhooks):
    _subscribe(admin)
    monkeypatch.setattr(panel, "send_push",
                        lambda *a: push_client.Result(Message("push.http_status", status=410), gone=True))
    assert not panel.notify(database, "caiu", "caiu")
    assert push_repo.all_devices(database) == []
    assert panel.recent_alerts(database)[0]["status"] == "falhou"


def test_salvar_eventos_e_nome(admin, database, post):
    _subscribe(admin)
    [row] = push_repo.for_user(database, _uid(admin))
    resp = post(admin, f"/account/push/{row['id']}", {"label": "Celular", "events": ["cpu-alta", "nao-existe"]})
    assert resp.status_code == 302
    [row] = push_repo.for_user(database, _uid(admin))
    assert (row["label"], row["events"]) == ("Celular", "cpu-alta")


def test_nao_mexe_no_aparelho_de_outra_pessoa(admin, operator, database, post):
    _subscribe(operator)
    [row] = push_repo.all_devices(database)
    post(admin, f"/account/push/{row['id']}/delete")
    post(admin, f"/account/push/{row['id']}", {"label": "meu", "events": []})
    [still] = push_repo.all_devices(database)
    assert (still["label"], still["events"]) == (row["label"], row["events"])


def test_teste_envia_para_o_aparelho(admin, database, pushes, post):
    _subscribe(admin)
    [row] = push_repo.for_user(database, _uid(admin))
    assert post(admin, f"/account/push/{row['id']}/test").status_code == 302
    assert len(pushes) == 1


def test_remover_e_desinscrever(admin, database, post):
    _subscribe(admin)
    resp = admin.post("/account/push/unsubscribe", json={"endpoint": FCM},
                      headers={"X-CSRF-Token": _csrf(admin)})
    assert resp.status_code == 200
    assert push_repo.all_devices(database) == []
    _subscribe(admin)
    [row] = push_repo.all_devices(database)
    post(admin, f"/account/push/{row['id']}/delete")
    assert push_repo.all_devices(database) == []


def test_tela_da_conta_mostra_a_chave_e_os_aparelhos(admin, database):
    _subscribe(admin)
    html = admin.get("/account").get_data(as_text=True)
    key = panel.webauthn.b64url(panel.push_keys(database).public)
    assert f'data-push="{key}"' in html
    assert "Android · Chrome" in html


def test_chave_vapid_e_estavel(database):
    assert panel.push_keys(database) == panel.push_keys(database)
