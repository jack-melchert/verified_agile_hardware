from verified_agile_hardware.solver import Solver
from verified_agile_hardware.yosys_utils import mem_tile_to_btor
import pytest


def test_mem_tile_btor_file():
    solver = Solver()
    solver.read_btor2("examples/mem_core.btor2")

def test_mem_tile_yosys():
    mem_tile_to_btor()
