"""
A deliberately narrow LLVM IR (.ll) text model.

This is NOT a general LLVM IR parser. It supports the regular, unoptimized
shape that `clang -S -emit-llvm -O0` produces for a defined subset of C
(ints/pointers/strings, straight-line + branching control flow, plain
function calls). Anything it doesn't recognize is kept as opaque text and
passed through unchanged, so a construct outside the supported subset
degrades to "not transformed" rather than crashing the parser.

Key design decision: LLVM requires unnamed (bare-integer) SSA values and
block labels to be numbered contiguously by the printer. Since obfuscation
passes insert new instructions/blocks, keeping that invariant intact would
be fragile. Instead, every anonymous local (`%9`) and block label (`9:`) is
renamed once, up front, to an explicit name (`%v9` / `v9:`) that can never
collide with LLVM's own numbering scheme. All later transforms only ever
introduce further explicitly-named locals/blocks.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

GLOBAL_NAME = r'@(?:"(?:[^"\\]|\\.)*"|[\w.$-]+)'
LOCAL_NAME = r'%(?:"(?:[^"\\]|\\.)*"|[\w.$-]+)'

_ANON_LOCAL_REF_RE = re.compile(r'%(\d+)\b')
_ANON_LABEL_DEF_RE = re.compile(r'^(\d+):', re.MULTILINE)


def canonicalize_locals(text: str) -> str:
    """Rename bare-integer locals/labels (%9, 9:) to explicit names (%v9, v9:)."""
    text = _ANON_LOCAL_REF_RE.sub(lambda m: f'%v{m.group(1)}', text)
    text = _ANON_LABEL_DEF_RE.sub(lambda m: f'v{m.group(1)}:', text)
    return text


def decode_ir_string(escaped: str) -> bytes:
    """Decode LLVM's c"..." byte-string escape format into raw bytes."""
    out = bytearray()
    i = 0
    while i < len(escaped):
        c = escaped[i]
        if c == '\\':
            hex_byte = escaped[i + 1:i + 3]
            out.append(int(hex_byte, 16))
            i += 3
        else:
            out.append(ord(c))
            i += 1
    return bytes(out)


def encode_ir_string(data: bytes) -> str:
    """Encode raw bytes into LLVM's c"..." byte-string escape format."""
    out = []
    for b in data:
        ch = chr(b)
        if 0x20 <= b <= 0x7E and ch not in ('\\', '"'):
            out.append(ch)
        else:
            out.append(f'\\{b:02X}')
    return ''.join(out)


@dataclass
class RawLine:
    """A top-level line we don't need to understand (comments, target
    triple, comdat groups, attribute groups, metadata, ...)."""
    text: str

    def render(self) -> str:
        return self.text


@dataclass
class GlobalVar:
    """A top-level `@name = ...` global variable/constant definition."""
    name: str            # includes leading '@'
    raw: str             # full original line, used verbatim unless string fields are edited
    is_string: bool = False
    str_len: int = 0     # the N in [N x i8]
    str_bytes: bytes = b''
    _prefix: str = ''    # text before the c"..." literal
    _suffix: str = ''    # text after the c"..." literal (", comdat, align 1")

    def render(self) -> str:
        if not self.is_string:
            return self.raw
        return f'{self._prefix}c"{encode_ir_string(self.str_bytes)}"{self._suffix}'


_GLOBAL_STRING_RE = re.compile(
    r'^(?P<prefix>' + GLOBAL_NAME + r'\s*=.*?\[(?P<len>\d+)\s*x\s*i8\]\s*)'
    r'c"(?P<bytes>(?:[^"\\]|\\.)*)"'
    r'(?P<suffix>.*)$'
)


def _parse_global_var(line: str) -> GlobalVar:
    name_match = re.match(GLOBAL_NAME, line)
    name = name_match.group(0) if name_match else line.split('=')[0].strip()
    m = _GLOBAL_STRING_RE.match(line)
    if not m:
        return GlobalVar(name=name, raw=line)
    return GlobalVar(
        name=name,
        raw=line,
        is_string=True,
        str_len=int(m.group('len')),
        str_bytes=decode_ir_string(m.group('bytes')),
        _prefix=m.group('prefix'),
        _suffix=m.group('suffix'),
    )


# --- Instructions -----------------------------------------------------

BINOP_RE = re.compile(
    r'^(?P<result>' + LOCAL_NAME + r') = (?P<op>add|sub|mul|and|or|xor)'
    r'(?P<flags>(?: nsw| nuw)*) (?P<type>\S+) (?P<lhs>[^,]+), (?P<rhs>.+)$'
)
ICMP_RE = re.compile(
    r'^(?P<result>' + LOCAL_NAME + r') = icmp (?P<cond>\w+) (?P<type>\S+) '
    r'(?P<lhs>[^,]+), (?P<rhs>.+)$'
)
_METADATA_SUFFIX = r'(?:, !\S+ !\d+)*$'
BR_COND_RE = re.compile(
    r'^br i1 (?P<cond>[^,]+), label (?P<iftrue>' + LOCAL_NAME + r'), label (?P<iffalse>' + LOCAL_NAME + r')'
    + _METADATA_SUFFIX
)
BR_UNCOND_RE = re.compile(r'^br label (?P<target>' + LOCAL_NAME + r')' + _METADATA_SUFFIX)
RET_RE = re.compile(r'^ret (?P<type>void|.+?)(?: (?P<value>.+))?$')
CALL_RE = re.compile(
    r'^(?:(?P<result>' + LOCAL_NAME + r') = )?'
    r'(?:tail |musttail |notail )?call (?P<rettype>.+?) '
    r'(?P<callee>' + GLOBAL_NAME + r'|' + LOCAL_NAME + r')\((?P<args>.*)\)(?P<attrs>.*)$'
)
GLOBAL_REF_RE = re.compile(GLOBAL_NAME)


@dataclass
class Instruction:
    raw: str
    opcode: Optional[str] = None
    fields: dict = field(default_factory=dict)

    def render(self) -> str:
        return '  ' + self.raw

    def global_refs(self) -> list[str]:
        return GLOBAL_REF_RE.findall(self.raw)


def _classify_instruction(text: str) -> Instruction:
    for opcode, rx in (
        ('binop', BINOP_RE),
        ('icmp', ICMP_RE),
        ('br_cond', BR_COND_RE),
        ('br_uncond', BR_UNCOND_RE),
        ('ret', RET_RE),
        ('call', CALL_RE),
    ):
        m = rx.match(text)
        if m:
            return Instruction(raw=text, opcode=opcode, fields=m.groupdict())
    return Instruction(raw=text, opcode=None, fields={})


@dataclass
class BasicBlock:
    label: str
    instructions: list = field(default_factory=list)
    is_entry: bool = False

    def render(self) -> str:
        lines = [f'{self.label}:']
        lines.extend(i.render() for i in self.instructions)
        return '\n'.join(lines)

    def terminator(self) -> Optional[Instruction]:
        if self.instructions and self.instructions[-1].opcode in ('br_cond', 'br_uncond', 'ret'):
            return self.instructions[-1]
        return None


@dataclass
class Function:
    header: str          # e.g. 'define dso_local i32 @add(i32 noundef %v0, i32 noundef %v1) #0 {'
    name: str
    blocks: list = field(default_factory=list)
    is_declaration: bool = False

    def render(self) -> str:
        if self.is_declaration:
            return self.header
        body = '\n\n'.join(b.render() for b in self.blocks)
        return f'{self.header}\n{body}\n}}'


_DEFINE_NAME_RE = re.compile(r'^define\b.*?(' + GLOBAL_NAME + r')\s*\(')
_DECLARE_NAME_RE = re.compile(r'^declare\b.*?(' + GLOBAL_NAME + r')\s*\(')


def _parse_function(lines: list[str]) -> Function:
    header = lines[0]
    name_match = _DEFINE_NAME_RE.match(header)
    name = name_match.group(1) if name_match else '@?'

    blocks: list[BasicBlock] = []
    current: Optional[BasicBlock] = None
    first = True
    for raw_line in lines[1:-1]:  # skip 'define ... {' and closing '}'
        if not raw_line.strip():
            continue
        if not raw_line.startswith((' ', '\t')):
            label = raw_line.split(':', 1)[0].strip()
            current = BasicBlock(label=label, is_entry=first)
            blocks.append(current)
            first = False
            continue
        text = raw_line.strip()
        if current is None:
            current = BasicBlock(label='entry', is_entry=True)
            blocks.append(current)
            first = False
        current.instructions.append(_classify_instruction(text))

    return Function(header=header, name=name, blocks=blocks)


@dataclass
class Module:
    items: list = field(default_factory=list)  # RawLine | GlobalVar | Function

    def render(self) -> str:
        return '\n'.join(item.render() for item in self.items) + '\n'

    def functions(self) -> list:
        return [i for i in self.items if isinstance(i, Function) and not i.is_declaration]

    def find_function(self, name: str) -> Optional[Function]:
        if not name.startswith('@'):
            name = '@' + name
        for f in self.functions():
            if f.name == name:
                return f
        return None

    def string_globals(self) -> list:
        return [i for i in self.items if isinstance(i, GlobalVar) and i.is_string]


def parse_module(text: str) -> Module:
    text = canonicalize_locals(text)
    lines = text.split('\n')
    items: list = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if line.startswith('define '):
            j = i
            while j < n and lines[j].rstrip() != '}':
                j += 1
            func_lines = lines[i:j + 1]
            items.append(_parse_function(func_lines))
            i = j + 1
            continue
        if line.startswith('declare '):
            name_match = _DECLARE_NAME_RE.match(line)
            name = name_match.group(1) if name_match else '@?'
            items.append(Function(header=line, name=name, is_declaration=True))
            i += 1
            continue
        if line.startswith('@'):
            items.append(_parse_global_var(line))
            i += 1
            continue
        items.append(RawLine(line))
        i += 1
    return Module(items=items)
