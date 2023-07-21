from hwtypes import BitVector
from peak import family_closure, Peak, family
from verified_agile_hardware.solver import Solver
from verified_agile_hardware.peak_utils import (
    create_input,
    load_pe_tile,
    get_aadt,
    get_pe_inputs,
    get_pe_state,
)
from lassen import PE_fc as lassen_fc
from examples.sum_pe.sim import PE_fc as PE_fc_s
import smt_switch as ss


@family_closure
def PE_fc(family):
    Data = BitVector[8]

    @family.assemble(locals(), globals())
    class PE(Peak):
        def __call__(self, x: Data) -> Data:
            return x + family.BitVector[8](1)

    return PE


def test_pe_to_smt():
    PE_smt = PE_fc(family.SMTFamily())
    inputs = create_input(PE_smt.input_t)
    outputs = PE_smt()(**inputs)

    if not isinstance(outputs, tuple):
        outputs = (outputs,)

    aadt = get_aadt(PE_fc.Py.output_t)
    output_val = aadt.from_fields(*outputs)


def test_pe_to_pono():
    solver = Solver()

    PE_smt = PE_fc(family.SMTFamily())
    inputs = create_input(PE_smt.input_t)
    outputs = PE_smt()(**inputs)

    if not isinstance(outputs, tuple):
        outputs = (outputs,)

    aadt = get_aadt(PE_fc.Py.output_t)
    output_val = aadt.from_fields(*outputs)

    output = solver.convert(output_val._value_.value)


def test_lassen_to_pono():
    solver = Solver()
    pe0, bboxes0 = load_pe_tile(solver, lassen_fc, pe_name="pe0")
    pe1, bboxes1 = load_pe_tile(solver, lassen_fc, pe_name="pe1")

    solver.assert_formula(solver.ur.at_time(solver.fts.init, 0))

    cycles = 3

    for i in range(cycles + 1):
        solver.assert_formula(solver.ur.at_time(solver.fts.trans, i))
        for i0, i1 in zip(get_pe_inputs(solver, "pe0"), get_pe_inputs(solver, "pe1")):
            solver.assert_formula(
                solver.create_term(
                    solver.ops.Equal, solver.ur.at_time(i0, i), solver.ur.at_time(i1, i)
                )
            )

        for reg in get_pe_state(solver, "pe0") + get_pe_state(solver, "pe1"):
            if reg.get_sort().get_sort_kind() == ss.sortkinds.BOOL:
                solver.assert_formula(
                    solver.create_term(
                        solver.ops.Equal,
                        solver.ur.at_time(reg, i),
                        solver.solver.make_term(False),
                    )
                )
            else:
                solver.assert_formula(
                    solver.create_term(
                        solver.ops.Equal,
                        solver.ur.at_time(reg, i),
                        solver.create_const(0, reg.get_sort()),
                    )
                )

    bbox_types_to_ins_outs = bboxes0
    for k, v in bboxes1.items():
        if k in bbox_types_to_ins_outs:
            bbox_types_to_ins_outs[k] += v
        else:
            bbox_types_to_ins_outs[k] = v

    for idx, (k, v) in enumerate(bbox_types_to_ins_outs.items()):
        bvs = v[0][0][0].get_sort()
        func = solver.solver.make_sort(ss.sortkinds.FUNCTION, [bvs, bvs, bvs])
        f = solver.solver.make_symbol(f"bb{idx}", func)
        for ins, outs in v:
            func_form = solver.solver.make_term(ss.primops.Apply, f, ins[0], ins[1])
            solver.solver.assert_formula(
                solver.solver.make_term(ss.primops.Equal, outs[0], func_form)
            )

    solver.assert_formula(
        solver.create_term(
            solver.ops.Not,
            solver.create_term(
                solver.ops.Equal,
                solver.ur.at_time(pe0, cycles),
                solver.ur.at_time(pe1, cycles),
            ),
        )
    )

    assert solver.check_sat().is_unsat()
