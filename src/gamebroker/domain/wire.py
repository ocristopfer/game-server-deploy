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
        "number": row["number"],
        "proto": row["proto"],
        "role": row["role"],
    }


def instance(row: Any) -> dict:
    """Uma instancia de jogo, como a API a mostra.

    Hoje os nomes batem com os da coluna, porque o banco foi traduzido logo depois desta
    camada nascer. O valor dela nao e a traducao: e a LISTA ser fixa. Um `SELECT *` leva
    para o JSON qualquer coluna nova no dia em que ela for criada, e ai ela e contrato
    sem ninguem ter decidido — foi assim que o formato de fio e o esquema do banco
    ficaram amarrados um no outro da primeira vez.
    """
    return {
        "id": row["id"],
        "ctid": row["ctid"],
        "ip": row["ip"],
        "game": row["game"],
        "name": row["name"],
        "hostname": row["hostname"],
        "state": row["state"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "detail": row["detail"],
        "ports": [port(p) for p in row.get("ports", ())],
    }


def operation(row: Any) -> dict:
    """Uma operacao em andamento ou terminada, como a API a mostra.

    O `log` vai inteiro: e ele que o painel mostra enquanto a criacao acontece, e cortar
    aqui deixaria a tela sem dizer em que fase a instalacao parou.
    """
    return {
        "id": row["id"],
        "instance_id": row["instance_id"],
        "kind": row["kind"],
        "state": row["state"],
        "log": row["log"],
        "result": row["result"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
    }
