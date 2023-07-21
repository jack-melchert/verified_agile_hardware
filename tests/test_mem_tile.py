from verified_agile_hardware.solver import Solver, Rewriter
from verified_agile_hardware.yosys_utils import mem_tile_to_btor
from verified_agile_hardware.lake_utils import (
    get_mem_btor_outputs,
    get_mem_inputs,
)
import pytest
import smt_switch as ss


@pytest.mark.parametrize(
    "mem_file, mem_module, mem_output_file",
    [
        ("examples/simple_mem.v", "regfile", "examples/RamChip.btor2"),
        ("/aha/garnet/garnet.v", "MemCore_inner", "examples/MemCore_inner.btor2"),
        ("/aha/garnet/garnet.v", "PondTop", "examples/PondTop.btor2"),
    ],
)
def test_mem_tile_yosys(mem_file, mem_module, mem_output_file):
    mem_tile_to_btor(
        mem_file, mem_tile_module=mem_module, btor_filename=mem_output_file
    )


@pytest.mark.parametrize(
    "mem_file",
    [
        "examples/RamChip.btor2",
        "examples/MemCore_inner.btor2",
        "examples/PondTop.btor2",
    ],
)
def test_mem_tile_btor_file(mem_file):
    solver = Solver()
    solver.read_btor2(mem_file)


@pytest.mark.parametrize(
    "mem_file",
    [
        "examples/RamChip.btor2",
        "examples/MemCore_inner.btor2",
        "examples/PondTop.btor2",
    ],
)
def test_loading_multiple_mems(mem_file):
    solver = Solver()

    solver.read_btor2(mem_file)

    outputs = get_mem_btor_outputs(mem_file)

    output_symbols = [solver.fts.lookup(o) for o in outputs]

    state_symbols = solver.fts.state_updates.values()

    output_symbols += state_symbols

    r0 = Rewriter(solver, output_symbols, "_memtile0")
    r1 = Rewriter(solver, output_symbols, "_memtile1")

    r0.rewrite()
    r1.rewrite()

    solver.assert_formula(solver.ur.at_time(solver.fts.init, 0))

    cycles = 10

    for i in range(cycles + 1):
        solver.assert_formula(solver.ur.at_time(solver.fts.trans, i))
        for i0, i1 in zip(
            get_mem_inputs(solver, "memtile0"), get_mem_inputs(solver, "memtile1")
        ):
            solver.assert_formula(
                solver.create_term(
                    solver.ops.Equal, solver.ur.at_time(i0, i), solver.ur.at_time(i1, i)
                )
            )

        for state0, state1 in zip(r0.new_state_vars, r1.new_state_vars):
            solver.assert_formula(
                solver.create_term(
                    solver.ops.Equal,
                    solver.ur.at_time(state0, i),
                    solver.ur.at_time(state1, i),
                )
            )

    for o in outputs:
        out_0 = solver.fts.lookup(o + "_memtile0")
        out_1 = solver.fts.lookup(o + "_memtile1")
        solver.assert_formula(
            solver.create_term(
                solver.ops.Not,
                solver.create_term(
                    solver.ops.Equal,
                    solver.ur.at_time(out_0, cycles),
                    solver.ur.at_time(out_1, cycles),
                ),
            )
        )

    solver.check_sat().is_unsat()
