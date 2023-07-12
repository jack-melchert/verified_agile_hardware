import pytest
from verified_agile_hardware.coreir_utils import (
    read_coreir,
    coreir_to_nx,
    coreir_to_pdf,
    nx_to_smt,
)


@pytest.mark.parametrize(
    "coreir_file",
    [
        "examples/pointwise.json",
        "examples/gaussian.json",
        "examples/three_level_pond.json",
    ],
)
def test_load_coreir(coreir_file):
    read_coreir(coreir_file)


@pytest.mark.parametrize(
    "coreir_file",
    [
        "examples/pointwise.json",
        "examples/gaussian.json",
        "examples/three_level_pond.json",
    ],
)
def test_coreir_to_nx(coreir_file):
    coreir_to_nx(read_coreir(coreir_file))


@pytest.mark.parametrize(
    "coreir_file",
    [
        "examples/pointwise.json",
        "examples/gaussian.json",
        "examples/three_level_pond.json",
    ],
)
def test_coreir_to_pdf(coreir_file):
    nx = coreir_to_nx(read_coreir(coreir_file))
    coreir_to_pdf(nx, "examples/coreir_output")


@pytest.mark.parametrize(
    "coreir_file",
    [
        "examples/pointwise.json",
        "examples/gaussian.json",
        "examples/three_level_pond.json",
    ],
)
def test_nx_to_smt(coreir_file):
    nx = coreir_to_nx(read_coreir(coreir_file))
    nx_to_smt(nx)
