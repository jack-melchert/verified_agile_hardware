from verified_agile_hardware.solver import Solver, Rewriter
from verified_agile_hardware.yosys_utils import mem_tile_to_btor
from verified_agile_hardware.configure_mem_tile import MemtileConfig
from _kratos import create_wrapper_flatten
import os
import magma
import kratos as kts
import json


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


def produce_configed_memtile_verilog(solver, mem_tile, configs, mem_name):
    config_dict = {c1[0]: (c0[1], c1[1].width) for c0, c1 in configs}

    # I cant get kratos to behave so I'll codegen raw verilog
    inputs_and_bw = []
    outputs_and_bw = []

    for port in mem_tile.core.dut.ports:
        direction = mem_tile.core.dut.ports[port].port_direction
        bw = mem_tile.core.dut.ports[port].width
        name = mem_tile.core.dut.ports[port].name
        packed = mem_tile.core.dut.ports[port].is_packed
        size = mem_tile.core.dut.ports[port].size[0]
        if direction == kts.PortDirection.In:
            inputs_and_bw.append((name, bw, packed, size))
        else:
            outputs_and_bw.append((name, bw, packed, size))

    verilog = f"""module {mem_name} (\n"""

    for in_, bw, packed, size in inputs_and_bw:
        if in_ in config_dict:
            continue
        if packed:
            verilog += f"input wire [{size-1}:0] [{bw-1}:0] {in_},\n"
        else:
            verilog += f"input wire [{bw-1}:0] {in_},\n"

    for in_, bw, packed, size in outputs_and_bw:
        if packed:
            verilog += f"output wire [{size-1}:0] [{bw-1}:0] {in_},\n"
        else:
            verilog += f"output wire [{bw-1}:0] {in_},\n"

    verilog += ");\n"

    verilog += f"{mem_tile.core.dut.name} {mem_tile.core.dut.name}_inst (\n"

    for in_, bw, packed, size in inputs_and_bw:
        if in_ in config_dict:
            verilog += f".{in_}({config_dict[in_][1]}'d{config_dict[in_][0]}),\n"
        else:
            verilog += f".{in_}({in_}),\n"

    for in_, bw, packed, size in outputs_and_bw:
        verilog += f".{in_}({in_}),\n"

    verilog += ");\n"
    verilog += "endmodule\n"

    # write verilog to file
    with open(f"{solver.app_dir}/{mem_name}_configed.sv", "w") as f:
        f.write(verilog)

    # kts_mem_tile = MemtileConfig(mem_name, mem_tile, configs)
    # kts_mem_tile = kts.Generator(f"{mem_name}_config", internal_generator=mem_tile.core.dut.internal_generator)

    # flattened = create_wrapper_flatten(mem_tile.core.dut.internal_generator, f"{mem_name}")
    # flattened_gen = kts.Generator(f"{mem_name}", internal_generator=flattened)
    # import _kratos
    # _kratos.passes.create_module_instantiation(mem_tile.core.dut.internal_generator)
    # breakpoint()
    # kts.Generator.clear_context_hash()
    # kts.verilog(flattened_gen, filename=f"{solver.app_dir}/{mem_name}_configed.sv")

    # Write configs to file
    # config_file = f"{solver.app_dir}/{mem_name}_config.json"
    # write_config = configs["config"]
    # write_config["mode"] = "UB"

    # with open(config_file, "w") as f:
    #     json.dump(write_config, f, indent=4)

    # kts.Generator.clear_context_hash()
    # mem_tile.core.CC.wrapper(
    #     wrapper_vlog_filename=f"{solver.app_dir}/{mem_name}_configed.sv",
    #     wrapper_vlog_modulename=f"{mem_name}_config",
    #     config_path=config_file,
    #     externally_define=False,
    # )
    # breakpoint()


def load_new_mem_tile(solver, mem_name, mem_tile, configs):
    # Write kratos configs to configure mem tile
    produce_configed_memtile_verilog(solver, mem_tile, configs, mem_name)

    btor_file = f"{solver.app_dir}/{mem_name}_configed.btor"

    mem_tile_to_btor(
        solver.app_dir,
        "/aha/garnet/garnet.v",
        f"{solver.app_dir}/{mem_name}_configed.sv",
        mem_tile_module=f"{mem_name}",
        btor_filename=btor_file,
    )

    if not solver.mem_tile_vars:
        solver.read_btor2(btor_file)
        solver.mem_tile_vars = get_mem_btor_outputs(solver, btor_file)
        solver.mem_tile_vars.update(solver.fts.state_updates)

    r0 = Rewriter(solver, solver.mem_tile_vars.values(), f"_{mem_name}")
    r0.rewrite()

    mem_inputs = get_mem_inputs(solver, f"_{mem_name}")

    return r0, mem_inputs, get_mem_btor_outputs(solver, btor_file, f"_{mem_name}")
