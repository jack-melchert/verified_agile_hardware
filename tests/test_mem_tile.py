from verified_agile_hardware.solver import Solver
from verified_agile_hardware.yosys_utils import mem_tile_to_btor
from verified_agile_hardware.lake_utils import get_mem_btor_outputs
import pytest
import smt_switch as ss


def test_mem_tile_yosys():
    mem_tile_to_btor()


def test_mem_tile_btor_file():
    solver = Solver()
    solver.read_btor2("examples/mem_core.btor2")


def test_multi_mem_tile():
    btor_filename = "examples/mem_core.btor2"
    solver = Solver()
    solver.read_btor2(btor_filename)

    input_sorts = []
    for var in solver.fts.inputvars:
        input_sorts.append(var.get_sort())

    output_vars = []
    output_var_names = get_mem_btor_outputs(btor_filename)
    for var in output_var_names:
        output_vars.append((solver.fts.lookup(var), solver.fts.lookup(var).get_sort()))

    output_sorts = [s[1] for s in output_vars]

    # concatenate all outputs
    assembled_output = solver.create_term(
        ss.primops.Concat, *[s[0] for s in output_vars]
    )
    assembled_output_width = sum([s.get_width() for s in output_sorts])

    f = solver.create_symbol(
        "f",
        solver.create_sort(
            ss.sortkinds.FUNCTION,
            input_sorts + [solver.create_bvsort(assembled_output_width)],
        ),
    )

    # for all inputs, outputs. f(inputs) = outputs
    fx = solver.create_term(ss.primops.Apply, f, *solver.fts.inputvars)
    # solver.assert_formula(solver.create_term(ss.primops.Forall, *solver.fts.inputvars, *solver.fts.statevars, fx))
    # solver.assert_formula(
    #     solver.create_term(
    #         ss.primops.Forall,
    #         *solver.fts.inputvars,
    #         *solver.fts.statevars,
    #         solver.create_term(solver.ops.Equal, fx, assembled_output)
    #     )
    # )
