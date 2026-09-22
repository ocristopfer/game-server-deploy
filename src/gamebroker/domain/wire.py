"""O formato de FIO da API do broker, num lugar so.

Existe porque antes nao existia: `/v1/instancias` devolvia `SELECT * FROM instancias`, e
com isso o nome de cada COLUNA virava, sem ninguem decidir, o nome de cada campo do
JSON. Renomear uma coluna quebrava o painel; renomear um campo do JSON exigia uma
migration. As duas coisas ficaram amarradas uma na outra por acidente.

Aqui a traducao e explicita: de um lado a linha do banco (que pode mudar com uma
migration), do outro o contrato com quem consome a API (que so muda com o painel junto).
Uma funcao por recurso, e nada alem de renomear campo — se aparecer regra de negocio
nestas funcoes, ela esta no lugar errado.
"""
from __future__ import annotations

from typing import Any


def port(row: Any) -> dict:
    """Uma porta alocada, como a API a mostra."""
    return {
        "base": row["base"],
        "number": row["numero"],
        "proto": row["proto"],
        "role": row["papel"],
    }


def instance(row: Any) -> dict:
    """Uma instancia de jogo, como a API a mostra.

    `detalhe` sai como `detail` e pode conter a mensagem de um erro de criacao — ele e
    para a pessoa ler no painel, nao para o painel decidir nada com ele.
    """
    return {
        "id": row["id"],
        "ctid": row["ctid"],
        "ip": row["ip"],
        "game": row["jogo"],
        "name": row["nome"],
        "hostname": row["hostname"],
        "state": row["estado"],
        "created_by": row["criado_por"],
        "created_at": row["criado_em"],
        "detail": row["detalhe"],
        "ports": [port(p) for p in row.get("portas", ())],
    }


def operation(row: Any) -> dict:
    """Uma operacao em andamento ou terminada, como a API a mostra.

    O `log` vai inteiro: e ele que o painel mostra enquanto a criacao acontece, e cortar
    aqui deixaria a tela sem dizer em que fase a instalacao parou.
    """
    return {
        "id": row["id"],
        "instance_id": row["instancia_id"],
        "kind": row["tipo"],
        "state": row["estado"],
        "log": row["log"],
        "result": row["resultado"],
        "started_at": row["iniciada_em"],
        "finished_at": row["terminada_em"],
    }
