from verified_agile_hardware.solver import Solver, Rewriter
from verified_agile_hardware.yosys_utils import mem_tile_to_btor
from verified_agile_hardware.lake_utils import load_new_mem_tile
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
    "mem_file, mem_module, mem_output_file",
    [
        ("examples/simple_mem.v", "regfile", "examples/RamChip.btor2"),
        ("/aha/garnet/garnet.v", "MemCore_inner", "examples/MemCore_inner.btor2"),
        ("/aha/garnet/garnet.v", "PondTop", "examples/PondTop.btor2"),
    ],
)
def test_loading_multiple_mems(mem_file, mem_module, mem_output_file):
    solver = Solver()

    r0, r0_inputs, r0_outputs = load_new_mem_tile(
        solver, mem_file, mem_module, mem_output_file, "_memtile0"
    )
    r1, r1_inputs, r1_outputs = load_new_mem_tile(
        solver, mem_file, mem_module, mem_output_file, "_memtile1"
    )

    solver.assert_formula(solver.ur.at_time(solver.fts.init, 0))

    cycles = 5

    for i in range(cycles + 1):
        solver.assert_formula(solver.ur.at_time(solver.fts.trans, i))
        for i0, i1 in zip(r0_inputs.values(), r1_inputs.values()):
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

    for out_0, out_1 in zip(r0_outputs.values(), r1_outputs.values()):
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

    assert solver.check_sat().is_unsat()
