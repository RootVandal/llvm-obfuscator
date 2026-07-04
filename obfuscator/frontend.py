"""Lowers a C source file to LLVM IR text via clang."""
import subprocess
import tempfile
import os

from .toolchain import find_clang


def compile_to_ir(source_path: str, clang: str = None) -> str:
    """Run `clang -S -emit-llvm -O0` on source_path and return the IR text."""
    clang = clang or find_clang()
    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "out.ll")
        result = subprocess.run(
            [
                clang, "-S", "-emit-llvm", "-O0",
                "-Xclang", "-disable-O0-optnone",
                source_path, "-o", out_path,
            ],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"clang frontend failed:\n{result.stderr}")
        with open(out_path, "r") as f:
            return f.read()
