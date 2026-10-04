"""Gera o UE4SS_Addresses.ini de um servidor Unreal LINUX a partir do .sym que vem com ele.

Servidor Unreal de Linux costuma vir SEM simbolos no executavel (o do Dragonwilds e assim),
mas com um `<Executavel>.sym` ao lado: e o arquivo que o proprio Unreal usa para montar o
relatorio de crash, e tem o nome e o endereco de cada funcao. O port Linux do UE4SS aceita
esses enderecos por um UE4SS_Addresses.ini; sem eles, ele procura por padroes e, num motor
diferente do Palworld, acha errado ou nao acha.

Formato do .sym (lido do Dragonwilds, UE 5.6.1): uint32 com o numero de registros, registros
de 20 bytes {uint64 endereco, uint32 linha, uint32 arquivo, uint32 nome} e, logo depois, a
tabela de textos separados por QUEBRA DE LINHA (nao por \\0); arquivo e nome sao deslocamentos
EM BYTES nela. O endereco e relativo a base de carga do executavel: no Dragonwilds, base
0x200000 - somado a ela, cada endereco cai num prologo de funcao (conferido byte a byte).

Os GLOBAIS de dados (GUObjectArray, GMalloc, GNatives) nao tem registro no .sym, que so lista
funcoes. Cada um sai de uma funcao curta que o le, decodificando a instrucao que o referencia:
  GNatives      - FFrame::Step faz `mov reg, [GNatives + opcode*8]` (a tabela da VM de Blueprint)
  GMalloc       - FMemory::Free le o GMalloc antes de tudo (`mov rdi, [rip+X]`)
  GUObjectArray - UObjectBaseInit passa &GUObjectArray como `this` do AllocateObjectPool
O GNatives e o que mais importa: sem ele o port CHUTA a tabela por heuristica, e com o chute
errado todo hook nativo (RegisterHook numa funcao C++) desalinha a pilha do Blueprint e o
proprio Unreal aborta em UObject::execUndefined - medido no Dragonwilds. Endereco que nao cai
num segmento GRAVAVEL do executavel e descartado: e sinal de que o padrao casou no lugar errado.

Roda DENTRO do CT, como os instaladores remotos: o ue4ss_linux_remote recebe este texto do
painel e o executa com `python3 -c` (por isso so stdlib e sem import do `gamepanel`).

Uso a mao (dentro do CT, onde o .sym tem 300 MB e nao vale a pena copiar):
    python3 ue_sym_addresses.py <executavel> [<executavel>.sym] > UE4SS_Addresses.ini
So stdlib; varre o arquivo por mmap, sem montar texto para cada um dos milhoes de registros.
"""
from __future__ import annotations

import mmap
import struct
import sys
from typing import NamedTuple

# Chave do UE4SS_Addresses.ini (a que o port le) -> assinaturas possiveis no .sym.
WANTED: dict[str, tuple[str, ...]] = {
    "FNameToString": ("FName::ToString(FString&) const",),
    "FNameConstructor": ("FName::FName(char16_t const*, EFindName)", "FName::FName(wchar_t const*, EFindName)"),
    "StaticConstructObject": ("StaticConstructObject_Internal(FStaticConstructObjectParameters const&)",),
    "UGameEngineTick": ("UGameEngine::Tick(float, bool)",),
    "ProcessInternal": ("UObject::ProcessInternal(UObject*, FFrame&, void*)",),
    "ProcessLocalScriptFunction": ("ProcessLocalScriptFunction(UObject*, FFrame&, void*)",),
    "CallFunctionByNameWithArguments": (
        "UObject::CallFunctionByNameWithArguments(char16_t const*, FOutputDevice&, UObject*, bool)",),
}
# Funcoes que so servem para achar os globais (nao vao para o .ini).
HELPERS: dict[str, tuple[str, ...]] = {
    "_FrameStep": ("FFrame::Step(UObject*, void*)",),
    "_MemoryFree": ("FMemory::Free(void*)",),
    "_ObjectBaseInit": ("UObjectBaseInit()",),
    "_AllocateObjectPool": ("FUObjectArray::AllocateObjectPool(int, int, bool)",),
}
GLOBALS = ("GUObjectArray", "GMalloc", "GNatives")
# Quantos bytes do comeco de cada funcao auxiliar sao decodificados.
SCAN_BYTES = 512
# Ate quantos bytes antes do `call` se procura a instrucao que monta o `this`.
THIS_WINDOW = 40
NEWLINE = bytes([10])
RECORD = struct.Struct("<QIII")
ELF_EXEC = 2
PT_LOAD = 1
PF_W = 2
LEA_RDI_RIP = bytes([0x48, 0x8D, 0x3D])
MOV_EDI_IMM32 = 0xBF
CALL_REL32 = 0xE8


class Segment(NamedTuple):
    vaddr: int
    offset: int
    filesz: int
    memsz: int
    writable: bool


def load_segments(executable: str) -> list[Segment]:
    """Os segmentos LOAD (executavel nao-PIE: o endereco virtual ja e o de execucao)."""
    with open(executable, "rb") as f:
        head = f.read(64)
        if head[:4] != b"\x7fELF":
            raise SystemExit(f"{executable} nao e um ELF")
        (e_type,) = struct.unpack_from("<H", head, 16)
        if e_type != ELF_EXEC:
            raise SystemExit("executavel PIE: a base so existe em tempo de execucao, este gerador nao cobre")
        (phoff,) = struct.unpack_from("<Q", head, 32)
        phentsize, phnum = struct.unpack_from("<HH", head, 54)
        segments = []
        for i in range(phnum):
            f.seek(phoff + i * phentsize)
            p_type, flags, offset, vaddr, _paddr, filesz, memsz = struct.unpack("<IIQQQQQ", f.read(48))
            if p_type == PT_LOAD:
                segments.append(Segment(vaddr, offset, filesz, memsz, bool(flags & PF_W)))
    return segments


def read_code(executable: str, segments: list[Segment], va: int, size: int) -> bytes:
    for seg in segments:
        if seg.vaddr <= va < seg.vaddr + seg.filesz:
            with open(executable, "rb") as f:
                f.seek(seg.offset + va - seg.vaddr)
                return f.read(min(size, seg.vaddr + seg.filesz - va))
    return b""


def is_data(segments: list[Segment], va: int) -> bool:
    return any(seg.writable and seg.vaddr <= va < seg.vaddr + seg.memsz for seg in segments)


def _int32(code: bytes, at: int) -> int:
    return struct.unpack_from("<i", code, at)[0]


def table_base(code: bytes) -> int | None:
    """`mov r64, [disp32 + reg*8]` sem base (REX.W 8B, ModRM mod=00 rm=100, SIB escala 8 base=101)."""
    for i in range(len(code) - 7):
        rex, opcode, modrm, sib = code[i:i + 4]
        if rex & 0xF8 == 0x48 and opcode == 0x8B and modrm & 0xC7 == 0x04 and sib & 0xC7 == 0xC5:
            return _int32(code, i + 4) & 0xFFFFFFFF
    return None


def first_rip_load(code: bytes, va: int) -> int | None:
    """O alvo do primeiro `mov r64, [rip+disp32]` (REX.W 8B, ModRM mod=00 rm=101)."""
    for i in range(len(code) - 6):
        rex, opcode, modrm = code[i:i + 3]
        if rex & 0xF8 == 0x48 and opcode == 0x8B and modrm & 0xC7 == 0x05:
            return va + i + 7 + _int32(code, i + 3)
    return None


def this_of_call(code: bytes, va: int, target: int) -> int | None:
    """O `this` (rdi) montado logo antes de um `call target`.

    Executavel nao-PIE carrega com `mov edi, imm32`; PIE usaria `lea rdi, [rip+X]`. Vale o
    mais perto da chamada, que e o que esta no registrador quando ela acontece.
    """
    for i in range(len(code) - 4):
        if code[i] != CALL_REL32 or va + i + 5 + _int32(code, i + 1) != target:
            continue
        for j in range(i - 5, max(i - THIS_WINDOW, 0) - 1, -1):
            if code[j] == MOV_EDI_IMM32:
                return _int32(code, j + 1) & 0xFFFFFFFF
            if code[j:j + 3] == LEA_RDI_RIP and j + 7 <= i:
                return va + j + 7 + _int32(code, j + 3)
    return None


def find_globals(executable: str, segments: list[Segment], functions: dict[str, int]) -> dict[str, int]:
    def code_of(key: str) -> tuple[bytes, int]:
        va = functions.get(key)
        return (read_code(executable, segments, va, SCAN_BYTES), va) if va is not None else (b"", 0)

    found: dict[str, int | None] = {}
    code, _ = code_of("_FrameStep")
    found["GNatives"] = table_base(code)
    code, va = code_of("_MemoryFree")
    found["GMalloc"] = first_rip_load(code, va)
    code, va = code_of("_ObjectBaseInit")
    pool = functions.get("_AllocateObjectPool")
    found["GUObjectArray"] = this_of_call(code, va, pool) if pool is not None else None
    return {key: va for key, va in found.items() if va is not None and is_data(segments, va)}


def find_addresses(sym_path: str) -> dict[str, int]:
    with open(sym_path, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as m:
        (count,) = struct.unpack_from("<I", m, 0)
        strings = 4 + count * RECORD.size
        # Onde cada nome desejado mora na tabela de textos; depois os registros sao comparados
        # por numero. Guardar o texto de cada registro estoura a memoria (sao ~12 milhoes).
        offsets: dict[int, str] = {}
        for key, names in {**WANTED, **HELPERS}.items():
            for name in names:
                needle = NEWLINE + name.encode() + NEWLINE
                pos = m.find(needle, strings - 1)
                while pos != -1:
                    offsets[pos + 1 - strings] = key
                    pos = m.find(needle, pos + 1)
        found: dict[str, int] = {}
        view = memoryview(m)[4:strings]
        try:
            for addr, _line, _file, sym in RECORD.iter_unpack(view):
                hit = offsets.get(sym)
                # O menor endereco de uma funcao e a entrada dela; os outros sao linhas do meio.
                if hit and (hit not in found or addr < found[hit]):
                    found[hit] = addr
        finally:
            view.release()
    return found


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    executable = argv[0]
    sym_path = argv[1] if len(argv) > 1 else executable + ".sym"
    segments = load_segments(executable)
    base = min(seg.vaddr for seg in segments)
    functions = {key: addr + base for key, addr in find_addresses(sym_path).items()}
    data = find_globals(executable, segments, functions)
    print(f"; gerado por ue_sym_addresses.py a partir de {sym_path} (base de carga 0x{base:X})")
    print("[Addresses]")
    for key in WANTED:
        if key in functions:
            print(f"{key} = 0x{functions[key]:X}")
        else:
            print(f"; {key} = nao achado no .sym")
    for key in GLOBALS:
        if key in data:
            print(f"{key} = 0x{data[key]:X}")
        else:
            print(f"; {key} = nao achado (a instrucao que o le nao casou com o padrao)")
    return 0 if any(key in functions for key in WANTED) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
