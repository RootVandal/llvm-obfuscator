from .string_encryption import StringEncryptionPass
from .instruction_substitution import InstructionSubstitutionPass
from .bogus_control_flow import BogusControlFlowPass
from .control_flow_flattening import ControlFlowFlatteningPass

PASSES = {
    "strenc": StringEncryptionPass,
    "subst": InstructionSubstitutionPass,
    "bogus": BogusControlFlowPass,
    "flatten": ControlFlowFlatteningPass,
}

__all__ = [
    "StringEncryptionPass",
    "InstructionSubstitutionPass",
    "BogusControlFlowPass",
    "ControlFlowFlatteningPass",
    "PASSES",
]
