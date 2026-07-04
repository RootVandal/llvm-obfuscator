"""Runs the full obfuscation pipeline (all four passes chained via the CLI)
against every fixture and proves the compiled-and-run behavior is
unchanged -- the concrete evidence that obfuscation preserved semantics."""
import subprocess

import pytest

from obfuscator.cli import run as cli_run
from obfuscator.toolchain import find_clang
from conftest import fixture_path, run_binary

FIXTURES = ["hello.c", "branching.c", "strings.c", "loop.c"]
SEEDS = [1, 42, 999]


def _direct_compile_and_run(source_path, tmp_path):
    exe = str(tmp_path / "orig.exe")
    subprocess.run(
        [find_clang(), source_path, "-o", exe], check=True, capture_output=True, text=True
    )
    return run_binary(exe)


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("fixture", FIXTURES)
def test_full_pipeline_semantic_equivalence(fixture, seed, tmp_path):
    source_path = fixture_path(fixture)
    expected_stdout, expected_rc = _direct_compile_and_run(source_path, tmp_path)

    out_exe = str(tmp_path / "obfuscated.exe")
    rc = cli_run([source_path, "-o", out_exe, "--seed", str(seed)])
    assert rc == 0

    actual_stdout, actual_rc = run_binary(out_exe)
    assert actual_stdout == expected_stdout
    assert actual_rc == expected_rc


def test_obfuscated_binary_does_not_contain_plaintext_strings(tmp_path):
    source_path = fixture_path("strings.c")
    out_exe = str(tmp_path / "obfuscated.exe")
    rc = cli_run([source_path, "-o", out_exe, "--seed", "7"])
    assert rc == 0

    with open(out_exe, "rb") as f:
        data = f.read()
    for literal in (b"big", b"small", b"done"):
        assert literal not in data


def test_cli_rejects_unknown_pass_name(tmp_path):
    source_path = fixture_path("hello.c")
    out_exe = str(tmp_path / "out.exe")
    with pytest.raises(SystemExit):
        cli_run([source_path, "-o", out_exe, "--passes", "not_a_real_pass"])
