from verified_agile_hardware.solver import Solver, Rewriter
from verified_agile_hardware.yosys_utils import mem_tile_to_btor
from verified_agile_hardware.lake_utils import load_new_mem_tile
import pytest
import smt_switch as ss
import pono


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
def test_bmc_mem_tile(mem_file):
    solver = Solver()
    solver.read_btor2(mem_file)

    bvsort16 = solver.create_bvsort(16)

    prop = pono.Property(
        solver.solver,
        solver.create_term(
            solver.ops.Equal,
            solver.create_term(0, bvsort16),
            solver.create_term(0, bvsort16),
        ),
    )

    bmc = pono.Bmc(prop, solver.fts, solver.solver)
    res = bmc.check_until(2)

    assert res is None
