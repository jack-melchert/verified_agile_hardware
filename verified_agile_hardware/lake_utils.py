from verified_agile_hardware.solver import Solver, Rewriter
from verified_agile_hardware.yosys_utils import mem_tile_to_btor
from verified_agile_hardware.configure_mem_tile import MemtileConfig
from verified_agile_hardware.simulate_lake import simulate_mem_tile_counters
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


def mem_tile_constraint_generator(
    solver, memtile_name, config_dict, lake_configs, cycles, iterator_support=2
):

    addr_out, dim_out, read_addr_out, write_addr_out = simulate_mem_tile_counters(
        config_dict, lake_configs, cycles, iterator_support
    )

    addr_out_to_symbol_name = {}
    addr_out_to_symbol_name["stencil_valid_sched_gen_sched_addr_gen"] = (
        "mem_ctrl_stencil_valid_flat.stencil_valid_inst.stencil_valid_sched_gen.addr_out"
    )
    addr_out_to_symbol_name["agg_only_agg_write_sched_gen_0_sched_addr_gen"] = (
        "strg_ub_vec_inst.agg_only.agg_write_sched_gen_0.addr_out"
    )
    addr_out_to_symbol_name["agg_only_agg_write_sched_gen_1_sched_addr_gen"] = (
        "strg_ub_vec_inst.agg_only.agg_write_sched_gen_1.addr_out"
    )
    addr_out_to_symbol_name["sram_tb_shared_output_sched_gen_0_sched_addr_gen"] = (
        "strg_ub_vec_inst.sram_tb_shared.output_sched_gen_0.addr_out"
    )
    addr_out_to_symbol_name["sram_tb_shared_output_sched_gen_1_sched_addr_gen"] = (
        "strg_ub_vec_inst.sram_tb_shared.output_sched_gen_1.addr_out"
    )
    addr_out_to_symbol_name["tb_only_tb_read_sched_gen_0_sched_addr_gen"] = (
        "strg_ub_vec_inst.tb_only.tb_read_sched_gen_0.addr_out"
    )
    addr_out_to_symbol_name["tb_only_tb_read_sched_gen_1_sched_addr_gen"] = (
        "strg_ub_vec_inst.tb_only.tb_read_sched_gen_1.addr_out"
    )

    dim_out_to_symbol_name = {}
    dim_out_to_symbol_name["stencil_valid_sched_gen_sched_addr_gen"] = (
        "mem_ctrl_stencil_valid_flat.stencil_valid_inst.loops_stencil_valid.dim_counter"
    )
    dim_out_to_symbol_name["agg_only_agg_write_sched_gen_0_sched_addr_gen"] = (
        "strg_ub_vec_inst.agg_only.loops_in2buf_0.dim_counter"
    )
    dim_out_to_symbol_name["agg_only_agg_write_sched_gen_1_sched_addr_gen"] = (
        "strg_ub_vec_inst.agg_only.loops_in2buf_1.dim_counter"
    )
    dim_out_to_symbol_name["sram_tb_shared_output_sched_gen_0_sched_addr_gen"] = (
        "strg_ub_vec_inst.sram_tb_shared.loops_buf2out_autovec_read_0.dim_counter"
    )
    dim_out_to_symbol_name["sram_tb_shared_output_sched_gen_1_sched_addr_gen"] = (
        "strg_ub_vec_inst.sram_tb_shared.loops_buf2out_autovec_read_1.dim_counter"
    )
    dim_out_to_symbol_name["tb_only_tb_read_sched_gen_0_sched_addr_gen"] = (
        "strg_ub_vec_inst.tb_only.loops_buf2out_read_0.dim_counter"
    )
    dim_out_to_symbol_name["tb_only_tb_read_sched_gen_1_sched_addr_gen"] = (
        "strg_ub_vec_inst.tb_only.loops_buf2out_read_1.dim_counter"
    )

    read_addr_out_to_symbol_name = {}
    read_addr_out_to_symbol_name["sram_tb_shared_output_sched_gen_0_sched_addr_gen"] = (
        "strg_ub_vec_inst.sram_only.output_addr_gen_0.addr_out"
    )
    read_addr_out_to_symbol_name["sram_tb_shared_output_sched_gen_1_sched_addr_gen"] = (
        "strg_ub_vec_inst.sram_only.output_addr_gen_1.addr_out"
    )
    read_addr_out_to_symbol_name["tb_only_tb_read_sched_gen_0_sched_addr_gen"] = (
        "strg_ub_vec_inst.tb_only.tb_read_addr_gen_0.addr_out"
    )
    read_addr_out_to_symbol_name["tb_only_tb_read_sched_gen_1_sched_addr_gen"] = (
        "strg_ub_vec_inst.tb_only.tb_read_addr_gen_1.addr_out"
    )
    read_addr_out_to_symbol_name["agg_only_agg_write_sched_gen_0_sched_addr_gen"] = (
        "strg_ub_vec_inst.agg_sram_shared.agg_sram_shared_addr_gen_0.lin_addr_cnter"
    )
    read_addr_out_to_symbol_name["agg_only_agg_write_sched_gen_1_sched_addr_gen"] = (
        "strg_ub_vec_inst.agg_sram_shared.agg_sram_shared_addr_gen_1.lin_addr_cnter"
    )

    write_addr_out_to_symbol_name = {}
    write_addr_out_to_symbol_name["agg_only_agg_write_sched_gen_0_sched_addr_gen"] = (
        "strg_ub_vec_inst.agg_only.agg_write_addr_gen_0.addr_out"
    )
    write_addr_out_to_symbol_name["agg_only_agg_write_sched_gen_1_sched_addr_gen"] = (
        "strg_ub_vec_inst.agg_only.agg_write_addr_gen_1.addr_out"
    )
    write_addr_out_to_symbol_name[
        "sram_tb_shared_output_sched_gen_0_sched_addr_gen"
    ] = "strg_ub_vec_inst.tb_only.tb_write_addr_gen_0.addr_out"
    write_addr_out_to_symbol_name[
        "sram_tb_shared_output_sched_gen_1_sched_addr_gen"
    ] = "strg_ub_vec_inst.tb_only.tb_write_addr_gen_1.addr_out"

    for controller, addr_out_list in addr_out.items():
        for name, term in solver.fts.named_terms.items():
            if (
                addr_out_to_symbol_name[controller] in name
                and memtile_name in name
                and not solver.fts.is_next_var(term)
            ):
                print(
                    "Adding constraint for addr_out",
                    controller,
                    addr_out_to_symbol_name[controller],
                )
                addr_out_type = term.get_sort()

                # Create LUT for addr_out and dim_out
                addr_out_var = solver.create_fts_state_var(
                    f"{memtile_name}_{controller}_address_out",
                    solver.solver.make_sort(
                        ss.sortkinds.ARRAY, solver.create_bvsort(16), addr_out_type
                    ),
                )

                for i, addr in enumerate(addr_out_list):
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
                break

    for controller, dim_out_list in dim_out.items():
        for name, term in solver.fts.named_terms.items():
            if (
                dim_out_to_symbol_name[controller] in name
                and memtile_name in name
                and not solver.fts.is_next_var(term)
            ):
                print(
                    "Adding constraint for dim counter",
                    controller,
                    dim_out_to_symbol_name[controller],
                )
                dim_cnt_type = term.get_sort()

                # Create LUT for dim_cnt and dim_out
                dim_cnt_var = solver.create_fts_state_var(
                    f"{memtile_name}_{controller}_dimemsion_cnt",
                    solver.solver.make_sort(
                        ss.sortkinds.ARRAY, solver.create_bvsort(16), dim_cnt_type
                    ),
                )

                for i, dim_cnt in enumerate(dim_out_list):
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

                solver.fts.add_invar(
                    solver.create_term(solver.ops.Equal, term, starting_dim_cnt)
                )
                break

    for controller, addr_out_list in read_addr_out.items():
        for name, term in solver.fts.named_terms.items():
            if (
                read_addr_out_to_symbol_name[controller] in name
                and memtile_name in name
                and not solver.fts.is_next_var(term)
            ):
                print(
                    "Adding constraint for read_addr_out",
                    controller,
                    read_addr_out_to_symbol_name[controller],
                )
                addr_out_type = term.get_sort()

                # Create LUT for addr_out and dim_out
                addr_out_var = solver.create_fts_state_var(
                    f"{memtile_name}_{controller}_read_address_out",
                    solver.solver.make_sort(
                        ss.sortkinds.ARRAY, solver.create_bvsort(16), addr_out_type
                    ),
                )

                for i, addr in enumerate(addr_out_list):
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
                break

    for controller, addr_out_list in write_addr_out.items():
        for name, term in solver.fts.named_terms.items():
            if (
                write_addr_out_to_symbol_name[controller] in name
                and memtile_name in name
                and not solver.fts.is_next_var(term)
            ):
                print(
                    "Adding constraint for write_addr_out",
                    controller,
                    write_addr_out_to_symbol_name[controller],
                )
                addr_out_type = term.get_sort()

                # Create LUT for addr_out and dim_out
                addr_out_var = solver.create_fts_state_var(
                    f"{memtile_name}_{controller}_write_address_out",
                    solver.solver.make_sort(
                        ss.sortkinds.ARRAY, solver.create_bvsort(16), addr_out_type
                    ),
                )

                for i, addr in enumerate(addr_out_list):
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
                break


def mem_tile_get_num_valids(config, cycles, iterator_support=2, address_width=16):

    model_ag = AddrGenModel(
        iterator_support=iterator_support, address_width=address_width
    )

    transformed_config = {}

    transformed_config["starting_addr"] = config["cycle_starting_addr"][0]
    transformed_config["dimensionality"] = len(config["extent"])
    for i in range(transformed_config["dimensionality"]):
        transformed_config[f"strides_{i}"] = config["cycle_stride"][i]
        transformed_config[f"ranges_{i}"] = config["extent"][i]

    model_ag.set_config(transformed_config)

    cycles_to_idx = []
    valids = []
    num_valids = 0

    for cycle in range(cycles):
        cycles_to_idx.append(num_valids)
        if cycle == model_ag.get_address():
            valids.append(1)
            num_valids += 1
            model_ag.step()
        else:
            valids.append(0)
        cycle += 1

    return cycles_to_idx, valids
