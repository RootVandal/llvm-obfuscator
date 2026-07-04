# Before / after

Source: [`tests/fixtures/strings.c`](../tests/fixtures/strings.c) --
prints `"big"` or `"small"` depending on a computed value, then `"done"`.

```sh
python -m obfuscator tests/fixtures/strings.c -o strings_obf.exe --seed 7 --emit-ir strings_obf.ll
```

## 1. String literals disappear from the binary

```python
>>> data_orig = open("strings_orig.exe", "rb").read()
>>> data_obf  = open("strings_obf.exe",  "rb").read()
>>> for s in [b"big", b"small", b"done"]:
...     print(s, "in original:", s in data_orig, "| in obfuscated:", s in data_obf)
b'big'   in original: True  | in obfuscated: False
b'small' in original: True  | in obfuscated: False
b'done'  in original: True  | in obfuscated: False
```

Both binaries still run identically:

```
$ ./strings_orig.exe          $ ./strings_obf.exe
big                           big
done                          done
$ echo $?  -> 7                $ echo $?  -> 7
```

## 2. The IR itself, before and after

**Before** (`clang -S -emit-llvm`, string constants in plaintext):

```llvm
@"??_C@_03CCCOBCKE@big?$AA@"   = linkonce_odr dso_local unnamed_addr constant [4 x i8] c"big\00", comdat, align 1
@"??_C@_05KJDGBEEG@small?$AA@" = linkonce_odr dso_local unnamed_addr constant [6 x i8] c"small\00", comdat, align 1
@"??_C@_04GMOJEHPC@done?$AA@"  = linkonce_odr dso_local unnamed_addr constant [5 x i8] c"done\00", comdat, align 1

define dso_local i32 @main() #0 {
  %1 = alloca i32, align 4
  %2 = alloca i32, align 4
  store i32 0, ptr %1, align 4
  store i32 7, ptr %2, align 4
  %3 = load i32, ptr %2, align 4
  %4 = icmp sgt i32 %3, 5
  br i1 %4, label %5, label %7

5:
  %6 = call i32 @puts(ptr noundef @"??_C@_03CCCOBCKE@big?$AA@")
  br label %9
  ...
```

**After** (`--passes strenc,subst,bogus,flatten --seed 7`): the globals now
hold XOR-encrypted bytes, and the entry block is gated behind an
always-true opaque predicate with a junk block alongside it:

```llvm
@"??_C@_03CCCOBCKE@big?$AA@"   = linkonce_odr dso_local unnamed_addr constant [4 x i8] c"1:4S", comdat, align 1
@"??_C@_05KJDGBEEG@small?$AA@" = linkonce_odr dso_local unnamed_addr constant [6 x i8] c"\80\9E\92\9F\9F\F3", comdat, align 1
@"??_C@_04GMOJEHPC@done?$AA@"  = linkonce_odr dso_local unnamed_addr constant [5 x i8] c"CHIB'", comdat, align 1

define dso_local i32 @main() #0 {
entry:
  %bcf1_k = add i32 0, 792
  %bcf1_kp1 = add i32 %bcf1_k, 1
  %bcf1_prod = mul i32 %bcf1_k, %bcf1_kp1
  %bcf1_mod = srem i32 %bcf1_prod, 2
  %bcf1_ok = icmp eq i32 %bcf1_mod, 0
  br i1 %bcf1_ok, label %entry_real1, label %entry_junk1

entry_junk1:
  %bcfj1_buf = alloca i32, align 4
  store i32 75954, ptr %bcfj1_buf, align 4
  %bcfj1_val = load i32, ptr %bcfj1_buf, align 4
  %bcfj1_sum = add i32 %bcfj1_val, 861168
  br label %entry_real1

entry_real1:
  %v1 = alloca i32, align 4
  %v2 = alloca i32, align 4
  store i32 0, ptr %v1, align 4
  store i32 7, ptr %v2, align 4
  %v3 = load i32, ptr %v2, align 4
  %v4 = icmp sgt i32 %v3, 5
  br i1 %v4, label %v5, label %v7
  ...
```

(the actual generated file also runs `--passes ...,flatten` last, which
further restructures every function into a `switch`-based dispatch loop --
see [ARCHITECTURE.md](ARCHITECTURE.md) for what that looks like structurally.)

## 3. What this demonstrates

A binary's size grows only modestly (a few hundred bytes to a few KB for
these tiny examples) while:

- static string scanning (`strings`, a hex editor, IDA's string window)
  no longer reveals the program's literals,
- opcode/signature-based scanning sees `xor`/`and`/`or`/`shl`/`select`
  sequences where a naive disassembly would expect a single `add`/`sub`,
  and a `switch`-based dispatch loop instead of the program's real
  control flow graph,
- the program's observable behavior (stdout, exit code) is provably
  identical before and after, per `tests/test_end_to_end.py`.
