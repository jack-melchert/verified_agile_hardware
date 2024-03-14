from verified_agile_hardware.solver import Solver, Rewriter
from verified_agile_hardware.yosys_utils import mem_tile_to_btor
from verified_agile_hardware.configure_mem_tile import MemtileConfig
from _kratos import create_wrapper_flatten
from lake.models.addr_gen_model import AddrGenModel
import os
import magma
import kratos as kts
import json
import smt_switch as ss


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


def produce_configed_memtile_verilog(
    app_dir, mem_tile, config_dict, mem_name, used_inputs, used_outputs
):

    # always used
    used_inputs += ["clk", "flush", "rst_n"]

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
        if in_ in config_dict or in_ not in used_inputs:
            continue
        in_ += f"_{mem_name}"
        if packed:
            verilog += f"input wire [{size-1}:0] [{bw-1}:0] {in_},\n"
        else:
            verilog += f"input wire [{bw-1}:0] {in_},\n"

    for out_, bw, packed, size in outputs_and_bw:
        if out_ not in used_outputs:
            continue
        out_ += f"_{mem_name}"
        if packed:
            verilog += f"output wire [{size-1}:0] [{bw-1}:0] {out_},\n"
        else:
            verilog += f"output wire [{bw-1}:0] {out_},\n"

    verilog += ");\n"

    for in_, bw, packed, size in inputs_and_bw:
        if in_ in config_dict or in_ in used_inputs:
            continue
        in_ += f"_{mem_name}"
        if packed:
            verilog += f"wire [{size-1}:0] [{bw-1}:0] {in_};\n"
        else:
            verilog += f"wire [{bw-1}:0] {in_};\n"

    for out_, bw, packed, size in outputs_and_bw:
        if out_ in used_outputs:
            continue
        out_ += f"_{mem_name}"
        if packed:
            verilog += f"wire [{size-1}:0] [{bw-1}:0] {out_};\n"
        else:
            verilog += f"wire [{bw-1}:0] {out_};\n"

    verilog += f"{mem_tile.dut.name} {mem_tile.dut.name}_{mem_name} (\n"

    for in_, bw, packed, size in inputs_and_bw:
        if in_ in config_dict:
            verilog += f".{in_}({bw}'d{config_dict[in_]}),\n"
        else:
            verilog += f".{in_}({in_}_{mem_name}),\n"

    for in_, bw, packed, size in outputs_and_bw:
        verilog += f".{in_}({in_}_{mem_name}),\n"

    verilog += ");\n"
    verilog += "endmodule\n"

    with open(f"{app_dir}/{mem_name}_configed.sv", "w") as f:
        f.write(verilog)


def load_new_mem_tile(
    solver, mem_name, mem_tile, config_dict, used_inputs, used_outputs
):
    # Write kratos config_dict to configure mem tile
    produce_configed_memtile_verilog(
        solver.app_dir, mem_tile, config_dict, mem_name, used_inputs, used_outputs
    )

    unique = solver.num_memtiles + 12345  # this is stupid
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


def constrain_cycle_starting_addr(solver, mem_name, metadata):

    cycle_starting_addrs = {}

    for controller, config in metadata["config"].items():
        cycle_starting_addrs[controller] = config["cycle_starting_addr"][0]

    for name, term in solver.fts.named_terms.items():
        if "addr_out" in name and mem_name in name:
            for controller, addr in cycle_starting_addrs.items():
                if controller in name:
                    solver.fts.constrain_init(
                        solver.create_term(
                            solver.ops.Equal,
                            term,
                            solver.create_const(addr, term.get_sort()),
                        )
                    )
                    print(f"Constraining {name} to {addr}")


def mem_tile_constraint_generator(
    solver, memtile_name, config_dict, cycles, iterator_support=2
):

    for controller, config in config_dict["config"].items():
        addr_out, dim_out = mem_tile_addr_dim_values(config, cycles, iterator_support)
        for name, term in solver.fts.named_terms.items():
            if (
                "addr_out" in name
                and memtile_name in name
                and controller in name
                and not solver.fts.is_next_var(term)
            ):
                addr_out_type = term.get_sort()

                # Create LUT for addr_out and dim_out
                addr_out_var = solver.create_fts_state_var(
                    f"{memtile_name}_address_out",
                    solver.solver.make_sort(
                        ss.sortkinds.ARRAY, solver.create_bvsort(16), addr_out_type
                    ),
                )

                for i, addr in enumerate(addr_out):
                    addr_out_var = solver.create_term(
                        solver.ops.Store,
                        addr_out_var,
                        solver.create_const(i, solver.create_bvsort(16)),
                        solver.create_const(addr, addr_out_type),
                    )

                starting_addr = solver.create_term(
                    solver.ops.Select, addr_out_var, solver.cycle_count
                )

                solver.fts.add_invar(
                    solver.create_term(solver.ops.Equal, term, starting_addr)
                )

            if (
                "dim_counter" in name
                and memtile_name in name
                and controller in name
                and not solver.fts.is_next_var(term)
            ):
                dim_cnt_type = term.get_sort()

                # Create LUT for dim_cnt and dim_out
                dim_cnt_var = solver.create_fts_state_var(
                    f"{memtile_name}_dimemsion_cnt",
                    solver.solver.make_sort(
                        ss.sortkinds.ARRAY, solver.create_bvsort(16), dim_cnt_type
                    ),
                )

                for i, dim_cnt in enumerate(dim_out):
                    dm_sort = dim_cnt_type.get_width() // len(dim_cnt)

                    dim_cnt_concat = 0

                    for dc_idx, dc in enumerate(dim_cnt):
                        dim_cnt_concat += dc << (dc_idx * dm_sort)

                    dim_cnt_var = solver.create_term(
                        solver.ops.Store,
                        dim_cnt_var,
                        solver.create_const(i, solver.create_bvsort(16)),
                        solver.create_const(dim_cnt_concat, dim_cnt_type),
                    )

                starting_dim_cnt = solver.create_term(
                    solver.ops.Select, dim_cnt_var, solver.cycle_count
                )

                solver.fts.constrain_init(
                    solver.create_term(solver.ops.Equal, term, starting_dim_cnt)
                )


def mem_tile_addr_dim_values(config, cycles, iterator_support=2):

    model_ag = AddrGenModel(iterator_support=iterator_support, address_width=16)

    transformed_config = {}

    transformed_config["starting_addr"] = config["cycle_starting_addr"][0]
    transformed_config["dimensionality"] = config["dimensionality"]
    for i in range(config["dimensionality"]):
        transformed_config[f"strides_{i}"] = config["cycle_stride"][i]
        transformed_config[f"ranges_{i}"] = config["extent"][i]

    model_ag.set_config(transformed_config)

    addr_out = []
    dim_out = []

    for cycle in range(cycles):
        addr_out.append(model_ag.get_address())
        dim_out.append(model_ag.dim_cnt.copy())

        if cycle == model_ag.get_address():
            model_ag.step()

        cycle += 1

    return addr_out, dim_out
