"""Command-line entry point chaining the obfuscation passes together.

    python -m obfuscator input.c -o output.exe --passes strenc,subst,bogus,flatten --seed 1234
"""
import argparse
import random
import sys

from .backend import compile_ir_to_binary
from .frontend import compile_to_ir
from .ir_model import parse_module
from .ir_writer import write_module
from .passes import PASSES
from .verify import IRVerificationError, verify_ir

DEFAULT_PASSES = "strenc,subst,bogus,flatten"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="obfuscator", description=__doc__)
    parser.add_argument("source", help="input .c file")
    parser.add_argument("-o", "--output", required=True, help="output executable/object path")
    parser.add_argument(
        "--passes", default=DEFAULT_PASSES,
        help=f"comma-separated pass names to apply in order (available: {', '.join(PASSES)}), "
             f"default: {DEFAULT_PASSES}",
    )
    parser.add_argument("--seed", type=int, default=None, help="RNG seed for reproducible output")
    parser.add_argument(
        "--emit-ir", metavar="PATH",
        help="also write the final obfuscated .ll IR text to PATH",
    )
    return parser


def run(args=None) -> int:
    parser = build_arg_parser()
    opts = parser.parse_args(args)

    pass_names = [p.strip() for p in opts.passes.split(",") if p.strip()]
    unknown = [p for p in pass_names if p not in PASSES]
    if unknown:
        parser.error(f"unknown pass(es): {', '.join(unknown)} (available: {', '.join(PASSES)})")

    rng = random.Random(opts.seed)

    ir_text = compile_to_ir(opts.source)
    module = parse_module(ir_text)

    for name in pass_names:
        PASSES[name](rng).run(module)

    rendered = write_module(module)

    try:
        verify_ir(rendered)
    except IRVerificationError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if opts.emit_ir:
        with open(opts.emit_ir, "w") as f:
            f.write(rendered)

    compile_ir_to_binary(rendered, opts.output)
    return 0


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
