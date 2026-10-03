"""Gera o UE4SS_Addresses.ini de um servidor Unreal LINUX a partir do .sym que vem com ele.

Servidor Unreal de Linux costuma vir SEM simbolos no executavel (o do Dragonwilds e assim),
mas com um `<Executavel>.sym` ao lado: e o arquivo que o proprio Unreal usa para montar o
relatorio de crash, e tem o nome e o endereco de cada funcao. O port Linux do UE4SS aceita
esses enderecos por um UE4SS_Addresses.ini; sem eles, ele procura por padroes e, num motor
diferente do Palworld, acha errado ou nao acha.

Formato do .sym (lido do Dragonwilds, UE 5.6.1): uint32 com o numero de registros, registros
de 20 bytes {uint64 endereco, uint32 linha, uint32 arquivo, uint32 nome} e, logo depois, a
tabela de textos separados por QUEBRA DE LINHA (nao por \\0); arquivo e nome sao deslocamentos
nela. O endereco e relativo a base de carga do executavel: no Dragonwilds, base 0x200000 -
somado a ela, cada endereco cai num prologo de funcao (conferido byte a byte).

Uso (dentro do CT, onde o .sym tem 300 MB e nao vale a pena copiar):
    python3 ue-sym-addresses.py <executavel> [<executavel>.sym] > UE4SS_Addresses.ini
So stdlib; varre o arquivo por mmap, sem montar texto para cada um dos milhoes de registros.
"""
from __future__ import annotations

import mmap
import struct
import sys

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
NEWLINE = bytes([10])
RECORD = struct.Struct("<QIII")
ELF_EXEC = 2
PT_LOAD = 1


def load_base(executable: str) -> int:
    """A base de carga: o menor endereco dos segmentos LOAD (executavel nao-PIE)."""
    with open(executable, "rb") as f:
        head = f.read(64)
        if head[:4] != b"\x7fELF":
            raise SystemExit(f"{executable} nao e um ELF")
        (e_type,) = struct.unpack_from("<H", head, 16)
        if e_type != ELF_EXEC:
            raise SystemExit("executavel PIE: a base so existe em tempo de execucao, este gerador nao cobre")
        (phoff,) = struct.unpack_from("<Q", head, 32)
        phentsize, phnum = struct.unpack_from("<HH", head, 54)
        bases = []
        for i in range(phnum):
            f.seek(phoff + i * phentsize)
            p_type, _flags, _offset, p_vaddr = struct.unpack("<IIQQ", f.read(24))
            if p_type == PT_LOAD:
                bases.append(p_vaddr)
    return min(bases)


def find_addresses(sym_path: str) -> dict[str, int]:
    with open(sym_path, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as m:
        (count,) = struct.unpack_from("<I", m, 0)
        strings = 4 + count * RECORD.size
        # Onde cada nome desejado mora na tabela de textos; depois os registros sao comparados
        # por numero. Guardar o texto de cada registro estoura a memoria (sao ~12 milhoes).
        offsets: dict[int, str] = {}
        for key, names in WANTED.items():
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
                key = offsets.get(sym)
                # O menor endereco de uma funcao e a entrada dela; os outros sao linhas do meio.
                if key and (key not in found or addr < found[key]):
                    found[key] = addr
        finally:
            view.release()
    return found


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    executable = argv[0]
    sym_path = argv[1] if len(argv) > 1 else executable + ".sym"
    base = load_base(executable)
    found = find_addresses(sym_path)
    print(f"; gerado por tools/ue-sym-addresses.py a partir de {sym_path} (base de carga 0x{base:X})")
    print("[Addresses]")
    for key in WANTED:
        if key in found:
            print(f"{key} = 0x{found[key] + base:X}")
        else:
            print(f"; {key} = nao achado no .sym")
    return 0 if found else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
