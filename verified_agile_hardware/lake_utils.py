from verified_agile_hardware.solver import Solver, Rewriter
from verified_agile_hardware.yosys_utils import mem_tile_to_btor
from verified_agile_hardware.configure_mem_tile import MemtileConfig
from _kratos import create_wrapper_flatten
import os
import magma
import kratos as kts
import json


def get_mem_btor_outputs(solver, btor_filename):
    output_symbols = {}
    with open(btor_filename) as f:
        for line in f:
            if " output " in line:
                output_var = line.split()[3]
                output_symbols[output_var] = solver.fts.lookup(output_var)

    return output_symbols


def get_mem_inputs(solver, mem_name):
    input_vars = []
    for i in solver.fts.inputvars:
        solver.fts.promote_inputvar(i)
        if mem_name in str(i):
            input_vars.append(i)

    input_vars = sorted(input_vars, key=lambda x: str(x))

    input_dict = {}
    for i in input_vars:
        input_dict[str(i)] = i

    return input_dict


def get_mem_sram_var(solver, mem_name, sram_name="data_array"):
    sram_vars = []
    for sv in solver.fts.statevars:
        if sram_name in str(sv) and mem_name in str(sv):
            sram_vars.append(sv)

    assert len(sram_vars) == 1, f"Wrong number of SRAMs found: {len(sram_vars)}"

    return sram_vars[0]


def config_rom(solver, mem_name, rom_val):
    sram_var = get_mem_sram_var(solver, mem_name)
    sort = sram_var.get_sort()
    index_sort = sort.get_indexsort()
    element_sort = sort.get_elemsort()

 
    packed_rom_val = []
    for i in range(0, len(rom_val), 4):
        packed_rom_val.append(0)
        for j in range(4):
            if i + j >= len(rom_val):
                break
            packed_rom_val[i // 4] = packed_rom_val[i // 4] | (
                rom_val[i + j] << (j * 16)
            )

    for i, val in enumerate(packed_rom_val):
        sram_var = solver.create_term(
            solver.ops.Store,
            sram_var,
            solver.create_term(i, index_sort),
            solver.create_term(val, element_sort),
        )

    solver.fts.add_invar(
        solver.create_term(
            solver.ops.Equal, sram_var, get_mem_sram_var(solver, mem_name)
        )
    )


def produce_configed_memtile_verilog(solver, mem_tile, configs, mem_name):
    config_dict = {c1[0]: (c0[1], c1[1].width) for c0, c1 in configs}

    # I cant get kratos to behave so I'll codegen raw verilog
    inputs_and_bw = []
    outputs_and_bw = []

    for port in mem_tile.dut.ports:
        direction = mem_tile.dut.ports[port].port_direction
        bw = mem_tile.dut.ports[port].width
        name = mem_tile.dut.ports[port].name
        packed = mem_tile.dut.ports[port].is_packed
        size = mem_tile.dut.ports[port].size[0]
        if direction == kts.PortDirection.In:
            inputs_and_bw.append((name, bw, packed, size))
        else:
            outputs_and_bw.append((name, bw, packed, size))

    verilog = f"""module {mem_name} (\n"""

    for in_, bw, packed, size in inputs_and_bw:
        if in_ in config_dict:
            continue
        in_ += f"_{mem_name}"
        if packed:
            verilog += f"input wire [{size-1}:0] [{bw-1}:0] {in_},\n"
        else:
            verilog += f"input wire [{bw-1}:0] {in_},\n"

    for in_, bw, packed, size in outputs_and_bw:
        in_ += f"_{mem_name}"
        if packed:
            verilog += f"output wire [{size-1}:0] [{bw-1}:0] {in_},\n"
        else:
            verilog += f"output wire [{bw-1}:0] {in_},\n"

    verilog += ");\n"

    verilog += f"{mem_tile.dut.name} {mem_tile.dut.name}_{mem_name} (\n"

    for in_, bw, packed, size in inputs_and_bw:
        if in_ in config_dict:
            verilog += f".{in_}({config_dict[in_][1]}'d{config_dict[in_][0]}),\n"
        else:
            verilog += f".{in_}({in_}_{mem_name}),\n"

    for in_, bw, packed, size in outputs_and_bw:
        verilog += f".{in_}({in_}_{mem_name}),\n"

    verilog += ");\n"
    verilog += "endmodule\n"

    with open(f"{solver.app_dir}/{mem_name}_configed.sv", "w") as f:
        f.write(verilog)


def load_new_mem_tile(solver, mem_name, mem_tile, configs):
    # Write kratos configs to configure mem tile
    produce_configed_memtile_verilog(solver, mem_tile, configs, mem_name)

    unique = solver.num_memtiles + 12345
    solver.num_memtiles += 1

    btor_file_t = f"{solver.app_dir}/{mem_name}_configed_temp.btor"
    btor_file = f"{solver.app_dir}/{mem_name}_configed.btor"

    mem_tile_to_btor(
        solver.app_dir,
        "/aha/garnet/garnet.v",
        f"{solver.app_dir}/{mem_name}_configed.sv",
        mem_tile_module=f"{mem_name}",
        btor_filename=btor_file_t,
    )

    f = open(btor_file_t, "r")
    lines = f.readlines()
    f.close()

    rewritten_terms = {}

    for l_idx, line in enumerate(lines):
        split_lines = line.split()
        if split_lines[0].isnumeric():
            rewritten_terms[split_lines[0]] = str(unique) + split_lines[0]

        for s_idx, s in enumerate(split_lines):
            if "sort" == split_lines[1] and s_idx > 1 and "array" != split_lines[2]:
                continue

            if "const" == split_lines[1] and s_idx > 2:
                continue

            if ("uext" == split_lines[1] or "sext" == split_lines[1]) and s_idx > 3:
                continue

            if "slice" == split_lines[1] and s_idx > 3:
                continue

            if s in rewritten_terms:
                split_lines[s_idx] = rewritten_terms[s]

        lines[l_idx] = " ".join(split_lines) + "\n"

    f = open(btor_file, "w")
    f.writelines(lines)
    f.close()

    solver.read_btor2(btor_file)

    mem_inputs = get_mem_inputs(solver, mem_name)

    return mem_inputs, get_mem_btor_outputs(solver, btor_file)
