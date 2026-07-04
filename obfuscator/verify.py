"""Validates IR text via llvmlite before handing it to the backend, so a
malformed transform fails with a clear Python error instead of a cryptic
clang crash."""
import llvmlite.binding as llvm


class IRVerificationError(RuntimeError):
    pass


def verify_ir(ir_text: str) -> None:
    try:
        mod = llvm.parse_assembly(ir_text)
        mod.verify()
    except RuntimeError as e:
        raise IRVerificationError(f"Generated IR failed verification: {e}") from e
