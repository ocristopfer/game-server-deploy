"""Gestor de mods: o que cada jogo entende por "mod", e onde ele mora no servidor.

"Mod" nao e a mesma coisa em todo jogo, e o erro seria tratar tudo como "arquivo numa
pasta". No Euro Truck Simulator 2 o servidor NAO carrega arquivo de mod nenhum: o que ele
le sao os `server_packages`, exportados do jogo com os mods ativos - a tela mostra o que
esta dentro deles e o que os jogadores precisam instalar. Em outros (Palworld) o mod e um
arquivo que o servidor precisa ter na pasta certa.

Puro como `navigation.py`: sem Flask, sem SSH. Quem vai ao container e o blueprint.
"""
