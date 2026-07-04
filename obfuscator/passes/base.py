"""Base class for obfuscation passes.

Each pass mutates an ir_model.Module in place. Passes get a random.Random
seeded by the CLI's --seed so runs are reproducible.
"""
import random

from ..ir_model import Module


class Pass:
    name = "base"

    def __init__(self, rng: random.Random = None):
        self.rng = rng or random.Random()

    def run(self, module: Module) -> None:
        raise NotImplementedError
