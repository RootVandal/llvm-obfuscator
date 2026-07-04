"""Locates the clang binary used by both frontend.py and backend.py."""
import os
import shutil

_FALLBACK_PATHS = [
    r"C:\Program Files\LLVM\bin\clang.exe",
    "/usr/bin/clang",
    "/usr/local/bin/clang",
]


def find_clang() -> str:
    env = os.environ.get("OBFUSCATOR_CLANG")
    if env:
        return env
    found = shutil.which("clang")
    if found:
        return found
    for path in _FALLBACK_PATHS:
        if os.path.isfile(path):
            return path
    raise FileNotFoundError(
        "clang not found on PATH. Set OBFUSCATOR_CLANG to its full path."
    )
