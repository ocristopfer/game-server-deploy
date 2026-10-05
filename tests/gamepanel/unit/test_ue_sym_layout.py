"""Generator of the UE4SS files from the .sym (games/mods/ue_sym_layout.py).

The end-to-end path (Dragonwilds' executable and 300 MB .sym) was checked by hand against
the files tested on the server; here are the rules that do not need the game.
"""
from __future__ import annotations

from gamepanel.games.mods import ue_sym_layout as sl


def test_le_a_assinatura_do_template_e_a_do_sym_do_mesmo_jeito():
    template = sl.parse("void Serialize(FArchive&)")
    game = sl.parse("UObject::Serialize(FArchive&)")
    assert (template.method, template.params) == (game.method, game.params)
    assert game.owner == "UObject"


def test_retorno_ponteiro_nao_gruda_no_dono():
    """The demangler writes 'void *FMalloc::Malloc(...)': the owner is FMalloc, not '*FMalloc'."""
    sig = sl.parse("void *FMalloc::Malloc(unsigned long, unsigned int)")
    assert sig.owner == "FMalloc"
    assert sig.method == "Malloc"
    assert sig.params == sl.normalize("uint64, uint32")


def test_const_separa_as_sobrecargas():
    assert sl.parse("const FName& GetX() const").const is True
    assert sl.parse("FName& GetX()").const is False


def test_tipos_do_msvc_viram_os_do_itanium():
    assert sl.normalize("const wchar_t*, uint32, int64") == sl.normalize("char16_t const*, unsigned int, long")


def test_template_por_secao_com_o_destrutor_primeiro():
    sections = sl.read_template(
        "[UObject]\n; void* __vecDelDtor(uint32)\n__vecDelDtor\n; void ProcessEvent(UFunction*, void*)\nProcessEvent\n")
    names = [name for name, _sig in sections["UObject"]]
    assert names == ["__vecDelDtor", "ProcessEvent"]


def test_operando_relativo_vira_coringa():
    # call rel32, then mov rax, [rip+disp32] (48 8B 05 ...), then an ordinary byte.
    code = bytes([0xE8, 1, 2, 3, 4, 0x48, 0x8B, 0x05, 9, 9, 9, 9, 0xC3])
    keep = sl.wildcard_mask(code)
    assert keep == [True, False, False, False, False, True, True, True, False, False, False, False, True]


def test_gnatives_e_a_leitura_da_tabela_no_fframe_step():
    # mov rax, [rcx*8 + 0xDE38B70] = 48 8B 04 CD 70 8B E3 0D
    code = bytes([0x90, 0x90]) + bytes([0x48, 0x8B, 0x04, 0xCD, 0x70, 0x8B, 0xE3, 0x0D])
    assert sl.gnatives_offset(code) == 2


def test_extra_do_uplayer_casa_o_exec_da_vtable_principal():
    """FExec's Exec gets a slot in the primary vtable under Itanium; UE4SS Linux finds it there."""
    (name, signature), = sl.EXTRA_ENTRIES["UPlayer"]
    wanted = sl.parse(signature)
    game = sl.parse("UPlayer::Exec(UWorld*, char16_t const*, FOutputDevice&)")
    assert name == "Exec"
    assert (wanted.method, wanted.params) == (game.method, game.params)
