"""Reads and writes `push_subscriptions`: the devices that receive alerts as notifications."""
from __future__ import annotations

import sqlite3

LABEL_MAX = 60
ERROR_MAX = 300


def all_devices(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM push_subscriptions ORDER BY id").fetchall()


def for_user(conn: sqlite3.Connection, uid: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM push_subscriptions WHERE user_id = ? ORDER BY id", (uid,)).fetchall()


def count_for_user(conn: sqlite3.Connection, uid: int) -> int:
    return conn.execute(
        "SELECT COUNT(*) AS n FROM push_subscriptions WHERE user_id = ?", (uid,)).fetchone()["n"]


def by_id(conn: sqlite3.Connection, uid: int, sid: int) -> sqlite3.Row | None:
    """Only the owner's: one person must not test, edit or delete another person's device."""
    return conn.execute(
        "SELECT * FROM push_subscriptions WHERE id = ? AND user_id = ?", (sid, uid)).fetchone()


def by_endpoint(conn: sqlite3.Connection, endpoint: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM push_subscriptions WHERE endpoint = ?", (endpoint,)).fetchone()


def upsert(conn: sqlite3.Connection, uid: int, endpoint: str, p256dh: str, auth: str,
           events: str, label: str, now: str) -> None:
    """Same endpoint = same browser: the keys and the owner are refreshed, the chosen events stay.

    The browser hands out the SAME endpoint when the page subscribes again, and a NEW one when the
    push service rotates it. Keying on the endpoint makes the first case an update instead of a
    second row that would deliver every alert twice to the same phone. The owner is overwritten
    on purpose: whoever signs in on a shared device and turns notifications on is who gets them.
    """
    conn.execute(
        "INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, events, label, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(endpoint) DO UPDATE SET user_id = excluded.user_id,"
        " p256dh = excluded.p256dh, auth = excluded.auth, last_error = ''",
        (uid, endpoint, p256dh, auth, events, label[:LABEL_MAX], now))


def set_events(conn: sqlite3.Connection, uid: int, sid: int, events: str, label: str) -> bool:
    cur = conn.execute(
        "UPDATE push_subscriptions SET events = ?, label = ? WHERE id = ? AND user_id = ?",
        (events, label[:LABEL_MAX], sid, uid))
    return cur.rowcount > 0


def delete(conn: sqlite3.Connection, uid: int, sid: int) -> bool:
    cur = conn.execute(
        "DELETE FROM push_subscriptions WHERE id = ? AND user_id = ?", (sid, uid))
    return cur.rowcount > 0


def delete_endpoint(conn: sqlite3.Connection, uid: int, endpoint: str) -> bool:
    cur = conn.execute(
        "DELETE FROM push_subscriptions WHERE endpoint = ? AND user_id = ?", (endpoint, uid))
    return cur.rowcount > 0


def forget(conn: sqlite3.Connection, sid: int) -> None:
    """The push service said the subscription is gone (404/410): nobody owns it anymore."""
    conn.execute("DELETE FROM push_subscriptions WHERE id = ?", (sid,))


def mark_result(conn: sqlite3.Connection, sid: int, now: str, error: str) -> None:
    if error:
        conn.execute("UPDATE push_subscriptions SET last_error = ? WHERE id = ?",
                     (error[:ERROR_MAX], sid))
    else:
        conn.execute("UPDATE push_subscriptions SET last_ok_at = ?, last_error = '' WHERE id = ?",
                     (now, sid))
