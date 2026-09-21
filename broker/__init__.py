"""Broker de provisionamento: cria instancias de jogo (Proxmox) e abre portas (OPNsense).

O painel nao guarda nenhuma credencial de infraestrutura; ele pede ao broker um punhado
de verbos fixos (ver `api.py`) e o broker valida tudo de novo do lado dele.
"""
