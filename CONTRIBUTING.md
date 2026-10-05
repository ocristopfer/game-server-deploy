# Contributing

Thanks for your interest. This file is the short version; the full coding conventions
live in [CLAUDE.md](CLAUDE.md).

## Why "CLAUDE.md"?

`CLAUDE.md` is the repository's contributor guide: naming rules, where each thing lives,
the contracts the tests enforce, and the traps that already cost a bug. The name comes
from the fact that it is also read automatically by AI coding assistants (such as Claude
Code), so humans and tools follow the same rules. Read it before your first change — it is
long because every rule there comes with the reason behind it.

## Setup

You need [uv](https://docs.astral.sh/uv/) and, for the full dev environment, Docker.

```bash
uv sync    # creates .venv with gamepanel/gamebroker (editable) + pytest, ruff, mypy
```

`uv` only manages the development environment. It is never used in production.

## Tests and linters

```bash
uv run pytest tests/gamepanel/unit   # fast loop while editing (~30 s)
uv run pytest                        # the whole suite, from the repo root
uv run ruff check src tests          # must stay at zero findings
uv run mypy src                      # must stay at zero errors
```

`ruff` and `mypy` are at zero today, so any finding is a new one: fix it, or disable the
rule in the config with the reason written down — never with a bare `# noqa`.

`tests/gamepanel/test_javascript.py` needs `node` on the PATH and is skipped without it.

## Development environment

```bash
docker compose up --build -d    # panel at http://localhost:8080 (admin/admin12345)
```

This starts the panel, a toy broker and two fake game containers. Templates and static
files are bind-mounted (reload the page); a new route or decorator needs
`docker compose restart panel`. See "Verify before saying you are done" in CLAUDE.md for
the full checklist, including running the suite inside the container.

## Pull requests

Before opening a PR, please make sure that:

- the test suite is green (`uv run pytest`);
- `ruff check` and `mypy` are still at zero;
- every screen you touched was checked by hand in **both themes** (light and dark) and
  **both languages** (Portuguese and English), and as both an admin and an operator;
- new screen text goes into both i18n catalogs (`pt.py` and `en.py`, same keys);
- identifiers, file names, comments and docstrings are in English (test function names
  stay as descriptive Portuguese sentences — see CLAUDE.md);
- **no new dependency is added to production.** The panel runs on the Python standard
  library plus `python3-flask` from Debian's apt, and nothing else: no `pip install`, no
  CDN. Development-only tools go in the `dev` group of `pyproject.toml`.

Keep PRs focused, and explain in the description *why* the change is needed, not only
what it does.

## Security issues

Please do not open a public issue for a vulnerability. Follow
[SECURITY.md](SECURITY.md) instead.
