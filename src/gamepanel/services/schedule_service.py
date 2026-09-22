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

SCHEDULE_KINDS = ("diario", "semanal", "intervalo")
SCHEDULE_ACTIONS = ("restart", "stop", "start", "update", "backup")
WEEKDAYS = ("segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo")
# "toda segunda" mas "todo sabado": os dias de semana vem de "segunda-feira" (feminino),
# sabado e domingo sao masculinos.
DAY_ARTICLE = ("toda", "toda", "toda", "toda", "toda", "todo", "todo")
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


def schedule_label(sched: Any) -> str:
    """Como a tarefa e descrita na tela e no historico."""
    hora = f"{int(sched['hour']):02d}:{int(sched['minute']):02d}"
    if sched["kind"] == "intervalo":
        horas = int(sched["every_hours"])
        return f"a cada {horas}h" if horas != 1 else "a cada hora"
    if sched["kind"] == "semanal":
        indice = int(sched["weekday"]) % DAYS_IN_WEEK
        return f"{DAY_ARTICLE[indice]} {WEEKDAYS[indice]} as {hora}"
    return f"todo dia as {hora}"


def previous_occurrence(sched: Any, now: datetime) -> datetime | None:
    """Ultimo horario em que esta tarefa deveria ter rodado ('intervalo' nao tem)."""
    if sched["kind"] == "intervalo":
        return None
    alvo = now.replace(hour=int(sched["hour"]), minute=int(sched["minute"]),
                         second=0, microsecond=0)
    if sched["kind"] == "semanal":
        atras = (now.weekday() - int(sched["weekday"])) % DAYS_IN_WEEK
        alvo -= timedelta(days=atras)
        if alvo > now:
            alvo -= timedelta(days=DAYS_IN_WEEK)
        return alvo
    if alvo > now:
        alvo -= timedelta(days=1)
    return alvo


def is_due(sched: Any, now: datetime, tolerance_s: float) -> bool:
    """A tarefa deveria disparar agora?"""
    ultimo = _parse_dt(sched["last_run"])
    if sched["kind"] == "intervalo":
        if ultimo is None:
            return True
        return (now - ultimo) >= timedelta(hours=max(1, int(sched["every_hours"])))

    alvo = previous_occurrence(sched, now)
    if alvo is None:
        return False  # so 'intervalo' nao tem ocorrencia, e ele ja saiu acima
    if ultimo is not None and ultimo >= alvo:
        return False  # esta ocorrencia ja rodou
    # Atrasada demais: o painel estava fora do ar quando a hora passou. Nao dispara e nao
    # anota nada — na proxima ocorrencia a conta acima volta a fechar sozinha.
    return (now - alvo).total_seconds() <= tolerance_s
