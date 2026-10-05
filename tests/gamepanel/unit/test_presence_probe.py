"""Counting by the active conversations on the game port (gamepanel.runtime.presence_probe).

The number comes from the `players` set that lib/ct-firewall.sh maintains. The `nft -j` format
is the contract, and the table and set names are the other end of the shell script.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from gamepanel.runtime import presence_probe as pp
from gamepanel.runtime.a2s import QueryError
from gamepanel.runtime.ssh import RemoteError

ROOT = Path(__file__).resolve().parents[3]


def nft_json(elements) -> str:
    set_ = {"family": "inet", "name": "players", "table": "ct_firewall"}
    if elements is not None:
        set_["elem"] = elements
    return json.dumps({"nftables": [{"metainfo": {"version": "1.1.3"}}, {"set": set_}]})


def test_conta_cada_ip_e_porta_do_conjunto():
    raw = nft_json([{"elem": {"val": {"concat": ["1.2.3.4", 51000]}, "expires": 15}},
                    {"elem": {"val": {"concat": ["1.2.3.4", 51001]}, "expires": 9}}])
    assert pp.count_from_json(raw) == 2


def test_conjunto_vazio_e_zero_jogadores():
    """nft omits `elem` when nobody is there - not an error, it is an empty server."""
    assert pp.count_from_json(nft_json(None)) == 0


def test_saida_que_nao_e_o_conjunto_vira_erro_de_tela():
    with pytest.raises(QueryError):
        pp.count_from_json("lixo")
    with pytest.raises(QueryError):
        pp.count_from_json(json.dumps({"nftables": []}))


def test_ct_sem_o_conjunto_diz_para_reaplicar_o_firewall():
    def ssh(*a):
        raise RemoteError("Error: No such file or directory\nlist set inet ct_firewall players")

    with pytest.raises(QueryError, match="firewall"):
        pp.players_from_presence(ssh, {"host": "x"})


def test_ssh_fora_do_ar_nao_vira_falta_de_firewall():
    """Telling to reapply the rule on a CT that is merely stopped would send the person looking in the wrong place."""
    def ssh(*a):
        raise RemoteError("ssh: connect to host x port 22: Connection timed out")

    with pytest.raises(QueryError, match="timed out"):
        pp.players_from_presence(ssh, {"host": "x"})


def test_nomes_da_tabela_e_do_conjunto_batem_com_o_firewall():
    """Both sides are text: renaming the set in the shell would silence the count without a word."""
    script = (ROOT / "lib" / "ct-firewall.sh").read_text(encoding="utf-8")
    assert f"table inet {pp.PRESENCE_TABLE} " in script
    assert f"set {pp.PRESENCE_SET} " in script
    assert f"@{pp.PRESENCE_SET} " in script
