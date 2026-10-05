"""One file per game that has a quick-edit screen.

Adding a game means creating a module here (with `FILENAME` and `FIELDS`) and one line in
`registry.ADAPTERS` - without touching any route, template or the other games. A game
without an adapter is not left out of the panel: it falls back to the generic file editor,
which knows no game at all.

`test_game_registry.py` checks that no module here is left out of the registry: creating the
file and forgetting the line would raise no error, just leave a screen that stays generic.
"""
