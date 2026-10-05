"""Generator of the UE4SS files for a Linux Unreal server without symbols (games/mods/ue_linux_layout.py).

It runs INSIDE the CT; here against a minimal ELF built in the test itself (one code segment and one
data segment) and against the numbers MEASURED on the real servers: The Front's FUObjectArray
offset and the shape of the exported vtables.
"""
from __future__ import annotations

import struct

import pytest

from gamepanel.games.mods import ue_linux_layout as ull

CODE_VA = 0x401000
DATA_VA = 0x600000


def elf(path, code: bytes, data: bytes = b"\0" * 64) -> str:
    """ELF64 with one code PT_LOAD (R+X) and one data PT_LOAD (RW). No section table."""
    code_off, data_off = 0x1000, 0x1000 + len(code) + (-len(code)) % 0x1000
    header = b"\x7fELF" + bytes([2, 1, 1, 0]) + b"\0" * 8
    header += struct.pack("<HHIQQQIHHHHHH", 2, 0x3E, 1, CODE_VA, 64, 0, 0, 64, 56, 2, 64, 0, 0)
    phdrs = struct.pack("<IIQQQQQQ", 1, 5, code_off, CODE_VA, CODE_VA, len(code), len(code), 0x1000)
    phdrs += struct.pack("<IIQQQQQQ", 1, 6, data_off, DATA_VA, DATA_VA, len(data), len(data) + 0x1000, 0x1000)
    blob = bytearray(data_off + len(data))
    blob[:len(header + phdrs)] = header + phdrs
    blob[code_off:code_off + len(code)] = code
    blob[data_off:data_off + len(data)] = data
    target = path / "Server-Linux-Shipping"
    target.write_bytes(bytes(blob))
    return str(target)


def tokens(text: str) -> list[int | None]:
    return ull.parse_masked(text)


def test_mascara_tambem_o_rip_sem_prefixo_rex():
    """cmpb $0,[rip+d] (80 3D d32 00) has no REX: without this rule the displacement, which changes from
    game to game, went into the pattern as fixed (that is why the 4.27 pack's FName::ToString did not match)."""
    code = bytes.fromhex("80 3D 12 2A DA 03 00 48 8B 05 11 22 33 44 E8 01 02 03 04")
    assert ull.masked(code) == "80 3D ?? ?? ?? ?? 00 48 8B 05 ?? ?? ?? ?? E8 ?? ?? ?? ??"


def test_resolve_alonga_ate_ficar_unico(tmp_path):
    prologue = bytes.fromhex("55 41 57 41 56 41 55 41 54 53 48 81 EC")
    code = prologue + b"\x01\x01\x01" + b"\x90" * 16 + prologue + b"\x02\x02\x02" + b"\x90" * 16
    image = ull.Image(elf(tmp_path, code))
    wanted = prologue + b"\x02\x02\x02"
    (aob, body), address = ull.resolve(image, tokens(" ".join(f"{b:02X}" for b in wanted)), "return MatchAddress", 12)
    assert address == CODE_VA + len(prologue) + 3 + 16
    assert aob.endswith("02 02 02") and body == "return MatchAddress"


def test_prologo_comum_demais_alonga_em_vez_de_desistir(tmp_path, monkeypatch):
    """With 12 bytes the pattern was the push/push/sub of thousands of functions: the generator gave up at
    the match ceiling and FName::ToString came out in no game at all."""
    monkeypatch.setattr(ull, "MAX_HITS", 1)
    prologue = bytes.fromhex("55 41 57 41 56 41 55 41 54 53 48 81")
    code = (prologue + b"\xAA" * 4) * 3 + prologue + b"\xBB" * 4
    image = ull.Image(elf(tmp_path, code))
    found = ull.resolve(image, tokens(" ".join(f"{b:02X}" for b in prologue + b"\xBB" * 4)), "return MatchAddress", 12)
    assert found is not None and found[1] == CODE_VA + 3 * 16


def test_copias_identicas_valem_se_dao_o_mesmo_endereco(tmp_path):
    """FMemory::Free and operator delete are the same code: two matches, a single global."""
    # mov rdi,[rip+d] pointing to DATA_VA; the pattern starts at the operand.
    def load(at: int) -> bytes:
        rel = struct.pack("<i", DATA_VA - (CODE_VA + at + 7))
        return bytes.fromhex("48 8B 3D") + rel + bytes.fromhex("48 85 FF 75 0C C3")
    first = load(0)
    code = first + bytes.fromhex("90 90 90") + load(len(first) + 3)
    image = ull.Image(elf(tmp_path, code))
    body = "return MatchAddress + 0x4 + DerefToInt32(MatchAddress) - 0x0"
    (aob, new_body), address = ull.resolve(image, tokens("?? ?? ?? ?? 48 85 FF 75 0C C3 ?? ??"), body, 12)
    assert address == DATA_VA
    assert aob.startswith("48 8B 3D ??") and "(MatchAddress + 0x3)" in new_body


def test_padrao_que_comeca_em_coringa_ganha_os_bytes_da_instrucao(tmp_path):
    """The UE4SS scanner refuses a pattern that starts with ??, and the refusal took down the whole pass
    (the other signatures came out as not found). Measured on Smalland with GUObjectArray."""
    code = bytes.fromhex("90 90 74 1B BF") + struct.pack("<I", DATA_VA) + bytes.fromhex("58 E9 01 02 03 04 80 3D")
    image = ull.Image(elf(tmp_path, code))
    (aob, body), address = ull.resolve(image, tokens("?? ?? ?? ?? 58 E9 ?? ?? ?? ?? 80 3D"),
                                       "return DerefToInt32(MatchAddress) - 0x0", 12)
    assert aob.startswith("74 1B BF ?? ?? ?? ??")
    assert body == "return DerefToInt32((MatchAddress + 0x3)) - 0x0"
    assert address == DATA_VA


def test_endereco_do_tipo_errado_e_recusado(tmp_path):
    image = ull.Image(elf(tmp_path, b"\x90" * 32))
    assert ull.plausible(image, "FName_ToString", CODE_VA + 4)
    assert not ull.plausible(image, "FName_ToString", DATA_VA)
    assert ull.plausible(image, "GUObjectArray", DATA_VA + 8)
    assert not ull.plausible(image, "GUObjectArray", CODE_VA + 4)


def test_alinhamento_por_codigo_com_virtuais_a_mais_no_alvo():
    """Soulmask has 62 extra virtuals in AGameModeBase: the anchors (code unique on both sides) take each
    name to its position in the target, and between anchors with the same offset it interpolates."""
    ref = [f"f{i}" for i in range(10)]
    target = [*ref[:4], "novo1", "novo2", *ref[4:]]
    resolve_slot, anchors = ull.slot_mapping(ref, target)
    assert anchors == 10
    assert [resolve_slot(i) for i in (0, 3, 4, 9)] == [0, 3, 6, 11]
    # Repeated code (two identical empty functions) does not become an anchor; it interpolates between neighbors.
    ref2 = ["a", "x", "x", "b", "c"]
    resolve2, _ = ull.slot_mapping(ref2, ["a", "x", "x", "b", "c"])
    assert resolve2(2) == 2


def test_deslocamento_do_fuobjectarray_medido_no_the_front():
    """Real histograms (code accesses to each GUObjectArray member): Squad 44 (the reference),
    The Front (+0x18) and Smalland (same)."""
    squad44 = {0x0: 8, 0x4: 51, 0x10: 5913, 0x20: 5936, 0x24: 558, 0x2C: 11793, 0x78: 9, 0x80: 27, 0xB8: 1}
    the_front = {0x0: 8, 0x4: 50, 0x10: 2013, 0x20: 2, 0x24: 422, 0x70: 1, 0x78: 2, 0x7C: 1, 0x90: 14,
                 0x98: 37, 0x9C: 5}
    smalland = {0x0: 8, 0x4: 50, 0x10: 2376, 0x24: 287, 0x58: 1, 0x60: 2, 0x64: 1, 0x78: 14, 0x80: 37,
                0x84: 5, 0xB8: 1}
    assert ull.fuobjectarray_shift(squad44, the_front) == 0x18
    assert ull.fuobjectarray_shift(squad44, smalland) == 0
    assert ull.fuobjectarray_shift(squad44, {}) == 0


def test_gmalloc_conferido_na_hora_le_zero_como_zero():
    """DerefToInt32 returns nil when it reads 0 - the high half of every vtable in a non-PIE executable.
    Without the `or 0` Lua raised an error and took the whole signature pass down with it."""
    lua = ull.runtime_lua([0x7E207B8, 0x7FFB928], [0x1718F18], "GMalloc")
    assert "0x7E207B8, 0x7FFB928" in lua
    assert "[0x1718F18] = true" in lua
    assert "(DerefToInt32(Address + 4) or 0)" in lua
    assert 'return "48 8B 3D ?? ?? ?? ??"' in lua


@pytest.mark.parametrize(("body", "expected"), [
    ("return MatchAddress", 0x1000),
    ("return DerefToInt32(MatchAddress + 0x4)", 0x2000),
    ("return DerefToInt32(MatchAddress) - 0x24", 0x1FDC),
    ("return MatchAddress + 0x4 + DerefToInt32(MatchAddress) - 0x10", 0x2FF4),
])
def test_formas_de_onmatchfound_que_o_gerador_entende(body, expected):
    class Fake:
        @staticmethod
        def int32(va: int) -> int:
            return {0x1000: 0x2000, 0x1004: 0x2000}.get(va, 0)
    assert ull.decoder(body)(Fake, 0x1000) == expected


def test_forma_desconhecida_e_recusada():
    with pytest.raises(ValueError, match="desconhecida"):
        ull.decoder("return os.execute('x')")
