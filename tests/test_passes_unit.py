import random

import llvmlite.binding as llvm

from obfuscator.ir_model import parse_module
from obfuscator.ir_writer import write_module
from obfuscator.verify import verify_ir
from obfuscator.passes.string_encryption import StringEncryptionPass
from obfuscator.passes.instruction_substitution import InstructionSubstitutionPass
from obfuscator.passes.bogus_control_flow import BogusControlFlowPass
from obfuscator.passes.control_flow_flattening import ControlFlowFlatteningPass

SIMPLE_MODULE = """\
@.str = private unnamed_addr constant [4 x i8] c"hey\\00", align 1

declare i32 @puts(ptr noundef)

define i32 @main() {
entry:
  %1 = call i32 @puts(ptr noundef @.str)
  ret i32 0
}
"""


def test_string_encryption_changes_bytes_but_stays_valid():
    module = parse_module(SIMPLE_MODULE)
    [g] = module.string_globals()
    assert g.str_bytes == b"hey\x00"

    StringEncryptionPass(random.Random(1)).run(module)

    [g_after] = module.string_globals()
    assert g_after.str_bytes != b"hey\x00"
    assert len(g_after.str_bytes) == 4

    rendered = write_module(module)
    verify_ir(rendered)
    assert "@.str" not in rendered.split("call i32 @puts")[1]


def test_string_encryption_is_a_noop_without_string_globals():
    module = parse_module(
        "define i32 @main() {\nentry:\n  ret i32 0\n}\n"
    )
    before = write_module(module)
    StringEncryptionPass(random.Random(1)).run(module)
    assert write_module(module) == before


BINOP_MODULE = """\
define i32 @calc(i32 %a, i32 %b) {
entry:
  %s = add nsw i32 %a, %b
  %d = sub nsw i32 %a, %b
  %x = xor i32 %a, %b
  %t1 = add i32 %s, %d
  %t2 = xor i32 %t1, %x
  ret i32 %t2
}
"""


def _jit_call_calc(ir_text: str, a: int, b: int) -> int:
    import ctypes

    llvm.initialize_native_target()
    llvm.initialize_native_asmprinter()
    target_machine = llvm.Target.from_default_triple().create_target_machine()
    backing_mod = llvm.parse_assembly(ir_text)
    backing_mod.verify()
    engine = llvm.create_mcjit_compiler(backing_mod, target_machine)
    engine.finalize_object()
    addr = engine.get_function_address("calc")
    cfunc = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_int32, ctypes.c_int32)(addr)
    result = cfunc(a, b)
    engine.close()
    return result


def test_instruction_substitution_preserves_semantics():
    module = parse_module(BINOP_MODULE)
    binops_before = sum(
        1 for f in module.functions() for b in f.blocks for i in b.instructions
        if i.opcode == "binop"
    )
    assert binops_before == 5

    InstructionSubstitutionPass(random.Random(3)).run(module)
    rendered = write_module(module)
    verify_ir(rendered)

    # add/sub/xor should no longer appear as direct top-level binops feeding
    # the result chain unchanged -- the pass must have expanded them.
    assert rendered.count("\n") > BINOP_MODULE.count("\n")

    for a, b in [(3, 4), (10, 2), (-5, 7), (0, 0), (100, -100)]:
        original = _jit_call_calc(BINOP_MODULE, a, b)
        transformed = _jit_call_calc(rendered, a, b)
        assert transformed == original, f"mismatch for ({a}, {b})"


BRANCHY_MODULE = """\
define i32 @classify(i32 %n) {
entry:
  %c1 = icmp sgt i32 %n, 0
  br i1 %c1, label %pos, label %nonpos

pos:
  %r1 = mul i32 %n, 2
  ret i32 %r1

nonpos:
  %c2 = icmp eq i32 %n, 0
  br i1 %c2, label %zero, label %neg

zero:
  ret i32 0

neg:
  %r2 = mul i32 %n, -1
  ret i32 %r2
}
"""


def _jit_call_classify(ir_text: str, n: int) -> int:
    import ctypes

    llvm.initialize_native_target()
    llvm.initialize_native_asmprinter()
    target_machine = llvm.Target.from_default_triple().create_target_machine()
    backing_mod = llvm.parse_assembly(ir_text)
    backing_mod.verify()
    engine = llvm.create_mcjit_compiler(backing_mod, target_machine)
    engine.finalize_object()
    addr = engine.get_function_address("classify")
    cfunc = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_int32)(addr)
    result = cfunc(n)
    engine.close()
    return result


def test_bogus_control_flow_preserves_semantics_and_adds_blocks():
    module = parse_module(BRANCHY_MODULE)
    blocks_before = sum(len(f.blocks) for f in module.functions())

    BogusControlFlowPass(random.Random(5), probability=1.0).run(module)
    blocks_after = sum(len(f.blocks) for f in module.functions())
    # every one of the 5 original blocks should have gained a junk+real pair
    assert blocks_after == blocks_before + 2 * blocks_before

    rendered = write_module(module)
    verify_ir(rendered)

    for n in [5, -3, 0, 42, -100]:
        assert _jit_call_classify(rendered, n) == _jit_call_classify(BRANCHY_MODULE, n)


LOOPY_MODULE = """\
define i32 @sum_to_n(i32 %n) {
entry:
  %total = alloca i32, align 4
  %i = alloca i32, align 4
  store i32 0, ptr %total, align 4
  store i32 1, ptr %i, align 4
  br label %check

check:
  %iv = load i32, ptr %i, align 4
  %cond = icmp sle i32 %iv, %n
  br i1 %cond, label %body, label %done

body:
  %t1 = load i32, ptr %total, align 4
  %i1 = load i32, ptr %i, align 4
  %t2 = add i32 %t1, %i1
  store i32 %t2, ptr %total, align 4
  %i2 = load i32, ptr %i, align 4
  %i3 = add i32 %i2, 1
  store i32 %i3, ptr %i, align 4
  br label %check

done:
  %result = load i32, ptr %total, align 4
  ret i32 %result
}
"""


def _jit_call_sum_to_n(ir_text: str, n: int) -> int:
    import ctypes

    llvm.initialize_native_target()
    llvm.initialize_native_asmprinter()
    target_machine = llvm.Target.from_default_triple().create_target_machine()
    backing_mod = llvm.parse_assembly(ir_text)
    backing_mod.verify()
    engine = llvm.create_mcjit_compiler(backing_mod, target_machine)
    engine.finalize_object()
    addr = engine.get_function_address("sum_to_n")
    cfunc = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_int32)(addr)
    result = cfunc(n)
    engine.close()
    return result


def test_control_flow_flattening_preserves_semantics_for_loops():
    module = parse_module(LOOPY_MODULE)
    ControlFlowFlatteningPass(random.Random(11)).run(module)
    rendered = write_module(module)
    verify_ir(rendered)

    assert "switch i32" in rendered
    assert "flat_dispatch" in rendered

    for n in [0, 1, 5, 10, 100]:
        assert _jit_call_sum_to_n(rendered, n) == _jit_call_sum_to_n(LOOPY_MODULE, n)


def test_control_flow_flattening_skips_unrecognized_terminators():
    module_with_indirect = (
        "define i32 @weird() {\n"
        "entry:\n"
        "  indirectbr ptr blockaddress(@weird, %entry), [label %entry]\n"
        "}\n"
    )
    module = parse_module(module_with_indirect)
    before = write_module(module)
    ControlFlowFlatteningPass(random.Random(1)).run(module)
    assert write_module(module) == before
