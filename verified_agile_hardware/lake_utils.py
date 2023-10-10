from verified_agile_hardware.solver import Solver, Rewriter
from verified_agile_hardware.yosys_utils import mem_tile_to_btor
import os


def get_mem_btor_outputs(solver, btor_filename, mem_name=""):
    output_symbols = {}
    with open(btor_filename) as f:
        for line in f:
            if " output " in line:
                output_var = line.split()[3]
                output_symbols[output_var + mem_name] = solver.fts.lookup(
                    output_var + mem_name
                )

    return output_symbols


def get_mem_inputs(solver, mem_name):
    input_vars = []
    for i in solver.fts.inputvars:
        if mem_name in str(i):
            input_vars.append(i)

    input_vars = sorted(input_vars, key=lambda x: str(x))

    input_dict = {}
    for i in input_vars:
        input_dict[str(i)] = i
    return input_dict


def load_new_mem_tile(solver, mem_file, mem_module, btor_file, mem_name):
    if not os.path.isfile(btor_file):
        mem_tile_to_btor(mem_file, mem_tile_module=mem_module, btor_filename=btor_file)

    if not solver.mem_tile_vars:
        solver.read_btor2(btor_file)
        solver.mem_tile_vars = get_mem_btor_outputs(solver, btor_file)
        solver.mem_tile_vars.update(solver.fts.state_updates)

    r0 = Rewriter(solver, solver.mem_tile_vars.values(), mem_name)
    r0.rewrite()

    mem_inputs = get_mem_inputs(solver, mem_name)

    return r0, mem_inputs, get_mem_btor_outputs(solver, btor_file, mem_name)


# def create_mem_tile_lake():
#     mem_width = 64
#     mem_depth = 512
#     fifo_depth = 2
#     pipeline_scanner = True
#     perf_debug = False


#     strg_ub = StrgUBVec(data_width=16,
#                                     mem_width=mem_width,
#                                     mem_depth=mem_depth)

#     fiber_access = FiberAccess(data_width=16,
#                                 local_memory=False,
#                                 tech_map=GF_Tech_Map(depth=mem_depth, width=32, dual_port=False),
#                                 defer_fifos=True,
#                                 add_flush=False,
#                                 use_pipelined_scanner=pipeline_scanner,
#                                 fifo_depth=fifo_depth,
#                                 buffet_optimize_wide=True,
#                                 perf_debug=perf_debug)

#     strg_ram = StrgRAM(data_width=16,
#                         banks=1,
#                         memory_width=mem_width,
#                         memory_depth=mem_depth,
#                         rw_same_cycle=False,
#                         read_delay=1,
#                         addr_width=16,
#                         prioritize_write=True,
#                         comply_with_17=True)

#     stencil_valid = StencilValid()

#     controllers = []

#     controllers.append(fiber_access)
#     controllers.append(strg_ub)
#     controllers.append(strg_ram)
#     controllers.append(stencil_valid)

#     mem_tile_core_combiner = {'controllers_list': controllers,
#         'use_sim_sram': True,
#         'tech_map': GF_Tech_Map(depth=mem_depth, width=32, dual_port=False),
#         'pnr_tag': "m",
#         'mem_width': mem_width,
#         'mem_depth': mem_depth,
#         'name': "MemCore",
#         'input_prefix': "MEM_",
#         'fifo_depth': fifo_depth,
#         'dual_port': False,
#         'rf': False}

#     core = CoreCombinerCore(**mem_tile_core_combiner)
#     core.finalize()
#     return core
