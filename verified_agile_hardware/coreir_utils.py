import os
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
from verified_agile_hardware.lake_utils import load_new_mem_tile, config_rom


def coreir_to_pdf(nx_graph, filename):
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
        assert port in hack_remap, f"Port {port} not in hack remap"
        port = hack_remap[port]

    if mode == "stencil_valid":
        if "stencil_valid" in port:
            port = port_remap["stencil_valid"][port]
        elif port in port_remap["UB"]:
            port = port_remap["UB"][port]
    else:
        if port in port_remap[mode]:
            port = port_remap[mode][port]

    return port


def node_to_smt(solver, tile_type, in_symbols, out_symbols, data):
    if tile_type == "global.IO" or tile_type == "global.BitIO":
        for in_symbol in in_symbols:
            for out_symbol in out_symbols:
                solver.fts.add_invar(
                    solver.create_term(solver.ops.Equal, in_symbol, out_symbol)
                )

    elif tile_type == "global.PE":
        # for each output symbol, convert only formula associated with that symbol, not the whole PE

        out_port_names = [
            str(out_symbol).split(f"{data['inst'].name}.")[1]
            for out_symbol in out_symbols
        ]
        pe0, bboxes0, pe_inputs = load_pe_tile(
            solver, PE_fc, pe_name=data["inst"].name, out_port_names=out_port_names
        )
        solver.bboxes.update(bboxes0)

        pe_inputs = {str(i): i for i in pe_inputs}

        for in_symbol in in_symbols:
            port = str(in_symbol).split(f"{data['inst'].name}.")[1]
            width = in_symbol.get_sort().get_width()
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
                        pe_inputs[f"{port}_{data['inst'].name}"],
                    )
                )
            else:
                solver.fts.add_invar(
                    solver.create_term(
                        solver.ops.Equal,
                        in_symbol,
                        pe_inputs[f"{port}_{data['inst'].name}"],
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

        for out_symbol in out_symbols:
            port = str(out_symbol).split(f"{data['inst'].name}.")[1]

            if port in out_to_slice:
                start, end = out_to_slice[port]
            else:
                start, end = out_to_slice[
                    coreir_name_to_peak_name[port_remap_reversed[port]]
                ]

            ext = ss.Op(ss.primops.Extract, end, start)
            ext_pe = solver.create_term(ext, pe0)

            solver.fts.add_invar(
                solver.create_term(solver.ops.Equal, out_symbol, ext_pe)
            )
    elif tile_type == "cgralib.Mem":
        mem_name = data["inst"].name

        if "stencil_valid" in data["inst"].metadata["config"]:
            valid_out_starting_cycle = data["inst"].metadata["config"]["stencil_valid"][
                "cycle_starting_addr"
            ][0]
            solver.first_valid_output = min(
                solver.first_valid_output, valid_out_starting_cycle
            )

        metadata = data["inst"].metadata
        # Need to configure memory here
        mem_tile = solver.interconnect.tile_circuits[(3, 1)].core
        config = mem_tile.get_config_bitstream(data["inst"].metadata)


        mode = "UB"
        if "stencil_valid" in metadata["config"]:
            mode = "stencil_valid"
        elif "mode" in metadata and metadata["mode"] == "sram":
            mode = "ROM"
            # ROM values embedded in config, we want to remove those
            config = [c for c in config if len(c) == 2]
        
        # About to do something dumb
        # sort config by the first number of the tuple
        config = sorted(config, key=lambda x: x[0])
        registers = mem_tile.registers
        # Sort config inputs by the key
        config_inputs = {
            n.split(f"_{mem_name}")[0]: v for n, v in registers.items() if "CONFIG" in n
        }
        config_inputs = sorted(config_inputs.items(), key=lambda x: x[0])

        mem_inputs, mem_outputs = load_new_mem_tile(
            solver, mem_name, mem_tile, zip(config, config_inputs)
        )

        used_mem_inputs = []

        # Reset, clock, and flush
        solver.rsts.append(mem_inputs[f"rst_n_{mem_name}"])
        used_mem_inputs.append(mem_inputs[f"rst_n_{mem_name}"])
        solver.clks.append(mem_inputs[f"clk_{mem_name}"])
        used_mem_inputs.append(mem_inputs[f"clk_{mem_name}"])
        solver.flushes.append(mem_inputs[f"flush_{mem_name}"])
        used_mem_inputs.append(mem_inputs[f"flush_{mem_name}"])

        # tile_en, mode, and config signals, going to hardcode these
        solver.fts.add_invar(
            solver.create_term(
                solver.ops.Equal,
                mem_inputs[f"tile_en_{mem_name}"],
                solver.create_const(1, solver.create_bvsort(1)),
            )
        )
        used_mem_inputs.append(mem_inputs[f"tile_en_{mem_name}"])

        solver.fts.add_invar(
            solver.create_term(
                solver.ops.Equal,
                mem_inputs[f"clk_en_{mem_name}"],
                solver.create_const(1, solver.create_bvsort(1)),
            )
        )
        used_mem_inputs.append(mem_inputs[f"clk_en_{mem_name}"])

        if mode == "ROM":
            mode_val = 2
        else:
            mode_val = 1

        solver.fts.add_invar(
            solver.create_term(
                solver.ops.Equal,
                mem_inputs[f"mode_{mem_name}"],
                solver.create_const(mode_val, solver.create_bvsort(2)),
            )
        )
        used_mem_inputs.append(mem_inputs[f"mode_{mem_name}"])

        if mode == "ROM":
            mode_excl_val = 0
        else:
            mode_excl_val = 1

        solver.fts.add_invar(
            solver.create_term(
                solver.ops.Equal,
                mem_inputs[f"mode_excl_{mem_name}"],
                solver.create_const(mode_excl_val, solver.create_bvsort(1)),
            )
        )
        used_mem_inputs.append(mem_inputs[f"mode_excl_{mem_name}"])

        port_remap = mem_tile.get_port_remap()

        for in_symbol in in_symbols:
            port = str(in_symbol).split(f"{data['inst'].name}.")[1]

            port = port_remap_mem(mode, port, port_remap)


            in_symbol_width = in_symbol.get_sort().get_width()

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
            rom_wen_port = port_remap['ROM']['wen']
            wen_port = mem_inputs[f"{rom_wen_port}_{mem_name}"]
            solver.fts.add_invar(
                solver.create_term(
                    solver.ops.Equal, wen_port, solver.create_const(0, wen_port.get_sort())
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

        for out_symbol in out_symbols:
            port = str(out_symbol).split(f"{data['inst'].name}.")[1]

            port = port_remap_mem(mode, port, port_remap)

            out_symbol_width = out_symbol.get_sort().get_width()
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

            solver.fts.add_invar(
                solver.create_term(
                    solver.ops.Equal,
                    out_symbol,
                    mem_output,
                )
            )

        if mode == "ROM":
            assert "init" in metadata
            config_rom(solver, mem_name, metadata["init"])

    elif tile_type == "cgralib.Pond":
        pond_name = data["inst"].name

        # Need to configure pond here
        pond_tile = solver.interconnect.tile_circuits[(0, 1)].additional_cores[0]
        config = pond_tile.get_config_bitstream(data["inst"].metadata)

        # About to do something dumb
        # sort config by the first number of the tuple
        config = sorted(config, key=lambda x: x[0])
        registers = (
            solver.interconnect.tile_circuits[(0, 1)].additional_cores[0].registers
        )
        # Sort config inputs by the key
        config_inputs = {
            n.split(f"_{pond_name}")[0]: v
            for n, v in registers.items()
            if "CONFIG" in n
        }
        config_inputs = sorted(config_inputs.items(), key=lambda x: x[0])

        pond_inputs, pond_outputs = load_new_mem_tile(
            solver, pond_name, pond_tile, zip(config, config_inputs)
        )

        used_pond_inputs = []

        # Reset, clock, and flush
        solver.rsts.append(pond_inputs[f"rst_n_{pond_name}"])
        used_pond_inputs.append(pond_inputs[f"rst_n_{pond_name}"])
        solver.clks.append(pond_inputs[f"clk_{pond_name}"])
        used_pond_inputs.append(pond_inputs[f"clk_{pond_name}"])
        solver.flushes.append(pond_inputs[f"flush_{pond_name}"])
        used_pond_inputs.append(pond_inputs[f"flush_{pond_name}"])

        # tile_en, mode, and config signals, going to hardcode these
        solver.fts.add_invar(
            solver.create_term(
                solver.ops.Equal,
                pond_inputs[f"tile_en_{pond_name}"],
                solver.create_const(1, solver.create_bvsort(1)),
            )
        )
        used_pond_inputs.append(pond_inputs[f"tile_en_{pond_name}"])

        # Annoying port remapping stuff here
        port_remap = pond_tile.get_port_remap()

        port_remap = port_remap["pond"]

        for in_symbol in in_symbols:
            port = str(in_symbol).split(f"{data['inst'].name}.")[1]
            port = port.replace("_pond_", "_")

            if port in port_remap:
                port = port_remap[port]

            in_symbol_width = in_symbol.get_sort().get_width()
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

        for out_symbol in out_symbols:
            port = str(out_symbol).split(f"{data['inst'].name}.")[1]
            port = port.replace("_pond_", "_")
            if port in port_remap:
                port = port_remap[port]

            out_symbol_width = out_symbol.get_sort().get_width()
            if (
                out_symbol_width
                == pond_outputs[f"{port}_{pond_name}"].get_sort().get_width()
            ):
                mem_output = pond_outputs[f"{port}_{pond_name}"]
            else:
                mem_output = solver.fts.make_term(
                    ss.Op(ss.primops.Extract, out_symbol_width - 1, 0),
                    pond_outputs[f"{port}_{pond_name}"],
                )

            solver.fts.add_invar(
                solver.create_term(
                    solver.ops.Equal,
                    out_symbol,
                    mem_output,
                )
            )

    elif tile_type == "coreir.reg" or tile_type == "corebit.reg":
        name = data["inst"].name
        reg_in = solver.create_fts_state_var(f"{name}.reg_in", in_symbols[0].get_sort())
        reg_val = solver.create_fts_state_var(
            f"{name}.reg_val", in_symbols[0].get_sort()
        )
        for in_symbol in in_symbols:
            solver.fts.assign_next(reg_in, in_symbol)
            solver.fts.assign_next(reg_val, reg_in)

        for out_symbol in out_symbols:
            solver.fts.add_invar(
                solver.create_term(solver.ops.Equal, out_symbol, reg_val)
            )
    elif tile_type == "corebit.const" or tile_type == "coreir.const":
        value = data["inst"].config["value"].value
        # Value to int
        if type(value) == bool:
            value = int(value)
        else:
            value = value.value
        const = solver.create_const(value, out_symbols[0].get_sort())
        solver.fts.add_invar(
            solver.create_term(solver.ops.Equal, out_symbols[0], const)
        )
    else:
        raise NotImplementedError(f"Tile type {tile_type} not supported")


def nx_to_smt(graph, interconnect, file_info=None, app_dir=None):
    solver = Solver()
    solver.solver.set_opt("produce-models", "true")
    solver.file_info = file_info
    solver.app_dir = f"{app_dir}/verification"

    if not os.path.exists(solver.app_dir):
        os.mkdir(solver.app_dir)

    solver.interconnect = interconnect

    node_symbols = {}

    for node, data in graph.nodes(data=True):
        symbols = {}

        in_symbols = []
        for in_ in graph.in_edges(node):
            edge_info = graph.edges[in_]
            name = f"{in_[1]}.{graph.edges[in_]['sink_port']}"
            if name not in symbols:
                symbols[name] = solver.create_fts_state_var(
                    name, solver.create_bvsort(edge_info["bitwidth"])
                )
            in_symbols.append(symbols[name])

        out_symbols = []
        for out_ in graph.out_edges(node):
            edge_info = graph.edges[out_]
            name = f"{out_[0]}.{graph.edges[out_]['source_port']}"
            if name not in symbols:
                symbols[name] = solver.create_fts_state_var(
                    name, solver.create_bvsort(edge_info["bitwidth"])
                )
            out_symbols.append(symbols[name])
        node_symbols[node] = symbols

        if "inst" not in data:
            assert (
                node == "in" or node == "out"
            ), "Only in and out nodes should not have an inst attribute"
        else:
            tile_type = data["inst"].module.ref_name
            node_to_smt(solver, tile_type, in_symbols, out_symbols, data)

    for source, sink, data in graph.edges(data=True):
        source_symbol = node_symbols[source][f'{source}.{data["source_port"]}']
        sink_symbol = node_symbols[sink][f'{sink}.{data["sink_port"]}']
        solver.fts.add_invar(
            solver.create_term(solver.ops.Equal, source_symbol, sink_symbol)
        )

    return solver, node_symbols["in"], node_symbols["out"]


def coreir_to_nx(cmod):
    """
    Convert a CoreIR module to a NetworkX graph.
    """
    G = nx.DiGraph()
    for inst in cmod.instances:
        G.add_node(inst.name, inst=inst)

    for conn in cmod.connections:
        if conn.first.type.is_input():
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
