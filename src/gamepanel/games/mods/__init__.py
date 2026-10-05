"""Mod manager: what each game means by "mod", and where it lives on the server.

"Mod" is not the same thing in every game, and the mistake would be to treat everything as
"a file in a folder". In Euro Truck Simulator 2 the server loads NO mod file at all: what it
reads are the `server_packages`, exported from the game with the active mods - the screen shows
what is inside them and what the players need to install. In others (Palworld) the mod is a
file the server needs to have in the right folder.

Pure like `navigation.py`: no Flask, no SSH. Whoever goes to the container is the blueprint.
"""
