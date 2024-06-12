import os
import sys
import coreir
import networkx as nx
import json
import smt_switch as ss
from verified_agile_hardware.solver import Solver, Rewriter
from lassen import PE_fc, Inst_fc
from peak import family
import hwtypes
from verified_agile_hardware.peak_utils import (
    create_input,
    load_pe_tile,
    get_aadt,
    get_pe_inputs,
    get_pe_state,
)
from verified_agile_hardware.lake_utils import (
    load_new_mem_tile,
    config_rom,
    mem_tile_constraint_generator,
    pond_tile_constraint_generator,
)


def nx_to_pdf(nx_graph, filename):
    """
    Convert a NetworkX graph to a PDF.
    """
    from graphviz import Digraph

    dot = Digraph()
    for node in nx_graph.nodes:
        dot.node(node)
    for edge in nx_graph.edges:
        dot.edge(edge[0], edge[1], label=str(nx_graph.edges[edge]))
    dot.render(filename)


def port_remap_mem(mode, port, port_remap):
    # Ugh these hacks are copied from garnet
    if mode == "ROM":
        hack_remap = {
            "addr_in_0": "wr_addr_in",
            "ren_in_0": "ren",
            "data_out_0": "data_out",
        }
        if port in hack_remap:
            port = hack_remap[port]

    if mode == "pond":
        port = port.replace("pond_", "")

    if mode == "stencil_valid":
        if "stencil_valid" in port:
            port = port_remap["stencil_valid"][port]
        elif port in port_remap["UB"]:
            port = port_remap["UB"][port]
    else:
        if port in port_remap[mode]:
            port = port_remap[mode][port]

    return port


def node_to_smt(
    solver, tile_type, in_symbols, out_symbols_names, out_symbol_widths, data, node
):
    out_symbols = {}

    if tile_type == "global.IO" or tile_type == "global.BitIO":
        assert len(in_symbols) == 1

        for in_symbol_name, in_symbol in in_symbols.items():
            for out_symbol_name in out_symbols_names:
                out_symbols[out_symbol_name] = in_symbol

    elif tile_type == "global.PE":
        # To use bitwuzla, we can try packing the PE instuction into this node, and calling the PE smt with the constant

        out_port_names = [
            str(out_symbol).split(f"{node}.")[1] for out_symbol in out_symbols_names
        ]
        pe_name = str(node)
        pe0, bboxes0, pe_inputs = load_pe_tile(
            solver,
            PE_fc,
            pe_instr=data["pe_inst"],
            pe_name=pe_name,
            out_port_names=out_port_names,
        )
        solver.bboxes.update(bboxes0)

        pe_inputs = {str(i): i for i in pe_inputs}

        port_remap = solver.interconnect.tile_circuits[(1, 1)].core.get_port_remap()[
            "alu"
        ]
        port_remap_reversed = {v: k for k, v in port_remap.items()}

        for in_symbol_name, in_symbol in in_symbols.items():
            port = in_symbol_name.split(f"{node}.")[1]
            width = in_symbol.get_sort().get_width()
            if f"{port}_{pe_name}" not in pe_inputs:
                port = port_remap_reversed[port]
            if width == 1:
                new_in_symbol = solver.create_term(
                    solver.ops.Equal,
                    in_symbol,
                    solver.create_const(1, solver.create_bvsort(1)),
                )
                solver.fts.add_invar(
                    solver.create_term(
                        solver.ops.Equal,
                        new_in_symbol,
                        pe_inputs[f"{port}_{pe_name}"],
                    )
                )
            else:
                pe_input = pe_inputs[f"{port}_{pe_name}"]
                in_symbol_short = solver.fts.make_term(
                    ss.Op(ss.primops.Extract, pe_input.get_sort().get_width() - 1, 0),
                    in_symbol,
                )

                solver.fts.add_invar(
                    solver.create_term(
                        solver.ops.Equal,
                        in_symbol_short,
                        pe_input,
                    )
                )

        # This is hardcoded and will break if there are complex PE output types
        out_to_slice = {}
        curr_bit = 0

        coreir_name_to_peak_name = {}
        for idx, (n, v) in enumerate(PE_fc.SMT.output_t._field_table_.items()):
            if issubclass(v, hwtypes.bit_vector.Bit):
                size = 1
            else:
                size = v.size
            out_to_slice[f"O{idx}"] = (curr_bit, curr_bit + size - 1)
            curr_bit += size
            coreir_name_to_peak_name[n] = f"O{idx}"

        port_remap = solver.interconnect.tile_circuits[(1, 1)].core.get_port_remap()[
            "alu"
        ]
        port_remap_reversed = {v: k for k, v in port_remap.items()}

        for out_symbol_name in out_symbols_names:
            port = out_symbol_name.split(f"{node}.")[1]

            if port in out_to_slice:
                start, end = out_to_slice[port]
            else:
                start, end = out_to_slice[
                    coreir_name_to_peak_name[port_remap_reversed[port]]
                ]

            ext = ss.Op(ss.primops.Extract, end, start)
            ext_pe = solver.create_term(ext, pe0)

            out_symbol_width = out_symbol_widths[out_symbol_name]
            if out_symbol_width == ext_pe.get_sort().get_width():
                out_symbols[out_symbol_name] = ext_pe
            else:
                # Pad the output to out_symbol_width
                ext_pe_extended = solver.create_term(
                    ss.Op(ss.primops.Concat),
                    ext_pe,
                    solver.create_const(
                        0,
                        solver.create_bvsort(
                            out_symbol_width - ext_pe.get_sort().get_width()
                        ),
                    ),
                )

                out_symbols[out_symbol_name] = ext_pe_extended

    elif tile_type == "cgralib.Mem":
        mem_name = data["inst"].name

        if "stencil_valid" in data["inst"].metadata["config"]:
            valid_out_starting_cycle = data["inst"].metadata["config"]["stencil_valid"][
                "cycle_starting_addr"
            ][0]
            solver.stencil_valid_to_schedule[str(node)] = data["inst"].metadata[
                "config"
            ]["stencil_valid"]
            solver.first_valid_output = max(
                solver.first_valid_output, valid_out_starting_cycle
            )

        metadata = data["inst"].metadata
        # Need to configure memory here
        mem_tile = solver.interconnect.tile_circuits[(3, 1)].core

        sys.stdout = open(os.devnull, "w")
        config = mem_tile.get_config_bitstream(data["inst"].metadata)

        strg_ub_vec = None
        for controller in mem_tile.CC.controllers:
            if controller.name == "strg_ub_vec":
                strg_ub_vec = controller
                break
        assert strg_ub_vec is not None

        stencil_valid = None
        for controller in mem_tile.CC.controllers:
            if controller.name == "stencil_valid":
                stencil_valid = controller
                break
        assert stencil_valid is not None

        lake_configs = strg_ub_vec.get_bitstream(metadata["config"])
        if "stencil_valid" in metadata["config"]:
            lake_configs += stencil_valid.get_bitstream(metadata["config"])
        sys.stdout = sys.__stdout__

        mode = "UB"
        if "stencil_valid" in metadata["config"]:
            mode = "stencil_valid"
        elif "mode" in metadata and metadata["mode"] == "sram":
            mode = "ROM"
            # ROM values embedded in config, we want to remove those
            config = [c for c in config if len(c) == 2]

        mem_name = str(node)
        port_remap = mem_tile.get_port_remap()

        # About to do something dumb
        # sort config by the first number of the tuple
        config = sorted(config, key=lambda x: x[0])
        registers = mem_tile.registers
        # Sort config inputs by the key
        config_inputs = {
            n.split(f"_{mem_name}")[0]: v for n, v in registers.items() if "CONFIG" in n
        }
        config_inputs = sorted(config_inputs.items(), key=lambda x: x[0])

        config_dict = {c1[0]: c0[1] for c0, c1 in zip(config, config_inputs)}

        config_dict["tile_en"] = 1
        config_dict["clk_en"] = 1

        ctrl_mode = mem_tile.dut.get_mode_map()[mode].name
        mode_map = mem_tile.dut.ctrl_to_mode

        mode_val = mode_map[ctrl_mode][0]
        mode_excl_val = 1 if mode_map[ctrl_mode][1] == "excl" else 0

        config_dict["mode"] = mode_val
        config_dict["mode_excl"] = mode_excl_val

        config_dict["config_addr_in"] = 0
        config_dict["config_data_in"] = 0
        config_dict["config_en"] = 0
        config_dict["config_read"] = 0
        config_dict["config_write"] = 0

        # config_dict["flush"] = 0
        config_dict["rst_n"] = 1

        used_inputs = [
            port_remap_mem(mode, in_symbol_name.split(f"{mem_name}.")[1], port_remap)
            for in_symbol_name, in_symbol in in_symbols.items()
        ]
        used_outputs = [
            port_remap_mem(mode, out_symbol.split(f"{mem_name}.")[1], port_remap)
            for out_symbol in out_symbols_names
        ]

        if mode == "ROM":
            rom_wen_port = port_remap["ROM"]["wen"]
            used_inputs.append(rom_wen_port)

        config_dict_save = config_dict.copy()

        mem_inputs, mem_outputs = load_new_mem_tile(
            solver, mem_name, mem_tile, config_dict, used_inputs, used_outputs
        )

        flush_offset = 0
        if "y" in data:
            if data["y"] == 0 or solver.interconnect.pipeline_config_interval == 0:
                flush_offset = 0
            else:
                flush_offset = (
                    data["y"] - 1
                ) // solver.interconnect.pipeline_config_interval


        used_mem_inputs = []
        for n,v in config_dict_save.items():
  
            mem_input = mem_inputs[n + "_" + mem_name]

            solver.fts.add_invar(
                solver.create_term(
                    solver.ops.Equal, mem_input, solver.create_const(v, mem_input.get_sort())
                )
            )
            used_mem_inputs.append(mem_input)

        # clock, and flush
        solver.clks.append(mem_inputs[f"clk_{mem_name}"])
        used_mem_inputs.append(mem_inputs[f"clk_{mem_name}"])
        solver.flushes.append(mem_inputs[f"flush_{mem_name}"])
        used_mem_inputs.append(mem_inputs[f"flush_{mem_name}"])

        mem_tile_constraint_generator(
            solver,
            mem_name,
            flush_offset=flush_offset,
        )

        for in_symbol_name, in_symbol in in_symbols.items():
            port = in_symbol_name.split(f"{mem_name}.")[1]

            port = port_remap_mem(mode, port, port_remap)

            in_symbol_width = in_symbol.get_sort().get_width()

            if f"{port}_{mem_name}" not in mem_inputs:
                continue

            if (
                in_symbol_width
                == mem_inputs[f"{port}_{mem_name}"].get_sort().get_width()
            ):
                mem_input = mem_inputs[f"{port}_{mem_name}"]
            else:
                mem_input = solver.create_term(
                    ss.Op(ss.primops.Extract, in_symbol_width - 1, 0),
                    mem_inputs[f"{port}_{mem_name}"],
                )

            solver.fts.add_invar(
                solver.create_term(
                    solver.ops.Equal,
                    in_symbol,
                    mem_input,
                )
            )
            used_mem_inputs.append(mem_input)

        # Need to tie wen to 0 for ROMs, this is usually handled in the connection box
        # But we just have to emulate that behavior here
        if mode == "ROM":
            rom_wen_port = port_remap["ROM"]["wen"]
            wen_port = mem_inputs[f"{rom_wen_port}_{mem_name}"]
            solver.fts.add_invar(
                solver.create_term(
                    solver.ops.Equal,
                    wen_port,
                    solver.create_const(0, wen_port.get_sort()),
                )
            )

        unused_mem_inputs = {
            k: v for k, v in mem_inputs.items() if v not in used_mem_inputs
        }

        for k, v in unused_mem_inputs.items():
            if "config" in k:
                solver.fts.add_invar(
                    solver.create_term(
                        solver.ops.Equal, v, solver.create_const(0, v.get_sort())
                    )
                )

        for out_symbol_name in out_symbols_names:
            port = out_symbol_name.split(f"{mem_name}.")[1]

            port = port_remap_mem(mode, port, port_remap)

            out_symbol_width = out_symbol_widths[out_symbol_name]
            if (
                out_symbol_width
                == mem_outputs[f"{port}_{mem_name}"].get_sort().get_width()
            ):
                mem_output = mem_outputs[f"{port}_{mem_name}"]
            else:
                mem_output = solver.fts.make_term(
                    ss.Op(ss.primops.Extract, out_symbol_width - 1, 0),
                    mem_outputs[f"{port}_{mem_name}"],
                )
            out_symbols[out_symbol_name] = mem_output

        if mode == "ROM":
            assert "init" in metadata
            config_rom(solver, mem_name, metadata["init"])

    elif tile_type == "cgralib.Pond":
        pond_name = str(node)

        # Need to configure pond here
        metadata = data["inst"].metadata
        pond_tile = solver.interconnect.tile_circuits[(0, 1)].additional_cores[0]
        config = pond_tile.get_config_bitstream(data["inst"].metadata)

        mode = metadata["mode"]
        if "mode" in metadata and metadata["mode"] == "sram":
            mode = "ROM"
            # ROM values embedded in config, we want to remove those
            config = [c for c in config if len(c) == 2]

        ctrl_mode = pond_tile.dut.get_mode_map()[mode].name
        mode_map = pond_tile.dut.ctrl_to_mode
        strg_ub_vec = None
        for controller in pond_tile.dut.controllers:
            if controller.name == "strg_ub_thin_PondTop":
                strg_ub_vec = controller
                break
        assert strg_ub_vec is not None

        lake_configs = strg_ub_vec.get_bitstream(metadata["config"])

        port_remap = pond_tile.get_port_remap()

        # About to do something dumb
        # sort config by the first number of the tuple
        config = sorted(config, key=lambda x: x[0])
        registers = pond_tile.registers
        # Sort config inputs by the key
        config_inputs = {
            n.split(f"_{pond_name}")[0]: v
            for n, v in registers.items()
            if "CONFIG" in n
        }
        config_inputs = sorted(config_inputs.items(), key=lambda x: x[0])

        config_dict = {c1[0]: c0[1] for c0, c1 in zip(config, config_inputs)}

        config_dict["tile_en"] = 1
        config_dict["clk_en"] = 1

        mode_val = mode_map[ctrl_mode][0]
        mode_excl_val = 1 if mode_map[ctrl_mode][1] == "excl" else 0

        config_dict["mode"] = mode_val
        config_dict["mode_excl"] = mode_excl_val

        config_dict["config_addr_in"] = 0
        config_dict["config_data_in"] = 0
        config_dict["config_en"] = 0
        config_dict["config_read"] = 0
        config_dict["config_write"] = 0

        # config_dict["flush"] = 0
        config_dict["rst_n"] = 1

        used_inputs = [
            port_remap_mem(mode, in_symbol_name.split(f"{pond_name}.")[1], port_remap)
            for in_symbol_name in in_symbols
        ]
        used_outputs = [
            port_remap_mem(mode, out_symbol.split(f"{pond_name}.")[1], port_remap)
            for out_symbol in out_symbols_names
        ]

        if mode == "ROM":
            rom_wen_port = port_remap["ROM"]["wen"]
            used_inputs.append(rom_wen_port)

        pond_inputs, pond_outputs = load_new_mem_tile(
            solver, pond_name, pond_tile, config_dict, used_inputs, used_outputs
        )

        flush_offset = 0
        if "y" in data:
            if data["y"] == 0 or solver.interconnect.pipeline_config_interval == 0:
                flush_offset = 0
            else:
                flush_offset = (
                    data["y"] - 1
                ) // solver.interconnect.pipeline_config_interval

        pond_tile_constraint_generator(
            solver,
            pond_name,
            flush_offset=flush_offset,
        )

        used_pond_inputs = []

        # clock, and flush
        solver.clks.append(pond_inputs[f"clk_{pond_name}"])
        used_pond_inputs.append(pond_inputs[f"clk_{pond_name}"])
        solver.flushes.append(pond_inputs[f"flush_{pond_name}"])
        used_pond_inputs.append(pond_inputs[f"flush_{pond_name}"])

        for in_symbol_name, in_symbol in in_symbols.items():
            port = in_symbol_name.split(f"{pond_name}.")[1]

            port = port_remap_mem(mode, port, port_remap)

            in_symbol_width = in_symbol.get_sort().get_width()

            if f"{port}_{pond_name}" not in pond_inputs:
                continue

            if (
                in_symbol_width
                == pond_inputs[f"{port}_{pond_name}"].get_sort().get_width()
            ):
                mem_input = pond_inputs[f"{port}_{pond_name}"]
            else:
                mem_input = solver.create_term(
                    ss.Op(ss.primops.Extract, in_symbol_width - 1, 0),
                    pond_inputs[f"{port}_{pond_name}"],
                )

            solver.fts.add_invar(
                solver.create_term(
                    solver.ops.Equal,
                    in_symbol,
                    mem_input,
                )
            )
            used_pond_inputs.append(mem_input)

        # Need to tie wen to 0 for ROMs, this is usually handled in the connection box
        # But we just have to emulate that behavior here
        if mode == "ROM":
            rom_wen_port = port_remap["ROM"]["wen"]
            wen_port = pond_inputs[f"{rom_wen_port}_{pond_name}"]
            solver.fts.add_invar(
                solver.create_term(
                    solver.ops.Equal,
                    wen_port,
                    solver.create_const(0, wen_port.get_sort()),
                )
            )

        unused_pond_inputs = {
            k: v for k, v in pond_inputs.items() if v not in used_pond_inputs
        }

        for k, v in unused_pond_inputs.items():
            if "config" in k:
                solver.fts.add_invar(
                    solver.create_term(
                        solver.ops.Equal, v, solver.create_const(0, v.get_sort())
                    )
                )

        for out_symbol_name in out_symbols_names:
            port = out_symbol_name.split(f"{pond_name}.")[1]

            port = port_remap_mem(mode, port, port_remap)

            out_symbol_width = out_symbol_widths[out_symbol_name]
            if (
                out_symbol_width
                == pond_outputs[f"{port}_{pond_name}"].get_sort().get_width()
            ):
                pond_output = pond_outputs[f"{port}_{pond_name}"]
            else:
                pond_output = solver.fts.make_term(
                    ss.Op(ss.primops.Extract, out_symbol_width - 1, 0),
                    pond_outputs[f"{port}_{pond_name}"],
                )

            out_symbols[out_symbol_name] = pond_output

        if mode == "ROM":
            assert "init" in metadata
            config_rom(solver, pond_name, metadata["init"])

    elif tile_type == "coreir.reg" or tile_type == "corebit.reg":
        name = str(node)
        reg_in = solver.create_fts_state_var(
            f"{name}.reg_in", list(in_symbols.values())[0].get_sort()
        )
        reg_val = solver.create_fts_state_var(
            f"{name}.reg_val", list(in_symbols.values())[0].get_sort()
        )
        for in_symbol_name, in_symbol in in_symbols.items():
            solver.fts.assign_next(reg_in, in_symbol)
            solver.fts.assign_next(reg_val, reg_in)

        for out_symbol_name in out_symbols_names:
            out_symbols[out_symbol_name] = reg_val
    elif (
        tile_type == "corebit.const"
        or tile_type == "coreir.const"
        or tile_type == "pnr_const"
    ):
        if tile_type == "pnr_const":
            value = data["value"]
        else:
            value = data["inst"].config["value"].value
            # Value to int
            if type(value) == bool:
                value = int(value)
            else:
                value = value.value
        width = out_symbol_widths[out_symbols_names[0]]
        const = solver.create_const(value, solver.create_bvsort(width))

        for out_symbol_name in out_symbols_names:
            out_symbols[out_symbol_name] = const
    elif tile_type == "route":  # it's a pnr route node

        for in_symbol_name, in_symbol in in_symbols.items():
            for out_symbol_name in out_symbols_names:
                out_symbols[out_symbol_name] = in_symbol
    else:
        raise NotImplementedError(f"Tile type {tile_type} not implemented")

    return out_symbols


def pack_pe_constants(graph):
    # copy of graph
    graph_copy = graph.copy()

    for node, data in graph_copy.nodes(data=True):
        if "inst" in data:
            if data["inst"].module.name == "PE":
                # get the predecessor nodes
                for pred in graph.predecessors(node):
                    # get the edge data
                    edge_data = graph.get_edge_data(pred, node)
                    if edge_data["sink_port"] == "inst":

                        if "value" in graph.nodes(data=True)[pred]:
                            graph.nodes[node].update(
                                {"pe_inst": graph.nodes(data=True)[pred]["value"]}
                            )
                        else:
                            graph.nodes[node].update(
                                {
                                    "pe_inst": graph.nodes(data=True)[pred]["inst"]
                                    .config["value"]
                                    .value
                                }
                            )

                        graph.remove_edge(pred, node)
                        graph.remove_node(pred)

                        break


def nx_to_smt(graph, interconnect, solver):
    pack_pe_constants(graph)

    solver.interconnect = interconnect

    stencil_valid_to_port_controller = {}

    for node, data in graph.nodes(data=True):
        if (
            (
                "port_controller" in str(node)
                or (
                    str(node) in solver.id_to_name
                    and "port_controller" in solver.id_to_name[str(node)]
                )
            )
            and "inst" in data
            and data["inst"].module.name == "Mem"
        ):
            if "Counter" in str(node) or (
                str(node) in solver.id_to_name
                and "Counter" in solver.id_to_name[str(node)]
            ):
                continue
            curr_node = node
            while len(graph.out_edges(curr_node)) != 0:
                assert (
                    len(graph.out_edges(curr_node)) == 1
                ), f"Port controller {node} has more than one output"
                prev_node = curr_node
                for edge in graph.out_edges(curr_node):
                    curr_node = edge[1]

            stencil_valid_name = f"{edge[1]}.{edge[0]}"
            solver.stencil_valid_to_port_controller[stencil_valid_name] = node

    if len(list(nx.simple_cycles(graph))) > 0:
        breakpoint()

    node_symbols = {}
    input_symbols = {}
    output_symbols = {}

    # Topological sort
    for node in nx.topological_sort(graph):
        # for node, data in graph.nodes(data=True):
        data = graph.nodes[node]
        if node == "in":
            in_symbols = {}
            for out_ in graph.out_edges(node):
                edge_info = graph.edges[out_]
                name = f"{out_[1]}.{graph.edges[out_]['sink_port']}"
                input_symbols[name] = solver.create_fts_state_var(
                    name, solver.create_bvsort(edge_info["bitwidth"])
                )
                in_symbols[f'{out_[0]}.{edge_info["source_port"]}'] = input_symbols[
                    name
                ]
            node_symbols[node] = in_symbols
        elif node == "out":
            for in_ in graph.in_edges(node):
                edge_info = graph.edges[in_]
                source = in_[0]
                name = f"{in_[1]}.{source}"
                output_symbols[name] = solver.create_fts_state_var(
                    name, solver.create_bvsort(edge_info["bitwidth"])
                )
                solver.fts.add_invar(
                    solver.create_term(
                        solver.ops.Equal,
                        node_symbols[source][f'{source}.{edge_info["source_port"]}'],
                        output_symbols[name],
                    )
                )
        else:
            if "inst" not in data:
                if str(node) == "in" or str(node) == "out":
                    data["node_type"] = "route"
                tile_type = data["node_type"]
            else:
                tile_type = data["inst"].module.ref_name

            in_symbols = {}
            for in_ in graph.in_edges(node):
                edge_info = graph.edges[in_]
                source = in_[0]
                in_name = f'{in_[1]}.{edge_info["sink_port"]}'
                out_name = f'{source}.{edge_info["source_port"]}'
                source_symbol = node_symbols[source][out_name]
                in_symbols[in_name] = source_symbol

            out_symbol_widths = {}
            out_symbols_names = []
            for out_ in graph.out_edges(node):
                edge_info = graph.edges[out_]
                source = out_[0]
                name = f'{node}.{edge_info["source_port"]}'
                out_symbols_names.append(name)
                out_symbol_widths[name] = edge_info["bitwidth"]

            node_symbols[node] = node_to_smt(
                solver,
                tile_type,
                in_symbols,
                out_symbols_names,
                out_symbol_widths,
                data,
                node,
            )

    return solver, input_symbols, output_symbols


def coreir_to_nx(cmod):
    """
    Convert a CoreIR module to a NetworkX graph.
    """
    G = nx.DiGraph()
    for inst in cmod.instances:
        G.add_node(inst.name, inst=inst)
    # create map from inst.name to inst

    for conn in cmod.connections:
        if (
            conn.first.type.is_input()
        ):  # first vertex is input, second vertex must be output?
            assert conn.second.type.is_output()
            source = conn.second.selectpath
            sink = conn.first.selectpath
        else:
            assert conn.first.type.is_output()
            assert conn.second.type.is_input()
            source = conn.first.selectpath
            sink = conn.second.selectpath

        if source[0] == "self":
            source[0] = "in"
        if sink[0] == "self":
            sink[0] = "out"

        G.add_edge(
            source[0],
            sink[0],
            source_port=source[1],
            sink_port=sink[1],
            bitwidth=conn.size,
        )
    return G


def read_coreir(coreir_filename, top_module=None):
    try:
        with open(coreir_filename, "r") as f:
            pass
    except FileNotFoundError:
        raise FileNotFoundError(f"Could not find {coreir_filename}")

    c = coreir.Context()
    c.load_library("commonlib")
    c.load_library("cgralib")
    cmod = c.load_from_file(coreir_filename)

    return cmod.definition


def pnr_to_nx(pmod, cmod, instance_to_instr):
    """
    Convert a PnR module to a NetworkX graph.
    """
    g = nx.DiGraph()
    node_to_inst_dict = dict()

    # Create a dictionary that maps node names to instances
    for inst in cmod.instances:
        node_to_inst_dict[inst.name] = inst

    for node in pmod.nodes:
        if node in pmod.get_tiles():
            name = pmod.id_to_name[str(node)]

            # if node is a tile node, map to instructions
            if name in node_to_inst_dict.keys():
                # add the node itself
                g.add_node(
                    str(node),
                    inst=node_to_inst_dict[name],
                    node_type="tile",
                    node_name=name,
                    y=node.y,
                )

                # add the instructions for PEs
                if node in pmod.get_pes():
                    g.add_node(
                        str(node) + "_inst",
                        node_type="pnr_const",
                        value=instance_to_instr[name],
                        node_name=str(node) + "_inst",
                    )
                    source_port = "out"
                    sink_port = "inst"
                    bitwidth = instance_to_instr[name].size
                    g.add_edge(
                        str(node) + "_inst",
                        str(node),
                        source_port=source_port,
                        sink_port=sink_port,
                        bitwidth=bitwidth,
                    )
                    # add clk enable of the node
                    g.add_node(
                        str(node) + "_clk_en",
                        node_type="pnr_const",
                        value=1,
                        node_name=str(node) + "_clk_en",
                    )
                    source_port = "out"
                    sink_port = "clk_en"
                    bitwidth = 1
                    g.add_edge(
                        str(node) + "_clk_en",
                        str(node),
                        source_port=source_port,
                        sink_port=sink_port,
                        bitwidth=bitwidth,
                    )
            else:
                # Register
                g.add_node(
                    str(node),
                    node_type="coreir.reg",
                    node_name=name,
                )
        else:
            g.add_node(str(node), node_type="route", node_name=str(node))

    for edge in pmod.edges:
        # edge[0] = source, edge[1] = sink
        # if the source node is a tile node that's not a register
        if edge[0] in pmod.get_tiles() and edge[0] not in pmod.get_regs():
            # iterate through sinks of the node
            for sink in pmod.sinks[edge[0]]:
                if sink == edge[1]:  # find the sink connected to this edge
                    source_port = sink.port
                    bitwidth = sink.bit_width
        elif edge[0] in pmod.get_tiles():  # if a source node is a reg node
            source_port = "out"
            for sink in pmod.sinks[edge[0]]:
                if sink == edge[1]:  # find the sink connected to this edge
                    bitwidth = sink.bit_width
        else:  # if the source node is a port node
            source_port = "out"
            bitwidth = edge[0].bit_width

        if edge[1] in pmod.get_tiles() and edge[1] not in pmod.get_regs():
            # iterate through sources of the node
            for source in pmod.sources[edge[1]]:
                if source == edge[0]:  # find the sink connected to this edge
                    sink_port = source.port
                    bitwidth = source.bit_width
        elif edge[1] in pmod.get_tiles():
            sink_port = "in"
            for source in pmod.sources[edge[1]]:
                if source == edge[0]:  # find the sink connected to this edge
                    bitwidth = source.bit_width
        else:
            sink_port = "in"
            bitwidth = edge[1].bit_width

        g.add_edge(
            str(edge[0]),
            str(edge[1]),
            source_port=source_port,
            sink_port=sink_port,
            bitwidth=bitwidth,
        )

    g.add_node("in", node_type="in")
    g.add_node("out", node_type="out")

    for node in pmod.get_input_ios():
        if node.tile_id[0] == "I":
            bitwidth = int(node.tile_type.name.split("IO")[1])
            g.add_edge(
                "in",
                str(node),
                source_port=str(node),
                sink_port="out",
                bitwidth=bitwidth,
            )
        else:
            g.add_edge(
                "in", str(node), source_port=str(node), sink_port="out", bitwidth=1
            )

    for node in pmod.get_output_ios():
        if node.tile_id[0] == "I":
            bitwidth = int(node.tile_type.name.split("IO")[1])
            g.add_edge(
                str(node),
                "out",
                source_port="out",
                sink_port=str(node),
                bitwidth=bitwidth,
            )
        else:
            g.add_edge(
                str(node), "out", source_port="out", sink_port=str(node), bitwidth=1
            )

    return g
