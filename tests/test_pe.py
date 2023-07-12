from hwtypes import BitVector, Product, Enum, SMTBitVector
from peak import family_closure, Peak, family
from peak.assembler.assembler import Assembler
from peak.assembler.assembled_adt import AssembledADT
from peak.mapper.utils import aadt_product_to_dict, rebind_type


@family_closure
def PE_fc(family):
    Data = BitVector[8]

    @family.assemble(locals(), globals())
    class PE(Peak):
        def __call__(self, x: Data) -> Data:
            return family.BitVector[8](0)

    return PE


def create_input(T):
    aadt_t = AssembledADT[T, Assembler, SMTBitVector]
    width = Assembler(T).width
    aadt_val = aadt_t(SMTBitVector[width]())
    return aadt_product_to_dict(aadt_val)


def _get_aadt(T):
    T = rebind_type(T, family.SMTFamily())
    return family.SMTFamily().get_adt_t(T)


def test_pe_to_smt():
    PE_smt = PE_fc(family.SMTFamily())
    inputs = create_input(PE_smt.input_t)
    outputs = PE_smt()(**inputs)

    if not isinstance(outputs, tuple):
        outputs = (outputs,)

    aadt = _get_aadt(PE_fc.Py.output_t)
    output_val = aadt.from_fields(*outputs)
