from verified_agile_hardware.solver import Solver, Rewriter
from verified_agile_hardware.yosys_utils import mem_tile_to_btor, sv2v
from verified_agile_hardware.configure_mem_tile import MemtileConfig
from verified_agile_hardware.simulate_lake import (
    simulate_counters,
)
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
        solver.fts.add_invar(
            solver.create_term(
                solver.ops.Equal,
                solver.create_term(
                    solver.ops.Select, sram_var, solver.create_const(i, index_sort)
                ),
                solver.create_const(val, element_sort),
            )
        )

    for name, term in solver.fts.named_terms.items():
        if "r_w_seq_current_state" in name and mem_name in name:
            solver.fts.constrain_init(
                solver.create_term(
                    solver.ops.Equal, term, solver.create_const(0, term.get_sort())
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

    # Setting all unused inputs to 0 for some reason causes the memtiles to misbehave
    # for in_, bw, packed, size in inputs_and_bw:
    #     if in_ in config_dict or in_ in used_inputs:
    #         continue
    #     config_dict[in_] = 0

    # Module definition
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

    # Wire instantiation
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

    # Memtile instantiation
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


def produce_configed_simulation_memtile_verilog(
    app_dir, mem_tile, config_dict, mem_name
):

    if "rst_n" in config_dict:
        del config_dict["rst_n"]

    # always used
    used_inputs = ["clk", "flush", "rst_n"]
    used_outputs = []

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

    # Setting all unused inputs to 0 for some reason causes the memtiles to misbehave
    for in_, bw, packed, size in inputs_and_bw:
        if in_ in config_dict or in_ in used_inputs:
            continue
        config_dict[in_] = 0

    # Module definition
    verilog = f"""module {mem_name} (\n"""

    for in_, bw, packed, size in inputs_and_bw:
        if in_ in config_dict or in_ not in used_inputs:
            continue
        # in_ += f"_{mem_name}"
        if packed:
            verilog += f"input wire [{size-1}:0] [{bw-1}:0] {in_},\n"
        else:
            verilog += f"input wire [{bw-1}:0] {in_},\n"

    for out_, bw, packed, size in outputs_and_bw:
        if out_ not in used_outputs:
            continue
        # out_ += f"_{mem_name}"
        if packed:
            verilog += f"output wire [{size-1}:0] [{bw-1}:0] {out_},\n"
        else:
            verilog += f"output wire [{bw-1}:0] {out_},\n"

    verilog += ");\n"

    # Wire instantiation
    for in_, bw, packed, size in inputs_and_bw:
        if in_ in config_dict or in_ in used_inputs:
            continue
        # in_ += f"_{mem_name}"
        if packed:
            verilog += f"wire [{size-1}:0] [{bw-1}:0] {in_};\n"
        else:
            verilog += f"wire [{bw-1}:0] {in_};\n"

    for out_, bw, packed, size in outputs_and_bw:
        if out_ in used_outputs:
            continue
        # out_ += f"_{mem_name}"
        if packed:
            verilog += f"wire [{size-1}:0] [{bw-1}:0] {out_};\n"
        else:
            verilog += f"wire [{bw-1}:0] {out_};\n"

    # Memtile instantiation
    verilog += f"{mem_tile.dut.name} {mem_tile.dut.name} (\n"

    for in_, bw, packed, size in inputs_and_bw:
        if in_ in config_dict:
            verilog += f".{in_}({bw}'d{config_dict[in_]}),\n"
        else:
            verilog += f".{in_}({in_}),\n"

    for in_, bw, packed, size in outputs_and_bw:
        verilog += f".{in_}({in_}),\n"

    verilog += ");\n"
    verilog += "endmodule\n"

    with open(f"{app_dir}/{mem_name}_simulation.sv", "w") as f:
        f.write(verilog)


def load_new_mem_tile(
    solver, mem_name, mem_tile, config_dict, used_inputs, used_outputs
):
    # Write kratos config_dict to configure mem tile
    produce_configed_memtile_verilog(
        solver.app_dir, mem_tile, config_dict, mem_name, used_inputs, used_outputs
    )

    produce_configed_simulation_memtile_verilog(
        solver.app_dir, mem_tile, config_dict, mem_name
    )

    sv2v(
        f"{solver.app_dir}/{mem_name}_simulation.sv",
        f"{solver.app_dir}/{mem_name}_simulation.v",
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
    solver,
    mem_name,
    flush_offset=0,
):

    symbols_to_collect = [
        "mem_ctrl_stencil_valid_flat.stencil_valid_inst.stencil_valid_sched_gen.addr_out",
        # "mem_ctrl_strg_ub_vec_flat.strg_ub_vec_inst.agg_only.agg_write_sched_gen_0.addr_out",
        # "mem_ctrl_strg_ub_vec_flat.strg_ub_vec_inst.agg_only.agg_write_sched_gen_1.addr_out",
        # "mem_ctrl_strg_ub_vec_flat.strg_ub_vec_inst.sram_tb_shared.output_sched_gen_0.addr_out",
        # "mem_ctrl_strg_ub_vec_flat.strg_ub_vec_inst.sram_tb_shared.output_sched_gen_1.addr_out",
        # "mem_ctrl_strg_ub_vec_flat.strg_ub_vec_inst.tb_only.tb_read_sched_gen_0.addr_out",
        # "mem_ctrl_strg_ub_vec_flat.strg_ub_vec_inst.tb_only.tb_read_sched_gen_1.addr_out",
        "mem_ctrl_stencil_valid_flat.stencil_valid_inst.loops_stencil_valid.dim_counter",
        # "mem_ctrl_strg_ub_vec_flat.strg_ub_vec_inst.agg_only.loops_in2buf_0.dim_counter",
        # "mem_ctrl_strg_ub_vec_flat.strg_ub_vec_inst.agg_only.loops_in2buf_1.dim_counter",
        # "mem_ctrl_strg_ub_vec_flat.strg_ub_vec_inst.sram_tb_shared.loops_buf2out_autovec_read_0.dim_counter",
        # "mem_ctrl_strg_ub_vec_flat.strg_ub_vec_inst.sram_tb_shared.loops_buf2out_autovec_read_1.dim_counter",
        # "mem_ctrl_strg_ub_vec_flat.strg_ub_vec_inst.tb_only.loops_buf2out_read_0.dim_counter",
        # "mem_ctrl_strg_ub_vec_flat.strg_ub_vec_inst.tb_only.loops_buf2out_read_1.dim_counter",
        # "mem_ctrl_strg_ub_vec_flat.strg_ub_vec_inst.sram_only.output_addr_gen_0.addr_out",
        # "mem_ctrl_strg_ub_vec_flat.strg_ub_vec_inst.sram_only.output_addr_gen_1.addr_out",
        # "mem_ctrl_strg_ub_vec_flat.strg_ub_vec_inst.tb_only.tb_read_addr_gen_0.addr_out",
        # "mem_ctrl_strg_ub_vec_flat.strg_ub_vec_inst.tb_only.tb_read_addr_gen_1.addr_out",
        # "mem_ctrl_strg_ub_vec_flat.strg_ub_vec_inst.agg_sram_shared.agg_sram_shared_addr_gen_0.lin_addr_cnter",
        # "mem_ctrl_strg_ub_vec_flat.strg_ub_vec_inst.agg_sram_shared.agg_sram_shared_addr_gen_1.lin_addr_cnter",
        # "mem_ctrl_strg_ub_vec_flat.strg_ub_vec_inst.agg_only.agg_write_addr_gen_0.addr_out",
        # "mem_ctrl_strg_ub_vec_flat.strg_ub_vec_inst.agg_only.agg_write_addr_gen_1.addr_out",
        # "mem_ctrl_strg_ub_vec_flat.strg_ub_vec_inst.tb_only.tb_write_addr_gen_0.addr_out",
        # "mem_ctrl_strg_ub_vec_flat.strg_ub_vec_inst.tb_only.tb_write_addr_gen_1.addr_out",
    ]

    addr_out = simulate_counters(
        solver.app_dir,
        mem_name,
        "MemCore_inner",
        solver.max_cycles,
        symbols_to_collect,
    )

    if not (mem_name == "m1"):
        return

    for controller, addr_out_list in addr_out.items():
        addr_out[controller] = [0] * flush_offset + addr_out_list

    for controller, addr_out_list in addr_out.items():
        for name, term in solver.fts.named_terms.items():
            if (
                controller in name
                and mem_name in name
                and not solver.fts.is_next_var(term)
            ):

                print("Adding mem addr out constraint", controller, name)
                addr_out_type = term.get_sort()

                addr_out_lut = []
                for i, addr in enumerate(addr_out_list):
                    addr_out_lut.append(
                        (
                            solver.create_const(i, solver.create_bvsort(16)),
                            solver.create_const(addr, addr_out_type),
                        )
                    )

                breakpoint()

                addr_out_var = solver.create_lut(
                    f"{mem_name}_{controller}_address_out",
                    addr_out_lut,
                    solver.create_bvsort(16),
                    addr_out_type,
                )

                solver.fts.add_invar(
                    solver.create_term(
                        solver.ops.Equal, term, addr_out_var(solver.cycle_count)
                    )
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


def pond_tile_constraint_generator(
    solver,
    pond_name,
    flush_offset=0,
):

    symbols_to_collect = [
        "mem_ctrl_strg_ub_thin_PondTop_flat.strg_ub_thin_PondTop_inst.in2regfile_0_sched_gen.addr_out",
        "mem_ctrl_strg_ub_thin_PondTop_flat.strg_ub_thin_PondTop_inst.regfile2out_0_sched_gen.addr_out",
        "mem_ctrl_strg_ub_thin_PondTop_flat.strg_ub_thin_PondTop_inst.in2regfile_0_addr_gen.addr_out",
        "mem_ctrl_strg_ub_thin_PondTop_flat.strg_ub_thin_PondTop_inst.regfile2out_0_addr_gen.addr_out",
        "mem_ctrl_strg_ub_thin_PondTop_flat.strg_ub_thin_PondTop_inst.in2regfile_0_for_loop.dim_counter",
        "mem_ctrl_strg_ub_thin_PondTop_flat.strg_ub_thin_PondTop_inst.regfile2out_0_for_loop.dim_counter",
    ]

    addr_out = simulate_counters(
        solver.app_dir,
        pond_name,
        "PondTop",
        solver.max_cycles,
        symbols_to_collect,
    )

    for controller, addr_out_list in addr_out.items():
        addr_out[controller] = [0] * flush_offset + addr_out_list

    for controller, addr_out_list in addr_out.items():
        for name, term in solver.fts.named_terms.items():
            if (
                controller in name
                and pond_name in name
                and not solver.fts.is_next_var(term)
            ):

                print("Adding pond addr out constraint", controller, name)
                addr_out_type = term.get_sort()

                addr_out_lut = []
                for i, addr in enumerate(addr_out_list):
                    addr_out_lut.append(
                        (
                            solver.create_const(i, solver.create_bvsort(16)),
                            solver.create_const(addr, addr_out_type),
                        )
                    )

                addr_out_var = solver.create_lut(
                    f"{pond_name}_{controller}_address_out",
                    addr_out_lut,
                    solver.create_bvsort(16),
                    addr_out_type,
                )

                solver.fts.add_invar(
                    solver.create_term(
                        solver.ops.Equal, term, addr_out_var(solver.cycle_count)
                    )
                )
                break
