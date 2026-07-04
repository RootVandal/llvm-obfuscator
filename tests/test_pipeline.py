"""Proves the parse -> render -> verify -> compile -> run plumbing works
with zero obfuscation passes applied, before any transform logic exists."""
import subprocess
import tempfile
import os

import pytest

from obfuscator.frontend import compile_to_ir
from obfuscator.ir_model import parse_module
from obfuscator.ir_writer import write_module
from obfuscator.verify import verify_ir
from obfuscator.backend import compile_ir_to_binary
from obfuscator.toolchain import find_clang
from conftest import fixture_path, run_binary


FIXTURES = ["hello.c", "branching.c", "strings.c", "loop.c"]


def _compile_and_run_directly(source_path):
    with tempfile.TemporaryDirectory() as tmp:
        exe = os.path.join(tmp, "orig.exe")
        subprocess.run(
            [find_clang(), source_path, "-o", exe], check=True, capture_output=True, text=True
        )
        return run_binary(exe)


@pytest.mark.parametrize("fixture", FIXTURES)
def test_passthrough_matches_direct_compile(fixture, tmp_path):
    source_path = fixture_path(fixture)

    expected_stdout, expected_rc = _compile_and_run_directly(source_path)

    ir_text = compile_to_ir(source_path)
    module = parse_module(ir_text)
    rendered = write_module(module)
    verify_ir(rendered)

    exe_path = str(tmp_path / "roundtrip.exe")
    compile_ir_to_binary(rendered, exe_path)
    actual_stdout, actual_rc = run_binary(exe_path)

    assert actual_stdout == expected_stdout
    assert actual_rc == expected_rc
