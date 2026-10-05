"""UE4SS files for a LINUX Unreal server taken from its .sym - runs INSIDE the CT.

Same design as the remote installers: ue4ss_linux_remote receives this text from the panel and
runs it with `python3 -c`, which is why it is stdlib only and imports nothing from `gamepanel`.

The official UE4SS (our Linux fork, ocristopfer/RE-UE4SS) already has the layout of each ENGINE
version (5.1, 5.6) built in, generated from Epic's code. That is enough for an unmodified engine
(Palworld). A studio may tweak the engine classes - Dragonwilds adds virtuals to AActor -, and
then only what is measured on the executable itself holds. A server that ships the `.sym` (the
Unreal crash file, with the name and address of every function) can be measured:

- VTableLayout.ini: each class's vtable is found in the executable data (without RTTI it is
  {0, 0, complete destructor, deleting destructor, ...}), each slot gets its name from the .sym and
  each entry of the version's official template is matched by name and signature. MSVC groups
  overloads in reverse order and Itanium does not, so no fixed offset works - measured: on
  Dragonwilds BeginPlay landed on RemoveTickPrerequisiteComponent.
- UE4SS_Signatures/*.lua: patternsleuth only knows the code MSVC generates; FName::ToString, the
  FName constructor, StaticConstructObject and GNatives come from here, as an AOB unique in the
  executable, with the call/jmp/rip-relative operand wildcarded (it survives code that only moved).
  GNatives comes from the FFrame::Step instruction that reads the table.

Two executable traps, both seen on Dragonwilds: the linker merges identical functions (ICF), so
the .sym gives an empty function the name of a destructor of some unrelated class - only a name
from the section's own hierarchy counts; and UObject's complete destructor shows up as
`UObjectBase::~UObjectBase()` - the vtable is found by EITHER of the two destructor slots.

Usage: ue_sym_layout.py <executable> <VTableLayout_X_Y_Template.ini> -> ONE JSON line
{"files": {"VTableLayout.ini": text, "UE4SS_Signatures/FName_ToString.lua": text, ...},
 "report": [...]}. The executable must be non-PIE (the .sym address is added to the load base).
"""
from __future__ import annotations

import json
import mmap
import re
import struct
import sys
from typing import NamedTuple

RECORD = struct.Struct("<QIII")
PT_LOAD = 1
PF_X = 1
DTOR = "__vecDelDtor"
MAX_SLOTS = 1500
OBJECT_CHAIN = ("UObjectBase", "UObjectBaseUtility", "UObject")
VTABLE_INI = "VTableLayout.ini"
SIGNATURES_DIR = "UE4SS_Signatures"
# AOB cap: too long and it becomes the code itself, which changes on every game update.
MAX_AOB = 96
STEP_BYTES = 512

# Ini section -> (classes whose vtable contains it, the first one found wins; bases, as the UE4SS
# reader sums them). Mirrors UE4SSProgram; FMalloc has the reader's fixed "fexec_size".
SECTIONS: dict[str, tuple[tuple[str, ...], tuple[str, ...] | int]] = {
    "UObjectBase": (("UObject",), ()),
    "UObjectBaseUtility": (("UObject",), ("UObjectBase",)),
    "UObject": (("UObject",), ("UObjectBase", "UObjectBaseUtility")),
    "UField": (("UField",), OBJECT_CHAIN),
    "UEngine": (("UGameEngine", "UEngine"), OBJECT_CHAIN),
    "UScriptStruct::ICppStructOps": (("UScriptStruct::ICppStructOps",), ()),
    "FField": (("FField",), ()),
    "FProperty": (("FProperty",), ("FField",)),
    "FNumericProperty": (("FNumericProperty",), ("FField", "FProperty")),
    "FMulticastDelegateProperty": (("FMulticastDelegateProperty",), ("FField", "FProperty")),
    "FObjectPropertyBase": (("FObjectPropertyBase",), ("FField", "FProperty")),
    "UStruct": (("UStruct",), (*OBJECT_CHAIN, "UField")),
    "UClass": (("UClass",), (*OBJECT_CHAIN, "UField", "UStruct")),
    "UGameViewportClient": (("UGameViewportClient",), OBJECT_CHAIN),
    "FOutputDevice": (("FOutputDevice", "FOutputDeviceRedirector"), ()),
    "FMalloc": (("FMalloc", "FMallocBinned2", "FMallocBinned3", "FMallocAnsi"), 1),
    "AActor": (("AActor",), OBJECT_CHAIN),
    "AGameModeBase": (("AGameModeBase",), (*OBJECT_CHAIN, "AActor")),
    "AGameMode": (("AGameMode",), (*OBJECT_CHAIN, "AActor", "AGameModeBase")),
    "UPlayer": (("UPlayer",), OBJECT_CHAIN),
    "ULocalPlayer": (("ULocalPlayer",), (*OBJECT_CHAIN, "UPlayer")),
    "UDataTable": (("UDataTable",), OBJECT_CHAIN),
}
# Who else may implement a slot of the section (an override in the middle, an interface).
EXTRA_OWNERS = {
    "UEngine": ("UEngine", "UGameEngine"),
    "FMalloc": ("FMalloc", "FExec", "FUseSystemMallocForNew"),
    "FOutputDevice": ("FOutputDevice",),
    "UPlayer": ("UPlayer", "ULocalPlayer"),
}
# Entries no MSVC template has: in Itanium the override of a virtual from the SECONDARY base also
# gets a slot in the primary vtable. That is how UE4SS Linux finds ULocalPlayer::Exec (the player
# console): the MSVC offset landed on a destructor.
EXTRA_ENTRIES = {"UPlayer": [("Exec", "Exec(UWorld*, const wchar_t*, FOutputDevice&)")]}

# Template spelling (MSVC) -> .sym spelling (Itanium demangler), compared without spaces.
TYPE_WORDS = [
    (r"\bwchar_t\b", "char16_t"), (r"\bTCHAR\b", "char16_t"), (r"\buint8\b", "unsignedchar"),
    (r"\buint16\b", "unsignedshort"), (r"\buint32\b", "unsignedint"), (r"\buint64\b", "unsignedlong"),
    (r"\bint8\b", "signedchar"), (r"\bint16\b", "short"), (r"\bint32\b", "int"), (r"\bint64\b", "long"),
    (r"\b(class|struct|enum)\s+", ""), (r"\bconst\b", ""), (r"\s+", ""),
]
METHOD = re.compile(r"(~?[A-Za-z_]\w*|operator\s*\S+)$")

# Functions of each UE4SS signature (.lua file -> possible names in the .sym).
SIGNATURE_FUNCTIONS = {
    "FName_ToString": ("FName::ToString(FString&) const",),
    "FName_Constructor": ("FName::FName(char16_t const*, EFindName)", "FName::FName(wchar_t const*, EFindName)"),
    "StaticConstructObject": ("StaticConstructObject_Internal(FStaticConstructObjectParameters const&)",),
}
FRAME_STEP = "FFrame::Step(UObject*, void*)"


class Signature(NamedTuple):
    owner: str      # "UObject" in "UObject::Serialize(FArchive&)"; empty in the template
    method: str
    params: str     # normalized
    const: bool


def normalize(params: str) -> str:
    for pattern, repl in TYPE_WORDS:
        params = re.sub(pattern, repl, params)
    return params


def parse(text: str) -> Signature | None:
    """'UObject::Serialize(FArchive&) const' or 'const FName& GetX() const' -> Signature."""
    close = text.rfind(")")
    if close < 0:
        return None
    depth = 0
    for i in range(close, -1, -1):
        if text[i] == ")":
            depth += 1
        elif text[i] == "(":
            depth -= 1
            if depth == 0:
                break
    else:
        return None
    head, params, tail = text[:i].rstrip(), text[i + 1:close], text[close + 1:]
    match = METHOD.search(head)
    if not match:
        return None
    qualified = head[:match.start()]
    # The demangler writes "void *FMalloc::Malloc(...)": the return type's * sticks to the owner.
    owner = re.split(r"[\s*&]", qualified[:-2])[-1] if qualified.endswith("::") else ""
    return Signature(owner, match.group(1).replace(" ", ""), normalize(params), "const" in tail)


def read_template(text: str) -> dict[str, list[tuple[str, Signature | None]]]:
    """Section -> [(name in the ini, signature)] in template order (index 0 is the destructor)."""
    sections: dict[str, list[tuple[str, Signature | None]]] = {}
    current: list[tuple[str, Signature | None]] | None = None
    signature = ""
    for raw in text.replace("\r", "").splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            current = sections.setdefault(line[1:-1], [])
        elif line.startswith(";"):
            signature = line[1:].strip()
        elif line and current is not None:
            current.append((line, parse(signature) if signature else None))
            signature = ""
    return sections


class Image:
    """The ELF executable, via mmap: only the LOAD segments."""

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
        self.base = min(s[0] for s in self.segments)

    def is_code(self, va: int) -> bool:
        return any(x and v <= va < v + n for v, _o, n, x in self.segments)

    def read(self, va: int, size: int) -> bytes:
        for vaddr, offset, filesz, _x in self.segments:
            if vaddr <= va < vaddr + filesz:
                return self.data[offset + va - vaddr:offset + min(va - vaddr + size, filesz)]
        return b""

    def qword(self, va: int) -> int | None:
        chunk = self.read(va, 8)
        return struct.unpack("<Q", chunk)[0] if len(chunk) == 8 else None

    def occurrences(self, values: dict[int, str]) -> dict[str, list[int]]:
        """By name: every DATA address holding a qword with that name."""
        hits: dict[str, list[int]] = {}
        for vaddr, offset, filesz, executable in self.segments:
            if executable:
                continue
            view = memoryview(self.data)[offset:offset + filesz - filesz % 8]
            try:
                for i, (value,) in enumerate(struct.iter_unpack("<Q", view)):
                    name = values.get(value)
                    if name is not None:
                        hits.setdefault(name, []).append(vaddr + i * 8)
            finally:
                view.release()
        return hits


class Symbols:
    """The .sym: count, 20-byte records {u64 address, u32 line, u32 file, u32 name} and the
    table of newline-separated strings. Addresses are relative to the load base."""

    def __init__(self, path: str, base: int) -> None:
        self.file = open(path, "rb")  # noqa: SIM115 - kept open while the mmap lives
        self.data = mmap.mmap(self.file.fileno(), 0, access=mmap.ACCESS_READ)
        (self.count,) = struct.unpack_from("<I", self.data, 0)
        self.strings = 4 + self.count * RECORD.size
        self.base = base

    def text(self, offset: int) -> str:
        end = self.data.find(b"\n", self.strings + offset)
        return self.data[self.strings + offset:end].decode("utf-8", "replace")

    def addresses_of(self, names: set[str]) -> dict[str, set[int]]:
        """Every address (base already added) of the records with each name - a function has one per line."""
        offsets: dict[int, str] = {}
        for name in names:
            needle = b"\n" + name.encode() + b"\n"
            pos = self.data.find(needle, self.strings - 1)
            while pos != -1:
                offsets[pos + 1 - self.strings] = name
                pos = self.data.find(needle, pos + 1)
        found: dict[str, set[int]] = {name: set() for name in names}
        view = memoryview(self.data)[4:self.strings]
        try:
            for addr, _l, _f, name in RECORD.iter_unpack(view):
                hit = offsets.get(name)
                if hit:
                    found[hit].add(addr + self.base)
        finally:
            view.release()
        return found

    def names_at(self, addresses: set[int]) -> dict[int, str]:
        wanted = {a - self.base for a in addresses}
        names: dict[int, str] = {}
        view = memoryview(self.data)[4:self.strings]
        try:
            for addr, _l, _f, name in RECORD.iter_unpack(view):
                if addr in wanted and addr + self.base not in names:
                    names[addr + self.base] = self.text(name)
        finally:
            view.release()
        return names


# ------------------------------------------------------------------ VTableLayout.ini

def address_point(image: Image, hit: int, names: dict[int, str]) -> int | None:
    """The start of the vtable for a destructor found at `hit` (the complete or the deleting one)."""
    for start in (hit, hit - 8):
        first, second = image.qword(start), image.qword(start + 8)
        top, rtti = image.qword(start - 16), image.qword(start - 8)
        if top == 0 and rtti == 0 and first and second and "::~" in names.get(first, "") \
                and "::~" in names.get(second, ""):
            return start
    return None


def find_vtables(image: Image, symbols: Symbols, classes: list[str]) -> dict[str, int]:
    dtor_names = {f"{c}::~{c.rsplit('::', 1)[-1]}()": c for c in classes}
    by_address = {a: n for n, addrs in symbols.addresses_of(set(dtor_names)).items() for a in addrs}
    hits = image.occurrences(by_address)
    around = {image.qword(h + d) for hs in hits.values() for h in hs for d in (-8, 0, 8)}
    names = symbols.names_at({a for a in around if a})
    vtables: dict[str, int] = {}
    for name, addresses in hits.items():
        for hit in addresses:
            start = address_point(image, hit, names)
            if start is not None:
                vtables[dtor_names[name]] = start
                break
    return vtables


def read_slots(image: Image, symbols: Symbols) -> dict[str, list[Signature | None]]:
    """Class -> the signature of each slot of its vtable (None = the .sym does not name it)."""
    classes = sorted({c for candidates, _b in SECTIONS.values() for c in candidates})
    slots: dict[str, list[int]] = {}
    for owner, start in find_vtables(image, symbols, classes).items():
        pointers: list[int] = []
        for i in range(MAX_SLOTS):
            value = image.qword(start + i * 8)
            if value is None or not image.is_code(value):
                break
            pointers.append(value)
        slots[owner] = pointers
    names = symbols.names_at({a for pointers in slots.values() for a in pointers})
    return {owner: [parse(names.get(a, "")) for a in pointers] for owner, pointers in slots.items()}


def match_section(entries: list[tuple[str, Signature | None]], live: dict[int, Signature],
                  owners: set[str], base: int) -> dict[int, str]:
    """Index in the section (slot - base) -> template name, for each entry found in the vtable."""
    taken: set[int] = set()
    placed: dict[int, str] = {}
    for ini_name, wanted in entries:
        if wanted is None:
            continue
        found = [s for s, sig in live.items()
                 if s not in taken and sig.method == wanted.method and sig.owner.rsplit("::", 1)[-1] in owners]
        if len(found) > 1:
            # Overload: the signature breaks the tie, and const separates the const/non-const pair.
            exact = [s for s in found if live[s].params == wanted.params and live[s].const == wanted.const]
            found = exact or [s for s in found if live[s].params == wanted.params] or found
        if found:
            taken.add(found[0])
            placed[found[0] - base] = ini_name
    return placed


def vtable_ini(image: Image, symbols: Symbols, template_text: str) -> tuple[str, list[str]]:
    template = read_template(template_text)
    live_by_class = read_slots(image, symbols)
    sizes: dict[str, int] = {}
    out = ["; Gerado pelo painel (ue_sym_layout.py) a partir do executavel e do .sym deste servidor:",
           "; a ordem real de cada vtable, casada com os nomes do template por nome e assinatura.", ""]
    report = []
    for section, (candidates, bases) in SECTIONS.items():
        cls = next((c for c in candidates if c in live_by_class), None)
        entries = template.get(section)
        if cls is None or not entries:
            report.append(f"{section}: sem vtable" if cls is None else f"{section}: fora do template")
            continue
        base = bases if isinstance(bases, int) else sum(sizes.get(b, 0) for b in bases)
        owners = {section, cls, *(() if isinstance(bases, int) else bases), *EXTRA_OWNERS.get(section, ())}
        owners |= {o.rsplit("::", 1)[-1] for o in owners}
        # Only the slots the .sym named, from the section onwards.
        live = {s: sig for s, sig in enumerate(live_by_class[cls]) if sig and s > base}
        extra = [(name, parse(signature)) for name, signature in EXTRA_ENTRIES.get(section, [])]
        placed = match_section(entries[1:] + extra, live, owners, base)
        # The reader stacks each section on top of the size of its bases: ending the section at the
        # last slot found keeps the sum equal to the real position of what comes next.
        size = max(placed, default=0)
        sizes[section] = size
        out += [f"[{section}]", DTOR]
        out += [placed.get(i, f"__linux_slot_{i + base}") for i in range(1, size + 1)]
        out.append("")
        report.append(f"{section}: {len(placed)} de {len(entries) - 1}")
    return "\n".join(out) + "\n", report


# ------------------------------------------------------------------ UE4SS_Signatures

def wildcard_mask(code: bytes) -> list[bool]:
    """True = fixed AOB byte; the operand of call/jmp/jcc rel32 and of [rip+disp32] becomes a wildcard."""
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
        else:
            i += 1
    return keep


def unique_aob(image: Image, code: bytes) -> str | None:
    """The shortest AOB from the start of `code` that matches ONCE in the whole executable."""
    keep = wildcard_mask(code)
    for n in range(12, min(MAX_AOB, len(code)) + 1, 4):
        pattern = b"".join(re.escape(code[k:k + 1]) if keep[k] else b"." for k in range(n))
        hits = 0
        for _ in re.finditer(pattern, image.data, re.DOTALL):
            hits += 1
            if hits > 1:
                break
        if hits == 1:
            return " ".join(f"{code[k]:02X}" if keep[k] else "??" for k in range(n))
    return None


def gnatives_offset(code: bytes) -> int | None:
    """`mov r64, [disp32 + reg*8]` with no base (REX.W 8B, ModRM mod=00 rm=100, SIB scale 8 base=101):
    in FFrame::Step it is the read of the Blueprint VM table; the disp32 IS GNatives (non-PIE)."""
    for i in range(len(code) - 7):
        rex, opcode, modrm, sib = code[i:i + 4]
        if rex & 0xF8 == 0x48 and opcode == 0x8B and modrm & 0xC7 == 0x04 and sib & 0xC7 == 0xC5:
            return i
    return None


def lua_signature(aob: str, on_match: str) -> str:
    return f'function Register()\n    return "{aob}"\nend\n\nfunction OnMatchFound(MatchAddress)\n    {on_match}\nend\n'


def signatures(image: Image, symbols: Symbols) -> tuple[dict[str, str], list[str]]:
    wanted = {name for names in SIGNATURE_FUNCTIONS.values() for name in names} | {FRAME_STEP}
    found = {name: min(addrs) for name, addrs in symbols.addresses_of(wanted).items() if addrs}
    files: dict[str, str] = {}
    report = []
    for lua, names in SIGNATURE_FUNCTIONS.items():
        va = next((found[n] for n in names if n in found), None)
        aob = unique_aob(image, image.read(va, MAX_AOB)) if va else None
        if aob:
            files[f"{SIGNATURES_DIR}/{lua}.lua"] = lua_signature(aob, "return MatchAddress")
        report.append(f"{lua}: {'ok' if aob else 'nao achado'}")
    va = found.get(FRAME_STEP)
    code = image.read(va, STEP_BYTES) if va else b""
    at = gnatives_offset(code)
    aob = unique_aob(image, code[:MAX_AOB]) if at is not None else None
    if aob and at is not None:
        files[f"{SIGNATURES_DIR}/GNatives.lua"] = lua_signature(
            aob, f"return DerefToInt32(MatchAddress + 0x{at + 4:X})")
    report.append(f"GNatives: {'ok' if aob else 'nao achado'}")
    return files, report


def main(argv: list[str]) -> int:
    executable, template_path = argv
    image = Image(executable)
    symbols = Symbols(executable + ".sym", image.base)
    with open(template_path, encoding="utf-8") as f:
        ini, report = vtable_ini(image, symbols, f.read())
    files, sig_report = signatures(image, symbols)
    files[VTABLE_INI] = ini
    print(json.dumps({"files": files, "report": report + sig_report}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
