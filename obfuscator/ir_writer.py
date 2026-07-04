"""Serialize an ir_model.Module back into LLVM IR text."""
from .ir_model import Module


def write_module(module: Module) -> str:
    return module.render()
