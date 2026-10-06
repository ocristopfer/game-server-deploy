"""Screen text must not be born a literal: `translate` would return the sentence as is.

The `i18n` cascade is "requested language -> pt -> the key itself". A whole sentence passed
to `translate` is not a key of anything, so it comes out UNCHANGED - and the English screen
shows Portuguese, with no error, no log and no other test complaining: `test_i18n.py` checks
the CALLS of `_()`/`_h()`, not what a function returned.

It has already happened twice. First in the two password sentences and the history label
`broker-jogo`. Then in sixteen more, found against the live container: with the screen in
English, the operator 403 said "restrita" and the nonexistent route said "Pagina nao
encontrada". The barriers (`abort`), the form errors (`errors.append`) and the flashes were
all literals.

The test looks at the three doors through which text reaches the screen and demands a KEY,
never a sentence: `abort(codigo, ...)`, `errors.append(...)` and `flash(...)`. A call with
`Message(...)`, `translate(...)` or a variable passes; a literal with a space does not.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from gamepanel import i18n

ROOT = Path(__file__).resolve().parents[3]
SCREEN_FILES = [ROOT / "src/gamepanel/app.py",
                *sorted((ROOT / "src/gamepanel/blueprints").glob("*.py"))]

# Where the text reaches the PERSON. `_log_broker_action` and `notify` are left out: the first
# writes a job's output (in the deploy language, on purpose - see `label_for_db`) and the
# second builds the channel notice, which follows the same rule.
DOORS = {"abort", "flash", "append"}


def _sentences() -> list[tuple[str, int, str]]:
    """Literals with a space that come in through one of the doors. The space is the signal: a
    catalog key (`error.admin_only`) never has one, a sentence always does."""
    found: list[tuple[str, int, str]] = []
    for path in SCREEN_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name not in DOORS:
                continue
            # `errors.append` is the door; `log.append`/`lines.append` are not screen.
            if name == "append" and getattr(node.func, "value", None) is not None:
                target = getattr(node.func.value, "id", "")
                if target not in ("errors", "failures"):
                    continue
            for arg in node.args:
                # `abort(403, ...)`: the code is the first argument and is not text.
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and " " in arg.value:
                    found.append((path.name, node.lineno, arg.value))
                # An f-string with a sentence inside counts the same: it is not a key either.
                if isinstance(arg, ast.JoinedStr):
                    text = "".join(v.value for v in arg.values
                                   if isinstance(v, ast.Constant) and isinstance(v.value, str))
                    if " " in text.strip():
                        found.append((path.name, node.lineno, text))
    return found


def test_nenhuma_frase_literal_chega_a_tela():
    leftover = sorted({f"{f}:{n} {text[:60]!r}" for f, n, text in _sentences()})
    assert leftover == [], (
        "frase literal indo para a tela; ela sai igual no idioma de quem olha. Ponha em "
        "pt.py/en.py e use i18n.Message(chave):\n  " + "\n  ".join(leftover))


def test_a_varredura_olha_para_os_arquivos_de_tela():
    """Zero files is the silent way for this test to stop meaning anything."""
    assert len(SCREEN_FILES) >= 15


@pytest.mark.parametrize("key", [
    "error.not_found", "error.admin_only", "error.terminal_disabled",
    "error.broker_disabled", "flash.server_duplicate", "flash.username_invalid",
    "flash.schedule_bad_interval", "error.upload_too_large",
])
def test_as_chaves_das_barreiras_existem_nos_DOIS_idiomas(key: str):
    """A key without its pair shows on screen as `error.admin_only`, which is loud but ugly."""
    assert key in i18n.CATALOGS["pt"]
    assert key in i18n.CATALOGS["en"]


# ------------------------------------------- game fields: a FieldSpec carries keys

FIELD_BUILDERS = {"FieldSpec", "flag", "factor", "enum_of", "duration"}


def _field_sentences() -> list[str]:
    """Literals with a space handed to a field builder in `games/` (label, help, options, unit).

    `test_game_texts.py` checks the RESULT (every text is a key of both catalogs); this one
    points at the LINE, which is what the person fixing it needs.
    """
    found: list[str] = []
    for path in sorted((ROOT / "src/gamepanel/games").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name not in FIELD_BUILDERS:
                continue
            values = [*node.args, *(k.value for k in node.keywords)]
            values += [v for d in values if isinstance(d, ast.Dict) for v in d.values if v is not None]
            for value in values:
                if isinstance(value, ast.Constant) and isinstance(value.value, str) and " " in value.value:
                    found.append(f"{path.name}:{node.lineno} {value.value[:60]!r}")
    return found


def test_campo_de_jogo_recebe_chave_e_nao_frase():
    leftover = _field_sentences()
    assert leftover == [], (
        "campo de jogo com frase em vez de chave; ponha o texto em pt.py/en.py como "
        "game.<adaptador>.<campo>.label/help/opt.<valor>:\n  " + "\n  ".join(leftover))


# ------------------------------------------- exceptions: a sentence raised is a sentence shown

PACKAGE = ROOT / "src/gamepanel"

# Whole files whose raised text never reaches the panel screen.
NOT_SCREEN_FILES = {
    # Run INSIDE the game container (sent as text over SSH): their messages are job output.
    "games/mods/*_remote.py": "roda no container; a mensagem vira saida do job",
    "games/mods/ue_sym_layout.py": "roda no container; a mensagem vira saida do job",
    "games/mods/ue_linux_layout.py": "roda no container; a mensagem vira saida do job",
    # The bootstrap CLI prints to the terminal of whoever runs it, not to the panel.
    "cli.py": "linha de comando, nao tela",
    # Read once at start; a bad option goes to the journal and the panel does not even start.
    "config.py": "erro de partida, vai para o journal",
    # Every WebAuthnError is logged; the screen shows only passkey.login_failed/register_failed,
    # on purpose (the detail would tell an attacker which check failed).
    "security/webauthn.py": "so vai para o log; a tela mostra a chave generica de passkey",
    "blueprints/passkeys.py": "so vai para o log; a tela mostra a chave generica de passkey",
    # Every PushError is caught by push_client/push_keys and becomes push.bad_keys or a log line.
    "security/webpush.py": "so vai para o log; a tela mostra push.bad_keys",
    # The root updater: its text goes to the journal and to the status JSON, shown on the
    # Updates screen as LOG output (like a job), never as a sentence of the panel.
    "updater.py": "servico root; a mensagem e saida de log, como a de um job",
}

# Single raises that stay literal, each with its reason: (file, start of the message).
NOT_SCREEN_RAISES = {
    # Programming errors: an invariant of our own code, never something a person can cause.
    ("app.py", "ui.ACTIONS e app.COMMANDS fora de sincronia"): "invariante checado no import",
    ("app.py", "INSERT nao devolveu id"): "invariante do sqlite",
    ("persistence/repositories/jobs.py", "INSERT em jobs nao devolveu id"): "invariante do sqlite",
    ("runtime/backups.py", "_RESTORE_CHECK_AWK nao pode ter aspas"): "invariante checado no import",
    ("runtime/remote_cmd.py", "acao sem comando"): "a tabela de acoes e do codigo",
    ("runtime/backup_archive.py", "prefixo de backup invalido"): "o prefixo e montado pelo codigo",
    ("games/mods/antivirus.py", "o bloco de instalacao do ClamAV"): "invariante do script",
    ("games/mods/antivirus.py", "token de envio invalido"): "o token e gerado pelo painel (hex)",
    ("security/qr.py", "nenhuma mascara candidata"): "invariante do algoritmo",
    ("security/qr.py", " bytes: o maximo e "): "o painel so codifica a URI otpauth, que cabe",
    # Text of a JOB's output (history, deploy language on purpose - see `label_for_db`).
    ("app.py", "o backup nao disse qual arquivo criou"): "saida de job",
    ("app.py", "a copia no container saiu"): "saida de job",
    ("app.py", "a copia "): "saida de job",
    ("runtime/backup_archive.py", "copia incompleta"): "saida de job",
    ("blueprints/broker.py", "o backup foi guardado, mas o broker recusou"): "saida de job",
    # Terminal of the `--role` bootstrap path in app.py (the CLI's own error).
    ("app.py", "papel invalido"): "linha de comando, nao tela",
    # Broker options, read once at start by `_configure_broker`, which prints them to stderr.
    ("integrations/broker_client.py", "impressao SHA-256 invalida"): "erro de partida",
    ("integrations/broker_client.py", "GAMEPANEL_BROKER_URL deve ser"): "erro de partida",
    ("integrations/broker_client.py", "sem TLS so em loopback"): "erro de partida",
    ("integrations/broker_client.py", "o token do broker precisa ter"): "erro de partida",
}


def _raised_sentences() -> list[tuple[str, int, str]]:
    """`raise X("a sentence")` / `raise X(f"a {sentence}")` anywhere in the panel package.

    The text of an exception is what `flash(..., reason=exc)` and `errors.append` show: raised
    as a literal it reaches the English screen in Portuguese - which is exactly what the config
    readers (`games/config_format.py`) did, where no test looked. It must be an `i18n.Message`.
    """
    skipped = {p for pattern in NOT_SCREEN_FILES for p in PACKAGE.glob(pattern)}
    found = []
    for path in sorted(PACKAGE.rglob("*.py")):
        if path in skipped or "i18n" in path.parts:
            continue
        relative = path.relative_to(PACKAGE).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call) and node.exc.args):
                continue
            arg = node.exc.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                text = arg.value
            elif isinstance(arg, ast.JoinedStr):
                text = "".join(v.value for v in arg.values
                               if isinstance(v, ast.Constant) and isinstance(v.value, str))
            else:
                continue
            if " " not in text.strip():
                continue
            if any(file == relative and text.startswith(start) for file, start in NOT_SCREEN_RAISES):
                continue
            found.append((relative, node.lineno, text))
    return found


def test_nenhuma_excecao_nasce_com_frase_literal():
    leftover = sorted(f"{f}:{n} {text[:60]!r}" for f, n, text in _raised_sentences())
    assert leftover == [], (
        "excecao levantada com frase literal; se ela chega a tela, use i18n.Message(chave) "
        "(pt.py/en.py); se nunca chega, ponha em NOT_SCREEN_RAISES com o motivo:\n  "
        + "\n  ".join(leftover))


def test_as_excecoes_da_lista_ainda_existem():
    """An exception listed here and later removed from the code would keep a hole open for
    the next sentence that happens to start the same way."""
    texts = {}
    for path in PACKAGE.rglob("*.py"):
        texts[path.relative_to(PACKAGE).as_posix()] = path.read_text(encoding="utf-8")
    stale = [f"{f}: {start!r}" for f, start in NOT_SCREEN_RAISES if start not in texts.get(f, "")]
    assert stale == [], "excecao listada que o codigo nao tem mais:\n  " + "\n  ".join(stale)
    for pattern in NOT_SCREEN_FILES:
        assert list(PACKAGE.glob(pattern)), f"arquivo listado que nao existe mais: {pattern}"
