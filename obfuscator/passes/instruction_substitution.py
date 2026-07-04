"""Rewrites add/sub/xor into longer, semantically-equivalent instruction
sequences (mixed boolean-arithmetic identities), so a naive opcode/signature
scan no longer sees a plain `add`/`sub`/`xor`.

Identities used (all exact, not approximations):
    a + b == (a ^ b) + 2*(a & b)        (variant A)
    a + b == (a | b) + (a & b)          (variant B)
    a - b == a + (~b + 1)               (two's complement)
    a ^ b == (a | b) - (a & b)

`nsw`/`nuw` flags on the original instruction are dropped: they only assert
"no overflow" and license poison on overflow, so replacing them with plain
wrapping arithmetic can only make behavior *more* defined, never different
for any input that wasn't already undefined behavior.
"""
from ..ir_model import Instruction, Module
from .base import Pass


class InstructionSubstitutionPass(Pass):
    name = "subst"

    def __init__(self, rng=None):
        super().__init__(rng)
        self._counter = 0

    def _next_id(self) -> int:
        self._counter += 1
        return self._counter

    def run(self, module: Module) -> None:
        for func in module.functions():
            for block in func.blocks:
                new_instructions = []
                for instr in block.instructions:
                    replacement = self._substitute(instr)
                    new_instructions.extend(replacement)
                block.instructions = new_instructions

    def _substitute(self, instr: Instruction) -> list:
        if instr.opcode != "binop" or instr.fields.get("op") not in ("add", "sub", "xor"):
            return [instr]

        op = instr.fields["op"]
        result = instr.fields["result"]
        type_ = instr.fields["type"]
        lhs = instr.fields["lhs"]
        rhs = instr.fields["rhs"]
        uid = self._next_id()

        if op == "add":
            raws = self._add_variant(result, type_, lhs, rhs, uid)
        elif op == "sub":
            raws = self._sub_variant(result, type_, lhs, rhs, uid)
        else:
            raws = self._xor_variant(result, type_, lhs, rhs, uid)

        return [Instruction(raw=r) for r in raws]

    def _add_variant(self, result, type_, lhs, rhs, uid) -> list:
        if self.rng.choice([True, False]):
            t1, t2, t3 = f"%mba{uid}_1", f"%mba{uid}_2", f"%mba{uid}_3"
            return [
                f"{t1} = xor {type_} {lhs}, {rhs}",
                f"{t2} = and {type_} {lhs}, {rhs}",
                f"{t3} = shl {type_} {t2}, 1",
                f"{result} = add {type_} {t1}, {t3}",
            ]
        t1, t2 = f"%mba{uid}_1", f"%mba{uid}_2"
        return [
            f"{t1} = or {type_} {lhs}, {rhs}",
            f"{t2} = and {type_} {lhs}, {rhs}",
            f"{result} = add {type_} {t1}, {t2}",
        ]

    def _sub_variant(self, result, type_, lhs, rhs, uid) -> list:
        t1, t2 = f"%mba{uid}_1", f"%mba{uid}_2"
        return [
            f"{t1} = xor {type_} {rhs}, -1",
            f"{t2} = add {type_} {t1}, 1",
            f"{result} = add {type_} {lhs}, {t2}",
        ]

    def _xor_variant(self, result, type_, lhs, rhs, uid) -> list:
        t1, t2 = f"%mba{uid}_1", f"%mba{uid}_2"
        return [
            f"{t1} = or {type_} {lhs}, {rhs}",
            f"{t2} = and {type_} {lhs}, {rhs}",
            f"{result} = sub {type_} {t1}, {t2}",
        ]
