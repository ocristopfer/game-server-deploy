"""The WIRE format of the broker API, in one place.

It exists because before it did not: `/v1/instancias` returned `SELECT * FROM instancias`,
and so the name of each COLUMN became, without anyone deciding it, the name of each JSON
field. Renaming a column broke the panel; renaming a JSON field required a migration. The
two ended up tied to each other by accident.

Here the translation is explicit: on one side the database row (which may change with a
migration), on the other the contract with the API consumer (which only changes together
with the panel). One function per resource, and nothing beyond renaming fields - if business
rules show up in these functions, they are in the wrong place.
"""
from __future__ import annotations

from typing import Any


def port(row: Any) -> dict:
    """An allocated port, as the API shows it."""
    return {
        "base": row["base"],
        "number": row["number"],
        "proto": row["proto"],
        "role": row["role"],
    }


def instance(row: Any) -> dict:
    """A game instance, as the API shows it.

    Today the names match the column names, because the database was translated right after
    this layer was born. Its value is not the translation: it is the list being FIXED. A
    `SELECT *` carries any new column into the JSON the day it is created, and then it is
    contract without anyone having decided it - that is how the wire format and the database
    schema got tied to each other the first time.
    """
    return {
        "id": row["id"],
        # `str()` for the same reason as in `db.taken`: in a migrated database the column holds
        # the old CTID as a number, and the wire must always be text - the panel compares and
        # concatenates, and a type that varies with the database's age is a defect waiting to happen.
        "handle": str(row["handle"]),
        "backend": row["backend"],
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
    """An operation in progress or finished, as the API shows it.

    The `log` goes in full: it is what the panel shows while the creation happens, and
    cutting it here would leave the screen unable to say at which phase the installation stopped.
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
