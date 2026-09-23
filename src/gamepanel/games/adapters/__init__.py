"""Um arquivo por jogo com tela de edicao rapida.

Acrescentar um jogo e criar um modulo aqui (com `FILENAME` e `FIELDS`) e uma linha em
`registry.ADAPTERS` — sem tocar em rota, em template nem nos outros jogos. O jogo que
nao tem adapter nao fica de fora do painel: ele cai no editor de arquivo generico, que
nao conhece jogo nenhum.

`test_game_registry.py` cobra que nenhum modulo daqui fique fora do registro: criar o
arquivo e esquecer a linha nao daria erro, so uma tela que continua generica.
"""
