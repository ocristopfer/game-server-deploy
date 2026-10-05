"""Arquivos do UE4SS de um servidor Unreal LINUX sem simbolo - roda DENTRO do CT.

Mesmo desenho do ue_sym_layout: o ue4ss_linux_remote recebe este texto do painel e o executa com
`python3 -c`; por isso e so stdlib e nao importa nada do `gamepanel`.

Um servidor sem .sym nao da para medir pelo proprio executavel, e um layout por versao do motor
tambem nao basta: os estudios mexem nas classes do motor. MEDIDO em servidores 4.27: o The Front
acrescenta 0x18 bytes no FUObjectArray, o Soulmask 62 virtuais no AGameModeBase, e o proprio Squad 44
(a referencia) uma na AActor. O que passa de um jogo para outro da mesma versao e o CODIGO de cada
funcao do motor (mesmo compilador, mesmo fonte) e as vtables do proprio alvo, que os servidores
exportam no .dynsym (_ZTV*). O pacote de referencia da versao (ue_reference_pack.py do fork, no
release) traz isso de um jogo COM simbolos; daqui sai, para este executavel:

- UE4SS_Signatures/*.lua das funcoes e globais que o patternsleuth nao acha no codigo do Clang:
  de cada trecho de codigo da referencia (operando relocavel coringa), o MENOR prefixo que casa
  uma vez neste executavel - ou varias vezes, desde que todas deem o mesmo endereco (o mesmo
  codigo copiado, como o FMemory::Free e o operator delete);
- GMalloc.lua e ConsoleManager.lua conferidos NA HORA: os candidatos sao os globais que as funcoes
  mais chamadas leem, e vale o que aponta para um objeto com a vtable de um alocador (ou do
  FConsoleManager) - um padrao de bytes pegou o console manager no lugar do GMalloc no Smalland;
- GUObjectHashTables.lua com 0 (ausente): sem simbolo nao ha como achar o singleton, e o UE4SS
  cai na varredura do GUObjectArray;
- VTableLayout.ini: cada vtable exportada deste jogo alinhada com a da referencia pelo codigo de
  cada funcao (ancoras unicas; entre duas de mesmo deslocamento, interpola; onde o deslocamento
  muda, o proprio codigo decide), e cada nome do layout completo da referencia vai para a posicao
  dele AQUI;
- MemberVariableLayout.ini do FUObjectArray quando o histograma de acessos deste jogo esta
  deslocado em relacao ao da referencia (membros a mais antes das listas de listeners: sem isso o
  UE4SS grava o listener dele em outro campo e o jogo cai no carregamento assincrono).

Uso: ue_linux_layout.py <executavel> <pack.json> [--com-sym] -> UMA linha JSON
{"files": {"VTableLayout.ini": texto, ...}, "report": [...]}. Com --com-sym (o servidor traz .sym e
o ue_sym_layout ja gera o ini e as quatro funcoes dele), so os globais e o FUObjectArray.
"""
from __future__ import annotations

import collections
import json
import mmap
import re
import struct
import sys

PT_LOAD = 1
PF_X = 1
SHT_DYNSYM = 11
SIGNATURES_DIR = "UE4SS_Signatures"
VTABLE_INI = "VTableLayout.ini"
MEMBER_INI = "MemberVariableLayout.ini"
GENERATED_MARK = "; Gerado pelo painel"
DTOR = "__vecDelDtor"
FINGERPRINT = 24
MIN_PATTERN = 12
MAX_HITS = 4096
FUNCTION_SIGNATURES = ("FName_ToString", "FName_Constructor", "StaticConstructObject", "GNatives")
GLOBAL_SIGNATURES = ("GUObjectArray", "ConsoleManager")
# Secao -> bases somadas pelo leitor do UE4SS (UE4SSProgram), ou o tamanho fixo do FExec no FMalloc.
OBJECT_CHAIN = ("UObjectBase", "UObjectBaseUtility", "UObject")
SECTION_BASES: dict[str, tuple[str, ...] | int] = {
    "UObjectBase": (), "UObjectBaseUtility": ("UObjectBase",), "UObject": ("UObjectBase", "UObjectBaseUtility"),
    "UField": OBJECT_CHAIN, "UEngine": OBJECT_CHAIN, "UScriptStruct::ICppStructOps": (), "FField": (),
    "FProperty": ("FField",), "FNumericProperty": ("FField", "FProperty"),
    "FMulticastDelegateProperty": ("FField", "FProperty"), "FObjectPropertyBase": ("FField", "FProperty"),
    "UStruct": (*OBJECT_CHAIN, "UField"), "UClass": (*OBJECT_CHAIN, "UField", "UStruct"),
    "UGameViewportClient": OBJECT_CHAIN, "FOutputDevice": (), "FMalloc": 1, "AActor": OBJECT_CHAIN,
    "AGameModeBase": (*OBJECT_CHAIN, "AActor"), "AGameMode": (*OBJECT_CHAIN, "AActor", "AGameModeBase"),
    "UPlayer": OBJECT_CHAIN, "ULocalPlayer": (*OBJECT_CHAIN, "UPlayer"), "UDataTable": OBJECT_CHAIN,
}
# Membros do FUObjectArray que andam juntos quando o estudio acrescenta campos antes das listas.
FUOBJECTARRAY_SHIFTED_FROM = 0x50
MEMBER_SPAN = 0xC0
# Opcodes com ModRM que, sem REX, ainda podem ler [rip+disp32].
RIP_OPCODES = frozenset((0x80, 0x81, 0x83, 0xC6, 0xC7, 0x8B, 0x89, 0x8D, 0x3B, 0x39, 0x3A, 0x38, 0x84, 0x85,
                         0xF6, 0xF7, 0xFF, 0x03, 0x01, 0x2B, 0x29, 0x33, 0x31, 0x0B, 0x09, 0x23, 0x21))
IDIOM = re.compile(rb"([\x48\x4c])\x8b([\x05\x0d\x15\x1d\x25\x2d\x35\x3d])(....)\1\x85.\x75.\xe8....\1\x8b\2(....)",
                   re.DOTALL)
CALL = re.compile(rb"\xe8(....)", re.DOTALL)
MATCH_FORMS = (
    (re.compile(r"return MatchAddress$"), lambda read, at, _m: at),
    (re.compile(r"return DerefToInt32\(MatchAddress \+ 0x([0-9A-F]+)\)$"),
     lambda read, at, m: read(at + int(m.group(1), 16))),
    (re.compile(r"return DerefToInt32\(MatchAddress\) - 0x([0-9A-F]+)$"),
     lambda read, at, m: read(at) - int(m.group(1), 16)),
    (re.compile(r"return MatchAddress \+ 0x([0-9A-F]+) \+ DerefToInt32\(MatchAddress\) - 0x([0-9A-F]+)$"),
     lambda read, at, m: at + int(m.group(1), 16) + read(at) - int(m.group(2), 16)),
)


class Image:
    """O executavel ELF, por mmap: segmentos LOAD e o .dynsym."""

    def __init__(self, path: str) -> None:
        self.file = open(path, "rb")  # noqa: SIM115 - aberto enquanto o mmap viver
        self.data = mmap.mmap(self.file.fileno(), 0, access=mmap.ACCESS_READ)
        if self.data[:4] != b"\x7fELF":
            raise ValueError(f"{path} nao e um ELF")
        (phoff,) = struct.unpack_from("<Q", self.data, 32)
        phentsize, phnum = struct.unpack_from("<HH", self.data, 54)
        self.segments = []
        for i in range(phnum):
            p_type, flags, offset, vaddr, _pa, filesz, _memsz = struct.unpack_from(
                "<IIQQQQQ", self.data, phoff + i * phentsize)
            if p_type == PT_LOAD:
                self.segments.append((vaddr, offset, filesz, bool(flags & PF_X)))

    def va_of(self, file_offset: int) -> int | None:
        for vaddr, offset, filesz, _x in self.segments:
            if offset <= file_offset < offset + filesz:
                return vaddr + file_offset - offset
        return None

    def read(self, va: int, size: int) -> bytes:
        for vaddr, offset, filesz, _x in self.segments:
            if vaddr <= va < vaddr + filesz:
                return bytes(self.data[offset + va - vaddr:offset + min(va - vaddr + size, filesz)])
        return b""

    def int32(self, va: int) -> int:
        chunk = self.read(va, 4)
        return struct.unpack("<i", chunk)[0] if len(chunk) == 4 else 0

    def qword(self, va: int) -> int | None:
        chunk = self.read(va, 8)
        return struct.unpack("<Q", chunk)[0] if len(chunk) == 8 else None

    def is_code(self, va: int) -> bool:
        return any(x and v <= va < v + n for v, _o, n, x in self.segments)

    def code_views(self):
        for vaddr, offset, filesz, executable in self.segments:
            if executable:
                yield vaddr, self.data[offset:offset + filesz]

    def dynsym(self) -> dict[str, int]:
        d = self.data
        (shoff,) = struct.unpack_from("<Q", d, 0x28)
        shentsize, shnum, _shstrndx = struct.unpack_from("<HHH", d, 0x3A)
        secs = [struct.unpack_from("<IIQQQQIIQQ", d, shoff + i * shentsize) for i in range(shnum)]
        out: dict[str, int] = {}
        for sec in secs:
            if sec[1] != SHT_DYNSYM:
                continue
            strtab = secs[sec[6]]
            for i in range(sec[5] // 24):
                st_name, _info, _other, _shndx, value, _size = struct.unpack_from("<IBBHQQ", d, sec[4] + i * 24)
                end = d.find(b"\0", strtab[4] + st_name)
                if value:
                    out[d[strtab[4] + st_name:end].decode("ascii", "replace")] = value
        return out


# ------------------------------------------------------------------ assinaturas

def wildcard_mask(code: bytes) -> list[bool]:
    """True = byte fixo; operando de call/jmp/jcc rel32 e de [rip+disp32] vira coringa."""
    keep = [True] * len(code)
    i = 0
    while i < len(code):
        b = code[i]
        if b in (0xE8, 0xE9) and i + 5 <= len(code):
            keep[i + 1:i + 5] = [False] * 4
            i += 5
        elif b & 0xF0 == 0x40 and i + 7 <= len(code) and code[i + 2] & 0xC7 == 0x05:
            keep[i + 3:i + 7] = [False] * 4
            i += 7
        elif b == 0x0F and i + 6 <= len(code) and 0x80 <= code[i + 1] <= 0x8F:
            keep[i + 2:i + 6] = [False] * 4
            i += 6
        elif b in RIP_OPCODES and i + 6 <= len(code) and code[i + 1] & 0xC7 == 0x05:
            # [rip+disp32] sem prefixo REX (cmpb $0,[rip+d] e afins): o deslocamento muda por jogo.
            keep[i + 2:i + 6] = [False] * 4
            i += 6
        else:
            i += 1
    return keep


def masked(code: bytes) -> str:
    keep = wildcard_mask(code)
    return " ".join(f"{code[k]:02X}" if keep[k] else "??" for k in range(len(code)))


def parse_masked(text: str) -> list[int | None]:
    return [None if t == "??" else int(t, 16) for t in text.split()]


def pattern(tokens: list[int | None]) -> bytes:
    return b"".join(b"." if t is None else re.escape(bytes([t])) for t in tokens)


def decoder(match_body: str):
    for form, fn in MATCH_FORMS:
        found = form.fullmatch(match_body)
        if found:
            return lambda image, at, f=fn, m=found: f(image.int32, at, m)
    raise ValueError(f"forma de OnMatchFound desconhecida: {match_body!r}")


Resolved = tuple[tuple[str, str], int]


def resolve(image: Image, tokens: list[int | None], match_body: str, minimum: int) -> Resolved | None:
    """(menor AOB que serve, endereco) - unico, ou todos os casamentos dando o mesmo endereco."""
    decode = decoder(match_body)
    start = max(MIN_PATTERN, minimum)
    hits: list[int] | None = None
    for n in range(start, len(tokens) + 1, 4):
        if hits is None:
            # Prefixo curto que e o comeco de mil funcoes (o prologo push/push/sub): alonga ate a
            # lista caber, em vez de desistir.
            found = []
            for m in re.finditer(pattern(tokens[:n]), image.data, re.DOTALL):
                found.append(m.start())
                if len(found) > MAX_HITS:
                    break
            if len(found) > MAX_HITS:
                continue
            hits = found
        else:
            keep = [(k, t) for k, t in enumerate(tokens[:n]) if t is not None]
            hits = [h for h in hits if all(image.data[h + k] == t for k, t in keep)]
        if not hits:
            return None
        vas = [image.va_of(h) for h in hits]
        if None in vas:
            continue
        values = {decode(image, va) for va in vas}
        if len(values) == 1:
            return anchored(image, hits, tokens[:n], match_body), values.pop()
    return None


LEAD = 3


def anchored(image: Image, hits: list[int], tokens: list[int | None], match_body: str) -> tuple[str, str]:
    """(AOB, OnMatchFound) que o scanner do UE4SS aceita: ele recusa padrao que COMECA com coringa,
    e uma assinatura recusada derruba a passada inteira (as outras saem como nao achadas). Um padrao
    de global comeca no operando; ganha na frente os bytes da instrucao, tirados deste executavel
    (iguais em todos os casamentos), e o MatchAddress anda o mesmo tanto."""
    if tokens[0] is not None:
        return " ".join("??" if t is None else f"{t:02X}" for t in tokens), match_body
    lead = {bytes(image.data[h - LEAD:h]) for h in hits}
    if len(lead) != 1:
        raise ValueError("os casamentos nao tem os mesmos bytes antes do operando")
    prefix = " ".join(f"{b:02X}" for b in lead.pop())
    body = match_body.replace("MatchAddress", f"(MatchAddress + 0x{LEAD:X})")
    return prefix + " " + " ".join("??" if t is None else f"{t:02X}" for t in tokens), body


def lua_signature(aob: str, on_match: str) -> str:
    return (f"-- Gerado pelo painel (ue_linux_layout.py) para este executavel.\nfunction Register()\n"
            f'    return "{aob}"\nend\n\nfunction OnMatchFound(MatchAddress)\n    {on_match}\nend\n')


def plausible(image: Image, name: str, address: int) -> bool:
    """Funcao cai em codigo; global, num segmento gravavel. Um prefixo pode ser unico aqui e mesmo
    assim estar no lugar errado - o endereco que ele da tem de ao menos ser do tipo certo."""
    if name in FUNCTION_SIGNATURES and name != "GNatives":
        return image.is_code(address)
    return any(not x and v <= address < v + n + 0x1000000 for v, _o, n, x in image.segments)


def pack_signatures(image: Image, pack: dict,
                    names: tuple[str, ...]) -> tuple[dict[str, str], dict[str, int], list[str]]:
    files, addresses, report = {}, {}, []
    for name in names:
        value = pack.get("signatures", {}).get(name)
        # Um global pode vir com varias ancoras (o codigo de uma delas mudou neste jogo): vale a
        # primeira que casa e da um endereco do tipo certo.
        found, entry = None, None
        entries = value if isinstance(value, list) else [value] if value else []
        for entry in entries:
            found = resolve(image, parse_masked(entry["code"]), entry["match"], entry.get("min", 0))
            if found and plausible(image, name, found[1]):
                break
            found = None
        if not found and name in GLOBAL_SIGNATURES:
            # O trecho unico NA referencia pode ja ter mudado aqui (o GUObjectArray do Hypercharge casa
            # com 12 bytes, que no Mordhau nao sao unicos): um prefixo mais curto vale se for unico aqui
            # E der um global num segmento gravavel - o que recusa o casamento no lugar errado.
            for entry in entries:
                found = resolve(image, parse_masked(entry["code"]), entry["match"], 0)
                if found and plausible(image, name, found[1]):
                    break
                found = None
        if found and entry:
            (aob, body), address = found
            files[f"{SIGNATURES_DIR}/{name}.lua"] = lua_signature(aob, body)
            addresses[name] = address
        report.append(f"{name}: {'ok' if found else 'nao achado'}")
    return files, addresses, report


# ------------------------------------------------------------------ GMalloc e console, conferidos na hora

def idiom_globals(image: Image) -> collections.Counter:
    """Globais do idioma inline mov r,[G]; test r,r; jne; call cria; mov r,[G] - por frequencia."""
    tally: collections.Counter = collections.Counter()
    for vaddr, view in image.code_views():
        for m in IDIOM.finditer(view):
            a = vaddr + m.start() + 7 + struct.unpack("<i", m.group(3))[0]
            if a == vaddr + m.end() + struct.unpack("<i", m.group(4))[0]:
                tally[a] += 1
    return tally


def most_called(image: Image, count: int = 4) -> list[int]:
    tally: collections.Counter = collections.Counter()
    for vaddr, view in image.code_views():
        end = vaddr + len(view)
        for m in CALL.finditer(view):
            target = vaddr + m.end() + struct.unpack("<i", m.group(1))[0]
            if vaddr <= target < end:
                tally[target] += 1
    return [a for a, _n in tally.most_common(count)]


def globals_read(image: Image, va: int, size: int = 96) -> list[int]:
    """Globais de 8 bytes lidos no comeco da funcao (mov r64,[rip+d] e cmpq $i8,[rip+d])."""
    code = image.read(va, size)
    found = []
    for i in range(len(code) - 8):
        if code[i] in (0x48, 0x4C) and code[i + 1] == 0x8B and code[i + 2] & 0xC7 == 0x05:
            found.append(va + i + 7 + struct.unpack_from("<i", code, i + 3)[0])
        elif code[i] == 0x48 and code[i + 1] == 0x83 and code[i + 2] == 0x3D:
            found.append(va + i + 8 + struct.unpack_from("<i", code, i + 3)[0])
    return found


def runtime_lua(candidates: list[int], vtables: list[int], what: str) -> str:
    cands = ", ".join(f"0x{g:X}" for g in candidates)
    vts = ", ".join(f"[0x{v:X}] = true" for v in sorted(vtables))
    return f"""-- Gerado pelo painel (ue_linux_layout.py) para este executavel: {what} sem simbolo. Cada
-- candidato e um global; vale o primeiro que aponta para um objeto com uma das vtables abaixo.
local Candidates = {{ {cands} }}
local VTables = {{ {vts} }}

local function ReadPointer(Address)
    -- DerefToInt32 devolve nil quando le 0 (e quando o endereco nao e legivel): os dois contam como 0.
    local Low = (DerefToInt32(Address) or 0) & 0xFFFFFFFF
    local High = (DerefToInt32(Address + 4) or 0) & 0xFFFFFFFF
    return (High << 32) | Low
end

function Register()
    return "48 8B 3D ?? ?? ?? ??"
end

function OnMatchFound(MatchAddress)
    for _, Global in ipairs(Candidates) do
        local Object = ReadPointer(Global)
        -- So o que parece ponteiro de usuario alinhado: um contador ou flag nao e lido como objeto.
        if Object > 0x10000 and Object < 0x7FFFFFFFFFFF and Object % 8 == 0 and VTables[ReadPointer(Object)] then
            return Global
        end
    end
    return nil
end
"""


def runtime_globals(image: Image, exported: dict[str, int], need_console: bool) -> tuple[dict[str, str], list[str]]:
    files, report = {}, []
    idiom = [g for g, _n in idiom_globals(image).most_common(4)]
    console_vt = exported.get("_ZTV15FConsoleManager")
    console = idiom[0] if idiom else None
    malloc_vts = [v + 16 for n, v in exported.items() if re.match(r"_ZTV\d+FMalloc", n) and "Crash" not in n]
    candidates: list[int] = []
    for function in most_called(image):
        for g in globals_read(image, function):
            if g not in candidates and g != console:
                candidates.append(g)
    candidates += [g for g in idiom[1:] if g not in candidates]
    if candidates and malloc_vts:
        files[f"{SIGNATURES_DIR}/GMalloc.lua"] = runtime_lua(candidates, malloc_vts, "GMalloc")
    report.append(f"GMalloc: {len(candidates)} candidato(s), {len(malloc_vts)} vtable(s) de alocador")
    if need_console and idiom and console_vt:
        files[f"{SIGNATURES_DIR}/ConsoleManager.lua"] = runtime_lua(idiom[:3], [console_vt + 16], "console manager")
        report.append("ConsoleManager: conferido na hora pela vtable do FConsoleManager")
    return files, report


# ------------------------------------------------------------------ VTableLayout.ini

def mangled_vtable(cls: str) -> str:
    parts = cls.split("::")
    return f"_ZTV{len(cls)}{cls}" if len(parts) == 1 else "_ZTVN" + "".join(f"{len(p)}{p}" for p in parts) + "E"


def vtable_slots(image: Image, address_point: int) -> list[int]:
    slots, at = [], address_point
    while True:
        value = image.qword(at)
        if value is None or not image.is_code(value):
            return slots
        slots.append(value)
        at += 8


def slot_mapping(reference: list[str], target: list[str]):
    """ref slot -> alvo slot: ancoras por codigo unico; entre duas de mesmo deslocamento, interpola;
    onde o deslocamento muda, so um casamento unico de codigo dentro da janela vale."""
    tcount = collections.defaultdict(list)
    for j, s in enumerate(target):
        tcount[s].append(j)
    rcount = collections.Counter(reference)
    anchors, last = {}, -1
    for i, s in enumerate(reference):
        if rcount[s] == 1 and len(tcount.get(s, [])) == 1 and tcount[s][0] > last:
            anchors[i] = last = tcount[s][0]
    keys = sorted(anchors)

    def resolve_slot(i: int) -> int | None:
        if i in anchors:
            return anchors[i]
        lo = max((k for k in keys if k < i), default=None)
        hi = min((k for k in keys if k > i), default=None)
        if lo is not None and hi is not None and anchors[lo] - lo == anchors[hi] - hi:
            return i + anchors[lo] - lo
        a = anchors[lo] if lo is not None else -1
        b = anchors[hi] if hi is not None else len(target)
        window = [j for j in range(a + 1, b) if i < len(reference) and target[j] == reference[i]]
        if len(window) == 1:
            return window[0]
        if hi is None and lo is not None:
            return i + anchors[lo] - lo
        return None
    return resolve_slot, len(anchors)


def vtable_ini(image: Image, exported: dict[str, int], pack: dict) -> tuple[str, list[str]]:
    sizes: dict[str, int] = {}
    out = [f"{GENERATED_MARK} (ue_linux_layout.py): cada nome do layout de {pack.get('reference', '?')} na posicao",
           "; dele neste executavel, achada pelo codigo de cada funcao das vtables exportadas.", ""]
    report = []
    for section, bases in SECTION_BASES.items():
        ref = pack.get("sections", {}).get(section)
        if not ref:
            continue
        base = bases if isinstance(bases, int) else sum(sizes.get(b, 0) for b in bases)
        vt = exported.get(mangled_vtable(ref["cls"]))
        if not vt:
            report.append(f"{section}: {ref['cls']} sem vtable exportada - fica o layout embutido")
            continue
        target = [masked(image.read(f, FINGERPRINT)) for f in vtable_slots(image, vt + 16)]
        resolve_slot, anchors = slot_mapping(ref["fingerprints"], target)
        placed, missing = {}, []
        for name, slot in ref["slots"].items():
            j = resolve_slot(slot)
            if j is None or j <= base:
                missing.append(name)
            else:
                placed[j - base] = name
        size = max(placed, default=0)
        sizes[section] = size
        out += [f"[{section}]", DTOR] + [placed.get(k, f"__linux_slot_{k + base}") for k in range(1, size + 1)] + [""]
        report.append(f"{section}: {len(placed)} de {len(ref['slots'])} ({anchors} ancoras)"
                      + (f", sem posicao: {', '.join(missing[:4])}" if missing else ""))
    return "\n".join(out) + "\n", report


# ------------------------------------------------------------------ FUObjectArray

def member_counts(image: Image, address: int) -> dict[int, int]:
    counts: collections.Counter = collections.Counter()
    for vaddr, view in image.code_views():
        for m in re.finditer(rb"[\x05\x0d\x15\x1d\x25\x2d\x35\x3d]", view):
            i = m.start() + 1
            if i + 4 > len(view):
                continue
            (d,) = struct.unpack_from("<i", view, i)
            for tail in (0, 1, 4):
                a = vaddr + i + 4 + tail + d
                if address <= a < address + MEMBER_SPAN:
                    counts[a - address] += 1
                    break
    return dict(counts)


def fuobjectarray_shift(reference: dict[int, int], target: dict[int, int]) -> int:
    """Deslocamento (multiplo de 8) que melhor leva os acessos da referencia aos deste jogo, contando
    so a regiao das listas de listeners. 0 quando nada convence."""
    ref = {o: c for o, c in reference.items() if o >= FUOBJECTARRAY_SHIFTED_FROM}
    # Normaliza so na regiao comparada: o ObjObjects (+0x10) e lido milhares de vezes e achataria o resto.
    near = [c for o, c in target.items() if o >= FUOBJECTARRAY_SHIFTED_FROM - 0x20]
    if not ref or not near:
        return 0
    rmax, tmax = max(ref.values()), max(near)

    def score(d: int) -> float:
        return sum(min(c / rmax, target.get(o + d, 0) / tmax) for o, c in ref.items())
    best = max(range(-0x20, 0x61, 8), key=score)
    return best if best and score(best) > score(0) + 0.2 else 0


def member_ini(image: Image, pack: dict, guobjectarray: int | None) -> tuple[str, list[str]]:
    info = pack.get("fuobjectarray") or {}
    if guobjectarray is None or not info.get("members"):
        return "", ["FUObjectArray: sem o endereco do GUObjectArray, fica o layout embutido"]
    reference = {int(k, 16): v for k, v in info.get("access_counts", {}).items()}
    shift = fuobjectarray_shift(reference, member_counts(image, guobjectarray))
    if not shift:
        return "", ["FUObjectArray: igual ao da referencia"]
    moved = {n: o + shift for n, o in info["members"].items() if o >= FUOBJECTARRAY_SHIFTED_FROM}
    lines = [f"{GENERATED_MARK} (ue_linux_layout.py): o FUObjectArray deste jogo tem {shift:+#x} bytes",
             "; antes das listas de listeners (medido pelo historico de acessos do codigo).", "[FUObjectArray]"]
    lines += [f"{n} = {o}" for n, o in sorted(moved.items(), key=lambda kv: kv[1])]
    return "\n".join(lines) + "\n", [f"FUObjectArray: {shift:+#x} bytes a partir de {FUOBJECTARRAY_SHIFTED_FROM:#x}"]


def main(argv: list[str]) -> int:
    with_sym = "--com-sym" in argv
    executable, pack_path = [a for a in argv if a != "--com-sym"]
    image = Image(executable)
    with open(pack_path, encoding="utf-8") as f:
        pack = json.load(f)
    exported = image.dynsym()
    names = GLOBAL_SIGNATURES if with_sym else FUNCTION_SIGNATURES + GLOBAL_SIGNATURES
    files, addresses, report = pack_signatures(image, pack, names)
    runtime, runtime_report = runtime_globals(image, exported, "ConsoleManager" not in addresses)
    files.update(runtime)
    report += runtime_report
    files[f"{SIGNATURES_DIR}/GUObjectHashTables.lua"] = (
        "-- Gerado pelo painel: 0 = ausente, e o UE4SS usa a varredura do GUObjectArray.\nreturn 0\n")
    if not with_sym:
        missing = [n for n in ("FName_ToString", "FName_Constructor", "GNatives") if n not in addresses]
        if missing:
            raise SystemExit(f"o pacote da versao {pack.get('version')} nao serve a este executavel "
                             f"(sem: {', '.join(missing)}): nada foi instalado")
        ini, ini_report = vtable_ini(image, exported, pack)
        files[VTABLE_INI] = ini
        report += ini_report
    members, member_report = member_ini(image, pack, addresses.get("GUObjectArray"))
    if members:
        files[MEMBER_INI] = members
    report += member_report
    print(json.dumps({"files": files, "report": report}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
