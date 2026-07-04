# Architecture

```
input.c
   |  clang -S -emit-llvm -O0 -Xclang -disable-O0-optnone   (obfuscator/frontend.py)
   v
input.ll (text)
   |  parse_module()                                          (obfuscator/ir_model.py)
   v
Module (Python object model: RawLine | GlobalVar | Function[BasicBlock[Instruction]])
   |  StringEncryptionPass -> InstructionSubstitutionPass ->
   |  BogusControlFlowPass -> ControlFlowFlatteningPass        (obfuscator/passes/*.py)
   v
Module (mutated in place)
   |  write_module()                                          (obfuscator/ir_writer.py)
   v
output.ll (text)
   |  llvmlite.binding.parse_assembly(...).verify()            (obfuscator/verify.py)
   v
output.ll (verified valid IR)
   |  clang output.ll -o output.exe                            (obfuscator/backend.py)
   v
output.exe
```

## Why a hand-rolled IR model instead of an LLVM pass plugin

The obvious way to write an "LLVM obfuscator" is a native out-of-tree pass
plugin (`.so`/`.dll`) loaded via `clang -fpass-plugin=...`. That needs
LLVM's internal static libraries (`LLVMCore`, `LLVMSupport`, ...) and
`opt`. The official LLVM Windows release only ships `libclang`/`LLVM-C`
(the stable C API), not those internals -- there's no way to build a pass
plugin against it without building LLVM from source (hours, tens of GB) or
switching to Linux/WSL. This project instead treats LLVM IR as what it
textually is: a well-defined, greppable text format, and does the
transforms in pure Python.

`llvmlite` (the JIT library behind Numba) is used only for `parse_assembly(...).verify()`
-- it can parse and introspect a module, but its `binding` layer has no
instruction-mutation API (no insert/replace/remove on a parsed module), so
it can't drive the transforms itself. It's the right tool for "is this
still valid IR", not for "rewrite this IR".

## Why unnamed values are renamed up front

LLVM's textual IR requires unnamed (bare-integer) SSA values and block
labels (`%9`, `9:`) to be numbered contiguously by the printer. Passes
here insert new instructions and blocks, which would make maintaining that
invariant fragile and error-prone. `ir_model.canonicalize_locals()` renames
every bare-integer local/label to an explicit name (`%9` -> `%v9`, `9:` ->
`v9:`) as the very first parsing step. Explicit names have no numbering
constraint, so every later pass is free to introduce as many new
instructions/blocks as it wants without touching this at all.

## Why the parser is deliberately narrow

`ir_model.py` is not a general LLVM IR parser. It recognizes the specific,
regular shape `clang -O0` emits for a defined C subset: `alloca`/`load`/
`store`, `icmp`, `add`/`sub`/`mul`/`and`/`or`/`xor`, conditional/unconditional
`br`, `call`, `ret`, and string-constant globals. Anything else (metadata,
attribute groups, `phi`, floating point, structs, ...) is kept as opaque
text and passed through unchanged. A construct outside the supported
subset degrades to "not transformed", not a parser crash. This is a
deliberate scope cut, documented rather than hidden: real LLVM IR grammar
is large, and reproducing all of it isn't what this project is
demonstrating.

## Per-pass notes

**String encryption** (`passes/string_encryption.py`) XOR-encrypts each
string global's bytes in its initializer, then at every call site that
references the string, splices in straight-line
`getelementptr`/`load`/`xor`/`store` instructions that decrypt it into a
fresh stack buffer just before use. Because decryption always writes to a
brand-new `alloca`, not back into the (shared, possibly reused) global,
this is correct even if the same string literal were used from multiple
call sites or a loop -- there's no "already decrypted, don't XOR again"
bug to worry about.

**Instruction substitution** (`passes/instruction_substitution.py`) replaces
`add`/`sub`/`xor` with longer mixed-boolean-arithmetic-equivalent forms
(e.g. `a + b == (a ^ b) + 2*(a & b)`). These are exact identities, not
approximations, and `nsw`/`nuw` flags are dropped rather than propagated,
since those flags only assert "no overflow" (licensing poison on
overflow) -- dropping them can only make behavior more defined, never
different, for any input that wasn't already undefined behavior.

**Bogus control flow** (`passes/bogus_control_flow.py`) splits a block and
gates its original content behind an always-true opaque predicate
(`k*(k+1)` is always even), branching to either the real code or a junk
block of side-effect-free scratch instructions -- both paths reconverge on
the real code. This is safe by construction: even if the predicate logic
had a bug, both branches still lead to the same place.

**Control-flow flattening** (`passes/control_flow_flattening.py`) is the
most invasive: it turns every function into a dispatch loop with a
`switch` over an integer state variable (classic OLLVM-style flattening).
The tricky part is that after flattening, no block dominates any other
(every block's only predecessor is the dispatcher), which breaks clang's
-O0 pattern of stack-allocating locals in the entry block and referencing
them from anywhere else in the function. The fix: every `alloca` is
hoisted to the new true entry block before any terminators are rewritten,
since `alloca` has no side effect beyond reserving stack space and is
always safe to hoist earlier. This pass only runs on functions where every
block's terminator is one of the three forms it understands (`ret`,
unconditional `br`, conditional `br i1`); anything else and the whole
function is left untouched.

## Testing strategy

- `tests/test_pipeline.py` -- proves the parse/render/verify/compile
  plumbing round-trips correctly with **zero** passes applied.
- `tests/test_passes_unit.py` -- unit-tests each pass in isolation,
  including JIT-executing small hand-written modules via `llvmlite`
  before/after a transform and asserting identical results across a range
  of inputs (not just "the output looks different").
- `tests/test_end_to_end.py` -- runs the full CLI (all four passes
  chained) against every fixture, compiles both the original and
  obfuscated versions, runs both binaries, and asserts identical stdout
  and exit code. Also asserts the obfuscated binary no longer contains the
  original string literals in plaintext.
