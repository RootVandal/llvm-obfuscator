"""Inserts opaque-predicate branches to a junk basic block that always
reconverges with the real code, without changing program behavior.

For a chosen block, its original content is moved into a new "real" block
and the block keeps its original label but its body is replaced with:

    <opaque predicate, always true>
    br i1 %ok, label %real, label %junk

  junk:
    <harmless dead instructions, purely local scratch>
    br label %real

  real:
    <original content>

Both branches converge on `real`, so this is safe even if the predicate
logic were wrong: whichever way the branch goes, execution still reaches
the original code afterwards. The predicate itself uses the identity
`k * (k+1)` is always even for any integer k, evaluated with real
arithmetic instructions (not folded, since we never run an optimizer over
generated IR) so it isn't a bare `icmp eq i32 0, 0` a naive dead-code scan
would flag immediately.

Original block labels are preserved (nothing else needs to be rewritten to
find them); only the newly-created junk/real blocks get fresh names.
"""
from ..ir_model import BasicBlock, Instruction, Module
from .base import Pass


class BogusControlFlowPass(Pass):
    name = "bogus"

    def __init__(self, rng=None, probability: float = 0.6):
        super().__init__(rng)
        self.probability = probability
        self._counter = 0

    def _next_id(self) -> int:
        self._counter += 1
        return self._counter

    def run(self, module: Module) -> None:
        for func in module.functions():
            new_blocks = []
            for block in func.blocks:
                new_blocks.append(block)
                if self.rng.random() < self.probability:
                    junk, real = self._split(block)
                    new_blocks.append(junk)
                    new_blocks.append(real)
            func.blocks = new_blocks

    def _split(self, block: BasicBlock):
        uid = self._next_id()
        real_label = f"{block.label}_real{uid}"
        junk_label = f"{block.label}_junk{uid}"

        k = self.rng.randint(1, 10_000)
        p = f"%bcf{uid}"
        gate_instructions = [
            Instruction(raw=f"{p}_k = add i32 0, {k}"),
            Instruction(raw=f"{p}_kp1 = add i32 {p}_k, 1"),
            Instruction(raw=f"{p}_prod = mul i32 {p}_k, {p}_kp1"),
            Instruction(raw=f"{p}_mod = srem i32 {p}_prod, 2"),
            Instruction(raw=f"{p}_ok = icmp eq i32 {p}_mod, 0"),
            Instruction(raw=f"br i1 {p}_ok, label %{real_label}, label %{junk_label}"),
        ]

        junk_const_a = self.rng.randint(0, 1_000_000)
        junk_const_b = self.rng.randint(0, 1_000_000)
        j = f"%bcfj{uid}"
        junk_instructions = [
            Instruction(raw=f"{j}_buf = alloca i32, align 4"),
            Instruction(raw=f"store i32 {junk_const_a}, ptr {j}_buf, align 4"),
            Instruction(raw=f"{j}_val = load i32, ptr {j}_buf, align 4"),
            Instruction(raw=f"{j}_sum = add i32 {j}_val, {junk_const_b}"),
            Instruction(raw=f"br label %{real_label}"),
        ]

        real_block = BasicBlock(label=real_label, instructions=block.instructions)
        junk_block = BasicBlock(label=junk_label, instructions=junk_instructions)
        block.instructions = gate_instructions

        return junk_block, real_block
