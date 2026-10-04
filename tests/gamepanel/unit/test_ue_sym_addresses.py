"""Gerador do UE4SS_Addresses.ini (games/mods/ue_sym_addresses.py), contra um ELF e um .sym de mentira.

O executavel montado aqui tem so o que o gerador le: os segmentos LOAD (codigo e dados) e, no
codigo, as quatro funcoes auxiliares com as MESMAS instrucoes medidas no Dragonwilds - o
`mov rcx, [GNatives + rcx*8]` do FFrame::Step, o `mov rdi, [rip+GMalloc]` do FMemory::Free e o
`mov edi, &GUObjectArray; call AllocateObjectPool` do UObjectBaseInit.
"""
from __future__ import annotations

import struct

import pytest

from gamepanel.games.mods import ue_sym_addresses as gen

BASE = 0x200000
DATA = 0x800000
GNATIVES, GMALLOC, GUOBJECTARRAY = DATA + 0x100, DATA + 0x200, DATA + 0x300
STEP, FREE, POOL, INIT, FNAME = 0x100, 0x200, 0x300, 0x400, 0x500


def _code() -> bytes:
    code = bytearray(0x600)
    # FFrame::Step: mov rcx, [disp32 + rcx*8]
    code[STEP:STEP + 8] = bytes([0x48, 0x8B, 0x0C, 0xCD]) + struct.pack("<I", GNATIVES)
    # FMemory::Free: push rbx; mov rdi, [rip+X]
    rel = GMALLOC - (BASE + FREE + 1 + 7)
    code[FREE:FREE + 8] = bytes([0x53, 0x48, 0x8B, 0x3D]) + struct.pack("<i", rel)
    code[POOL] = 0xC3
    # UObjectBaseInit: mov edi, imm32; call AllocateObjectPool
    call = (BASE + POOL) - (BASE + INIT + 5 + 5)
    code[INIT:INIT + 10] = bytes([0xBF]) + struct.pack("<I", GUOBJECTARRAY) + bytes([0xE8]) + struct.pack("<i", call)
    code[FNAME] = 0xC3
    return bytes(code)


def _elf(code: bytes) -> bytes:
    phoff, phnum = 64, 2
    text_off = phoff + 56 * phnum
    head = b"\x7fELF" + bytes([2, 1, 1]) + bytes(9)
    head += struct.pack("<HHIQQQIHHHHHH", gen.ELF_EXEC, 0x3E, 1, BASE, phoff, 0, 0, 64, 56, phnum, 64, 0, 0)
    # Codigo: le e executa, a partir do comeco do arquivo (como o executavel de verdade).
    text = struct.pack("<IIQQQQQQ", gen.PT_LOAD, 5, 0, BASE, BASE, text_off + len(code), text_off + len(code), 0x1000)
    # Dados: gravavel, so memoria (bss) - e onde os globais moram.
    data = struct.pack("<IIQQQQQQ", gen.PT_LOAD, 6, 0, DATA, DATA, 0, 0x1000, 0x1000)
    # O codigo comeca em text_off no arquivo; as funcoes ficam no endereco BASE + deslocamento.
    blob = head + text + data
    return blob + code[len(blob):] if len(blob) <= STEP else pytest.fail("cabecalho invade o codigo")


def _sym(functions: dict[str, int]) -> bytes:
    table = b"Arquivo.cpp\n"
    records = []
    for name, offset in functions.items():
        records.append(struct.pack("<QIII", offset, 1, 0, len(table)))
        table += name.encode() + b"\n"
    return struct.pack("<I", len(records)) + b"".join(records) + table


@pytest.fixture
def server(tmp_path):
    exe = tmp_path / "Game-Linux-Shipping"
    exe.write_bytes(_elf(_code()))
    (tmp_path / "Game-Linux-Shipping.sym").write_bytes(_sym({
        "FFrame::Step(UObject*, void*)": STEP,
        "FMemory::Free(void*)": FREE,
        "FUObjectArray::AllocateObjectPool(int, int, bool)": POOL,
        "UObjectBaseInit()": INIT,
        "FName::FName(char16_t const*, EFindName)": FNAME,
    }))
    return exe


def test_gera_funcoes_e_os_tres_globais(server, capsys):
    assert gen.main([str(server)]) == 0
    out = capsys.readouterr().out
    assert f"FNameConstructor = 0x{BASE + FNAME:X}" in out
    assert f"GNatives = 0x{GNATIVES:X}" in out
    assert f"GMalloc = 0x{GMALLOC:X}" in out
    assert f"GUObjectArray = 0x{GUOBJECTARRAY:X}" in out


def test_global_fora_de_segmento_gravavel_e_descartado(tmp_path, capsys):
    """Padrao que casou no lugar errado aponta para codigo: melhor faltar que mentir."""
    code = bytearray(_code())
    code[STEP + 4:STEP + 8] = struct.pack("<I", BASE + 0x10)
    exe = tmp_path / "Game"
    exe.write_bytes(_elf(bytes(code)))
    (tmp_path / "Game.sym").write_bytes(_sym({"FFrame::Step(UObject*, void*)": STEP,
                                              "FName::FName(char16_t const*, EFindName)": FNAME}))
    gen.main([str(exe)])
    out = capsys.readouterr().out
    assert "GNatives = 0x" not in out
    assert "; GNatives = nao achado" in out


def test_lea_rip_relativo_tambem_vale_para_o_this():
    """Executavel PIE monta o `this` com `lea rdi, [rip+X]` em vez de `mov edi, imm32`."""
    va, target = 0x1000, 0x5000
    lea = bytes([0x48, 0x8D, 0x3D]) + struct.pack("<i", 0x9000 - (va + 7))
    call = bytes([0xE8]) + struct.pack("<i", target - (va + 7 + 5))
    assert gen.this_of_call(lea + call, va, target) == 0x9000
