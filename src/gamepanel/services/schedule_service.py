"""Quando uma tarefa agendada vence, e como ela se chama na tela.

So a conta do relogio: nada de banco, nada de SSH, nada de Flask. Quem acorda de tempos
em tempos e `tasks.scheduler`; quem dispara e grava o `last_run` esta em `app.py` junto
do `start_job`.

A regra que explica quase tudo aqui e a da ocorrencia: uma tarefa diaria/semanal nao
"vence a cada X"; ela tem um HORARIO, e o que se pergunta e se a ocorrencia mais recente
desse horario ja rodou. E o que faz o painel nao disparar duas vezes ao reiniciar, e nao
disparar nada quando ficou horas fora do ar (ver `SCHEDULE_GRACE` em `venceu`).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from gamepanel.i18n import Message

SCHEDULE_KINDS = ("diario", "semanal", "intervalo")
SCHEDULE_ACTIONS = ("restart", "stop", "start", "update", "backup")
# Chaves, nao texto: o `<select>` da tela mostra o nome do dia no idioma de quem olha.
WEEKDAYS = ("weekday.monday", "weekday.tuesday", "weekday.wednesday", "weekday.thursday",
            "weekday.friday", "weekday.saturday", "weekday.sunday")
# A mesma coisa com o artigo colado: "toda segunda" mas "todo sabado" (os dias vem de
# "segunda-feira", feminino; sabado e domingo sao masculinos). O ingles nao tem artigo
# nenhum aqui, entao a diferenca mora no catalogo e nao no codigo.
WEEKDAY_WITH_ARTICLE = ("weekday.on_monday", "weekday.on_tuesday", "weekday.on_wednesday",
                        "weekday.on_thursday", "weekday.on_friday", "weekday.on_saturday",
                        "weekday.on_sunday")
EVERY_HOURS_MAX = 168  # uma semana
DAYS_IN_WEEK = 7


def local_now() -> datetime:
    """Hora local do painel, com fuso. E o relogio que o agendamento enxerga."""
    return datetime.now().astimezone().replace(microsecond=0)


def _parse_dt(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def schedule_label(sched: Any) -> Message:
    """Como a tarefa e descrita na tela e no historico.

    Devolve `Message`, e nao texto pronto, porque este rotulo cai em DOIS lugares com
    regras diferentes: a tela, que segue o idioma de quem olha, e a coluna `command` do
    job, que e gravada e segue o idioma do deploy. Sendo `Message` (que e `str`), o
    segundo caso continua funcionando sem ninguem mudar nada.
    """
    time = f"{int(sched['hour']):02d}:{int(sched['minute']):02d}"
    if sched["kind"] == "intervalo":
        hours = int(sched["every_hours"])
        if hours == 1:
            return Message("schedule.every_hour")
        return Message("schedule.every_n_hours", n=hours)
    if sched["kind"] == "semanal":
        index = int(sched["weekday"]) % DAYS_IN_WEEK
        # O dia ja vem com o artigo ("toda segunda", "todo sabado"): em portugues ele
        # muda com o genero da palavra, e em ingles nem existe. Tentar montar
        # "{artigo} {dia}" na frase obrigaria o ingles a carregar um campo vazio.
        return Message("schedule.weekly", weekday=Message(WEEKDAY_WITH_ARTICLE[index]),
                       time=time)
    return Message("schedule.daily", time=time)


def previous_occurrence(sched: Any, now: datetime) -> datetime | None:
    """Ultimo horario em que esta tarefa deveria ter rodado ('intervalo' nao tem)."""
    if sched["kind"] == "intervalo":
        return None
    target = now.replace(hour=int(sched["hour"]), minute=int(sched["minute"]),
                         second=0, microsecond=0)
    if sched["kind"] == "semanal":
        back = (now.weekday() - int(sched["weekday"])) % DAYS_IN_WEEK
        target -= timedelta(days=back)
        if target > now:
            target -= timedelta(days=DAYS_IN_WEEK)
        return target
    if target > now:
        target -= timedelta(days=1)
    return target


def is_due(sched: Any, now: datetime, tolerance_s: float) -> bool:
    """A tarefa deveria disparar agora?"""
    last_one = _parse_dt(sched["last_run"])
    if sched["kind"] == "intervalo":
        if last_one is None:
            return True
        return (now - last_one) >= timedelta(hours=max(1, int(sched["every_hours"])))

    target = previous_occurrence(sched, now)
    if target is None:
        return False  # so 'intervalo' nao tem ocorrencia, e ele ja saiu acima
    if last_one is not None and last_one >= target:
        return False  # esta ocorrencia ja rodou
    # Atrasada demais: o painel estava fora do ar quando a hora passou. Nao dispara e nao
    # anota nada — na proxima ocorrencia a conta acima volta a fechar sozinha.
    return (now - target).total_seconds() <= tolerance_s
