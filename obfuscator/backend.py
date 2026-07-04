"""Compiles obfuscated LLVM IR text back into an object file or executable."""
import subprocess
import tempfile
import os

from .toolchain import find_clang


def compile_ir_to_binary(ir_text: str, output_path: str, clang: str = None) -> str:
    """Run clang on IR text, producing an executable/object at output_path."""
    clang = clang or find_clang()
    with tempfile.TemporaryDirectory() as tmp:
        ir_path = os.path.join(tmp, "module.ll")
        with open(ir_path, "w") as f:
            f.write(ir_text)
        result = subprocess.run(
            [clang, ir_path, "-o", output_path],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"clang backend failed:\n{result.stderr}")
        return output_path
