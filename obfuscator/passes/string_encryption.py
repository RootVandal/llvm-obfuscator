"""XOR-encrypts string constants and decrypts them into a fresh stack buffer
at each use site, right before the instruction that references them.

Each byte is decrypted with a handful of straight-line instructions
(getelementptr/load/xor/store) rather than a runtime loop, so this pass
never has to touch control flow -- it only ever inserts instructions inside
an existing basic block. The instruction that used the global is rewritten
to reference the new decrypted stack buffer instead.
"""
from ..ir_model import GLOBAL_NAME, Instruction, Module
from .base import Pass


class StringEncryptionPass(Pass):
    name = "strenc"

    def __init__(self, rng=None):
        super().__init__(rng)
        self._counter = 0

    def _next_id(self) -> int:
        self._counter += 1
        return self._counter

    def run(self, module: Module) -> None:
        targets = [g for g in module.string_globals() if g.str_len > 0]
        if not targets:
            return

        keys = {}
        for g in targets:
            key = self.rng.randint(1, 255)
            keys[g.name] = key
            g.str_bytes = bytes(b ^ key for b in g.str_bytes)

        target_by_name = {g.name: g for g in targets}

        for func in module.functions():
            for block in func.blocks:
                new_instructions = []
                for instr in block.instructions:
                    refs = [r for r in instr.global_refs() if r in target_by_name]
                    for name in refs:
                        g = target_by_name[name]
                        buf_name = self._emit_decrypt(new_instructions, g, keys[name])
                        instr.raw = instr.raw.replace(name, buf_name, 1)
                    new_instructions.append(instr)
                block.instructions = new_instructions

    def _emit_decrypt(self, out: list, g, key: int) -> str:
        """Append instructions decrypting global `g` into a fresh stack
        buffer, returning the buffer's local name (e.g. '%buf3')."""
        n = g.str_len
        uid = self._next_id()
        buf = f'%buf{uid}'
        out.append(Instruction(raw=f'{buf} = alloca [{n} x i8], align 1'))
        for k in range(n):
            src_gep = f'%se{uid}_{k}'
            loaded = f'%sl{uid}_{k}'
            decrypted = f'%sx{uid}_{k}'
            dst_gep = f'%sd{uid}_{k}'
            out.append(Instruction(
                raw=f'{src_gep} = getelementptr inbounds [{n} x i8], ptr {g.name}, i64 0, i64 {k}'
            ))
            out.append(Instruction(raw=f'{loaded} = load i8, ptr {src_gep}, align 1'))
            out.append(Instruction(raw=f'{decrypted} = xor i8 {loaded}, {key}'))
            out.append(Instruction(
                raw=f'{dst_gep} = getelementptr inbounds [{n} x i8], ptr {buf}, i64 0, i64 {k}'
            ))
            out.append(Instruction(raw=f'store i8 {decrypted}, ptr {dst_gep}, align 1'))
        return buf
