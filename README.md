# llvm-ir-obfuscator

A source-to-source obfuscator that operates directly on LLVM IR, written in
pure Python. It takes a `.c` file, lowers it with `clang -S -emit-llvm`,
applies a chain of obfuscation passes to the IR, and hands the result back
to `clang`/`llc` to produce a working binary.

Passes implemented so far:

- **String encryption** — XOR-encrypts string constants and decrypts them
  at runtime just before use, so `strings`/`objdump` on the compiled binary
  no longer reveals them in plaintext.
- **Instruction substitution** — rewrites arithmetic (`add`/`sub`/`xor`)
  into longer, semantically-equivalent instruction sequences (MBA-style).
- **Bogus control flow** — inserts opaque-predicate branches to junk basic
  blocks that always reconverge, without changing program behavior.
- **Control-flow flattening** — restructures each function into a single
  dispatch loop with a `switch` over an integer state variable (OLLVM-style).

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for how the pipeline is put
together and [docs/BEFORE_AFTER.md](docs/BEFORE_AFTER.md) for concrete
before/after IR and binary diffs.

## Status

Work in progress — see the repo's commit history / issues for what's done.

## Requirements

- `clang` on `PATH` (LLVM 14+; developed against LLVM 22)
- Python 3.9+, `pip install -r requirements.txt`

## Usage

```sh
python -m obfuscator input.c -o output.exe --passes strenc,subst,bogus,flatten --seed 1234
```

## Why this exists

A portfolio project demonstrating LLVM IR internals, classic
obfuscation/anti-reverse-engineering techniques, and the engineering
discipline of proving a transform preserves program semantics (see the
end-to-end tests in `tests/`) rather than just "looking obfuscated".

## Scope & limitations

This is not a general-purpose LLVM IR parser — it supports the regular,
unoptimized IR shape `clang -O0` emits for a defined C subset (ints,
pointers, string literals, straight-line + branching control flow, plain
function calls). Constructs outside that subset are preserved verbatim but
not transformed. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for
details.
