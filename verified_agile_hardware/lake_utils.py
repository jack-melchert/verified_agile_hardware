from verified_agile_hardware.solver import Solver, Rewriter
import smt_switch as ss


def get_mem_btor_outputs(btor_filename):
    output_vars = []
    with open(btor_filename) as f:
        for line in f:
            if " output " in line:
                output_vars.append(line.split()[3])
    return output_vars


def get_mem_inputs(solver, mem_name):
    input_vars = []
    for i in solver.fts.inputvars:
        if mem_name in str(i):
            input_vars.append(i)

    input_vars = sorted(input_vars, key=lambda x: str(x))
    return input_vars
