"""One function per query, instead of raw SQL scattered across the callers.

Before this, the same `SELECT * FROM servers WHERE id = ?` appeared in eight places, and
an `UPDATE servers SET ...` with a hand-written column list in four more. None of that
breaks when a column is renamed: it breaks on the FIRST VISIT to the screen that uses the
copy left behind, at runtime, with no lint or test complaining - which is why the rename
migrations had to be written so carefully.

**Every function here takes the connection as its FIRST parameter.** It never calls
`db()`: the connection is per request and lives in Flask's `g`, and a repository that
fetched it by itself would not serve the monitor or the scheduler, which run on their own
thread without `g`. Passing the connection is also what lets a query be tested without
starting any application.

**Nothing here decides.** No `flash`, no `abort`, no translation, no rule about who may see
what: that belongs to the caller. The repository only knows how to read and write rows.
"""
