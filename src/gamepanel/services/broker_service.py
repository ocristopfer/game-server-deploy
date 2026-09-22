"""Formulario de "jogo novo" do catalogo do broker.

So converte tipos e recolhe as listas — quem VALIDA de verdade e o broker, que recusa
campo desconhecido, caminho fora de /opt/game e comando escondido. Conferir aqui de
novo seria manter duas listas do que vale, e uma delas ficaria para tras.
"""
from __future__ import annotations

import re
from typing import Any

# Espelho do gamebroker.catalogo.RECEITAS: so para desenhar as caixas do formulario.
BROKER_RECEITAS = ("wine", "proton", "steamclient-sdk64")
NUMERO_RE = re.compile(r"[0-9]{1,10}", re.ASCII)

# Campos que entram como texto, se vierem preenchidos.
CAMPOS_DE_TEXTO = ("chave", "nome", "plataforma", "start_script", "start_args",
                   "config_path", "log_path", "join_re", "leave_re", "player_source")
# Campos numericos, com o rotulo que aparece no erro.
CAMPOS_NUMERICOS = (
    ("app_id", "App ID"), ("porta_jogo", "Porta do jogo"),
    ("porta_query", "Porta de consulta"), ("porta_extra", "Porta extra"),
    ("memoria_mb", "Memoria"), ("cores", "CPUs"), ("disco_gb", "Disco"),
)


def linhas(texto: str) -> list[str]:
    """Uma entrada por linha (virgula tambem separa), sem vazios."""
    return [p.strip() for p in (texto or "").replace(",", "\n").splitlines() if p.strip()]


def jogo_do_form(form: Any) -> tuple[dict, list[str]]:
    """Le o formulario de jogo novo: devolve o que mandar ao broker, e os erros de tipo."""
    erros: list[str] = []
    dados: dict = {}
    for campo in CAMPOS_DE_TEXTO:
        valor = (form.get(campo) or "").strip()
        if valor:
            dados[campo] = valor
    for campo, rotulo in CAMPOS_NUMERICOS:
        bruto = (form.get(campo) or "").strip()
        if not bruto:
            continue
        if NUMERO_RE.fullmatch(bruto):
            dados[campo] = int(bruto)
        else:
            erros.append(f"{rotulo} deve ser um numero.")
    dados["portas"] = [p for p in re.split(r"[\s,]+", (form.get("portas") or "").strip()) if p]
    dados["config_files"] = linhas(form.get("config_files", ""))
    dados["backup_paths"] = linhas(form.get("backup_paths", ""))
    dados["receitas"] = [r for r in form.getlist("receitas") if r in BROKER_RECEITAS]
    dados["deslocavel"] = form.get("deslocavel") == "1"
    return dados, erros
