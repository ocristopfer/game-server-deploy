"""UE4SS files for a LINUX Unreal server without symbols - runs INSIDE the CT.

Same design as ue_sym_layout: ue4ss_linux_remote receives this text from the panel and runs it
with `python3 -c`; that is why it is stdlib only and imports nothing from `gamepanel`.

A server without a .sym cannot be measured from its own executable, and one layout per engine
version is not enough either: studios tweak the engine classes. MEASURED on 4.27 servers: The Front
adds 0x18 bytes to FUObjectArray, Soulmask 62 virtuals to AGameModeBase, and Squad 44 itself
(the reference) one to AActor. What carries over from one game to another of the same version is
the CODE of each engine function (same compiler, same source) and the target's own vtables, which
the servers export in .dynsym (_ZTV*). The version's reference pack (the fork's
ue_reference_pack.py, in the release) carries that from a game WITH symbols; from it, for this
executable, we get:

- UE4SS_Signatures/*.lua for the functions and globals patternsleuth does not find in Clang code:
  from each piece of reference code (relocatable operand wildcarded), the SHORTEST prefix that
  matches once in this executable - or several times, as long as all give the same address (the
  same code copied, like FMemory::Free and operator delete);
- GMalloc.lua and ConsoleManager.lua checked AT RUNTIME: the candidates are the globals read by the
  most-called functions, and the winner is the one pointing to an object with an allocator vtable
  (or FConsoleManager's) - a byte pattern picked the console manager instead of GMalloc on Smalland;
- GUObjectHashTables.lua with 0 (absent): without symbols there is no way to find the singleton,
  and UE4SS falls back to scanning GUObjectArray;
- VTableLayout.ini: each exported vtable of this game aligned with the reference one by the code of
  each function (unique anchors; between two with the same offset, interpolate; where the offset
  changes, the code itself decides), and each name from the reference's full layout goes to its
  slot HERE;
- MemberVariableLayout.ini for FUObjectArray when this game's access histogram is shifted relative
  to the reference one (extra members before the listener lists: without this UE4SS writes its
  listener into another field and the game crashes during async loading).

Usage: ue_linux_layout.py <executable> <pack.json> [--com-sym] -> ONE JSON line
{"files": {"VTableLayout.ini": text, ...}, "report": [...]}. With --com-sym (the server ships a .sym
and ue_sym_layout already generates the ini and its four functions), only the globals and FUObjectArray.
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
# Section -> bases summed by the UE4SS reader (UE4SSProgram), or the fixed FExec size in FMalloc.
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
# FUObjectArray members that move together when the studio adds fields before the lists.
FUOBJECTARRAY_SHIFTED_FROM = 0x50
MEMBER_SPAN = 0xC0
# Opcodes with ModRM that, without REX, can still read [rip+disp32].
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
    """The ELF executable, via mmap: LOAD segments and .dynsym."""

    def __init__(self, path: str) -> None:
        self.file = open(path, "rb")  # noqa: SIM115 - kept open while the mmap lives
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


# ------------------------------------------------------------------ signatures

def wildcard_mask(code: bytes) -> list[bool]:
    """True = fixed byte; the operand of call/jmp/jcc rel32 and of [rip+disp32] becomes a wildcard."""
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
            # [rip+disp32] without a REX prefix (cmpb $0,[rip+d] and the like): the offset changes per game.
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
    """(shortest AOB that works, address) - unique, or every match giving the same address."""
    decode = decoder(match_body)
    start = max(MIN_PATTERN, minimum)
    hits: list[int] | None = None
    for n in range(start, len(tokens) + 1, 4):
        if hits is None:
            # A short prefix that is the start of a thousand functions (the push/push/sub prologue):
            # lengthen it until the list fits, instead of giving up.
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
    """(AOB, OnMatchFound) that the UE4SS scanner accepts: it rejects a pattern that STARTS with a
    wildcard, and one rejected signature brings down the whole pass (the others come out as not
    found). A global pattern starts at the operand; it gets the instruction bytes in front, taken
    from this executable (equal in every match), and MatchAddress moves by the same amount."""
    if tokens[0] is not None:
        return " ".join("??" if t is None else f"{t:02X}" for t in tokens), match_body
    lead = {bytes(image.data[h - LEAD:h]) for h in hits}
    if len(lead) != 1:
        raise ValueError("os casamentos nao tem os mesmos bytes antes do operando")
    prefix = " ".join(f"{b:02X}" for b in lead.pop())
    body = match_body.replace("MatchAddress", f"(MatchAddress + 0x{LEAD:X})")
    return prefix + " " + " ".join("??" if t is None else f"{t:02X}" for t in tokens), body


def lua_signature(aob: str, on_match: str) -> str:
    return (f"-- Generated by the panel (ue_linux_layout.py) for this executable.\nfunction Register()\n"
            f'    return "{aob}"\nend\n\nfunction OnMatchFound(MatchAddress)\n    {on_match}\nend\n')


def plausible(image: Image, name: str, address: int) -> bool:
    """A function lands in code; a global, in a writable segment. A prefix may be unique here and
    still be in the wrong place - the address it yields must at least be of the right kind."""
    if name in FUNCTION_SIGNATURES and name != "GNatives":
        return image.is_code(address)
    return any(not x and v <= address < v + n + 0x1000000 for v, _o, n, x in image.segments)


def pack_signatures(image: Image, pack: dict,
                    names: tuple[str, ...]) -> tuple[dict[str, str], dict[str, int], list[str]]:
    files, addresses, report = {}, {}, []
    for name in names:
        value = pack.get("signatures", {}).get(name)
        # A global may come with several anchors (the code of one of them changed in this game): the
        # first one that matches and yields an address of the right kind wins.
        found, entry = None, None
        entries = value if isinstance(value, list) else [value] if value else []
        for entry in entries:
            found = resolve(image, parse_masked(entry["code"]), entry["match"], entry.get("min", 0))
            if found and plausible(image, name, found[1]):
                break
            found = None
        if not found and name in GLOBAL_SIGNATURES:
            # The piece that is unique IN the reference may have changed here already (Hypercharge's
            # GUObjectArray matches with 12 bytes, which are not unique on Mordhau): a shorter prefix counts if
            # it is unique here AND yields a global in a writable segment - which rejects a match in the wrong place.
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


# ------------------------------------------------------------------ GMalloc and console, checked at runtime

def idiom_globals(image: Image) -> collections.Counter:
    """Globals of the inline idiom mov r,[G]; test r,r; jne; call create; mov r,[G] - by frequency."""
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
    """8-byte globals read at the start of the function (mov r64,[rip+d] and cmpq $i8,[rip+d])."""
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
    return f"""-- Generated by the panel (ue_linux_layout.py) for this executable: {what} without symbols. Each
-- candidate is a global; the first one pointing to an object with one of the vtables below wins.
local Candidates = {{ {cands} }}
local VTables = {{ {vts} }}

local function ReadPointer(Address)
    -- DerefToInt32 returns nil when it reads 0 (and when the address is not readable): both count as 0.
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
        -- Only what looks like an aligned user-space pointer: a counter or flag is not read as an object.
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
    slots: list[int] = []
    at = address_point
    while True:
        value = image.qword(at)
        if value is None or not image.is_code(value):
            return slots
        slots.append(value)
        at += 8


def slot_mapping(reference: list[str], target: list[str]):
    """ref slot -> target slot: anchors by unique code; between two with the same offset, interpolate;
    where the offset changes, only a unique code match within the window counts."""
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
    """Offset (multiple of 8) that best maps the reference accesses onto this game's, counting only
    the region of the listener lists. 0 when nothing is convincing."""
    ref = {o: c for o, c in reference.items() if o >= FUOBJECTARRAY_SHIFTED_FROM}
    # Normalize only within the compared region: ObjObjects (+0x10) is read thousands of times and
    # would flatten the rest.
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
        "-- Generated by the panel: 0 = absent, and UE4SS uses the GUObjectArray scan.\nreturn 0\n")
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
