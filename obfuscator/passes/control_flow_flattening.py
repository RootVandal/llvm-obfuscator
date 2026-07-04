"""OLLVM-style control-flow flattening: restructures each function into a
single dispatch loop with a `switch` over an integer state variable, so the
function's real control flow no longer shows up as a normal-looking CFG in
a disassembler -- every block's only structural successor is the dispatcher,
and the actual "which block runs next" decision is data (a stored integer),
not a branch target.

Transform, per function:

    flat_entry:                          ; new, becomes the function's entry
      %state = alloca i32
      store i32 <id of original entry block>, ptr %state
      br label %flat_dispatch

    flat_dispatch:                       ; new
      %cur = load i32, ptr %state
      switch i32 %cur, label %flat_default [ i32 <id0>, label %<block0> ... ]

    <original block>:                    ; label unchanged, content unchanged
      ...                                ; except its terminator becomes:
      store i32 <next-id>, ptr %state    ;   (branch) or select+store (cond branch)
      br label %flat_dispatch            ;   ret instructions are left alone

    flat_default:
      unreachable

Every state-changing "branch" (conditional or not) still executes inside
the SAME original block where its condition was computed, so no new
cross-block SSA-dominance issue is introduced: %state's alloca lives in
flat_entry, which dominates every other block (it's the sole predecessor
of the dispatcher, which is in turn the sole predecessor of every case
block), so referencing the state pointer anywhere is always valid.

Only applied to functions where every block's terminator is one this
module recognizes (`ret`, unconditional `br`, conditional `br i1`) --
anything else is left completely untouched rather than risk emitting
invalid IR.

One more wrinkle: after flattening, every case block's only predecessor is
the dispatcher, and the dispatcher itself is a loop merge point with many
predecessors -- so no case block dominates any other anymore. Clang's -O0
output stores every local variable to a stack slot up front and only ever
passes values between blocks through those `alloca`'d pointers, so the one
place this bites is the `alloca`s themselves: an `alloca` sitting in what
used to be the entry block no longer dominates a load/store of it in some
other case block. The fix mirrors what real flattening passes do: hoist
every `alloca` to the new `flat_entry` block before rewriting terminators.
`alloca` has no observable side effect beyond reserving stack space, so
moving it earlier changes nothing about program behavior.
"""
import re

from ..ir_model import BasicBlock, Instruction, Module
from .base import Pass

_RECOGNIZED_TERMINATORS = ("ret", "br_uncond", "br_cond")
_ALLOCA_RE = re.compile(r'^%\S+ = alloca\b')


class ControlFlowFlatteningPass(Pass):
    name = "flatten"

    def __init__(self, rng=None):
        super().__init__(rng)
        self._counter = 0

    def _next_id(self) -> int:
        self._counter += 1
        return self._counter

    def run(self, module: Module) -> None:
        for func in module.functions():
            if not func.blocks or not self._all_terminators_recognized(func):
                continue
            self._flatten(func)

    def _hoist_allocas(self, blocks) -> list:
        hoisted = []
        for b in blocks:
            remaining = []
            for instr in b.instructions:
                if _ALLOCA_RE.match(instr.raw):
                    hoisted.append(instr)
                else:
                    remaining.append(instr)
            b.instructions = remaining
        return hoisted

    def _all_terminators_recognized(self, func) -> bool:
        for block in func.blocks:
            if not block.instructions:
                return False
            if block.instructions[-1].opcode not in _RECOGNIZED_TERMINATORS:
                return False
        return True

    def _flatten(self, func) -> None:
        original_blocks = list(func.blocks)
        ids = list(range(len(original_blocks)))
        self.rng.shuffle(ids)
        label_to_id = {b.label: ids[i] for i, b in enumerate(original_blocks)}

        uid = self._next_id()
        state = f"%fstate{uid}"
        entry_label = f"flat_entry{uid}"
        dispatch_label = f"flat_dispatch{uid}"
        default_label = f"flat_default{uid}"

        entry_id = label_to_id[original_blocks[0].label]

        hoisted_allocas = self._hoist_allocas(original_blocks)

        new_entry = BasicBlock(label=entry_label, is_entry=True, instructions=[
            *hoisted_allocas,
            Instruction(raw=f"{state} = alloca i32, align 4"),
            Instruction(raw=f"store i32 {entry_id}, ptr {state}, align 4"),
            Instruction(raw=f"br label %{dispatch_label}"),
        ])

        cases = " ".join(
            f"i32 {label_to_id[b.label]}, label %{b.label}" for b in original_blocks
        )
        cur = f"%fcur{uid}"
        dispatch_block = BasicBlock(label=dispatch_label, instructions=[
            Instruction(raw=f"{cur} = load i32, ptr {state}, align 4"),
            Instruction(raw=f"switch i32 {cur}, label %{default_label} [ {cases} ]"),
        ])

        default_block = BasicBlock(label=default_label, instructions=[
            Instruction(raw="unreachable"),
        ])

        for b in original_blocks:
            b.is_entry = False
            self._rewrite_terminator(b, label_to_id, state, dispatch_label)

        func.blocks = [new_entry, dispatch_block] + original_blocks + [default_block]

    def _rewrite_terminator(self, block: BasicBlock, label_to_id: dict, state: str, dispatch_label: str) -> None:
        term = block.instructions[-1]

        if term.opcode == "ret":
            return

        if term.opcode == "br_uncond":
            target_id = label_to_id[term.fields["target"][1:]]
            block.instructions[-1] = Instruction(raw=f"store i32 {target_id}, ptr {state}, align 4")
            block.instructions.append(Instruction(raw=f"br label %{dispatch_label}"))
            return

        # br_cond
        iftrue_id = label_to_id[term.fields["iftrue"][1:]]
        iffalse_id = label_to_id[term.fields["iffalse"][1:]]
        cond = term.fields["cond"]
        nid = self._next_id()
        sel = f"%fsel{nid}"
        block.instructions[-1] = Instruction(
            raw=f"{sel} = select i1 {cond}, i32 {iftrue_id}, i32 {iffalse_id}"
        )
        block.instructions.append(Instruction(raw=f"store i32 {sel}, ptr {state}, align 4"))
        block.instructions.append(Instruction(raw=f"br label %{dispatch_label}"))
