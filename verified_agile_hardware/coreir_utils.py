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
from verified_agile_hardware.lake_utils import (
    load_new_mem_tile,
    config_rom,
    constrain_cycle_starting_addr,
)


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


def node_to_smt(
    solver,
    tile_type,
    in_symbols,
    out_symbols,
    data,
    node,
    node_symbols_in,
    node_symbols_out,
):
    if tile_type == "global.IO" or tile_type == "global.BitIO":
        # check if is an input node
        if "node_name" in data and "input" in data["node_name"]:
            in_symbols_dict = {str(s): s for s in out_symbols}
            node_symbols_in.update(in_symbols_dict)
        else:
            out_symbols_dict = {str(s): s for s in in_symbols}
            node_symbols_out.update(out_symbols_dict)

        for in_symbol in in_symbols:
            for out_symbol in out_symbols:
                solver.fts.add_invar(
                    solver.create_term(solver.ops.Equal, in_symbol, out_symbol)
                )

    elif tile_type == "global.PE":
        # for each output symbol, convert only formula associated with that symbol, not the whole PE

        out_port_names = [
            str(out_symbol).split(f"{node}.")[1] for out_symbol in out_symbols
        ]
        pe_name = str(node)
        pe0, bboxes0, pe_inputs = load_pe_tile(
            solver, PE_fc, pe_name=pe_name, out_port_names=out_port_names
        )
        solver.bboxes.update(bboxes0)

        pe_inputs = {str(i): i for i in pe_inputs}

        port_remap = solver.interconnect.tile_circuits[(1, 1)].core.get_port_remap()[
            "alu"
        ]
        port_remap_reversed = {v: k for k, v in port_remap.items()}

        for in_symbol in in_symbols:
            port = str(in_symbol).split(f"{node}.")[1]
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

        for out_symbol in out_symbols:
            port = str(out_symbol).split(f"{node}.")[1]

            if port in out_to_slice:
                start, end = out_to_slice[port]
            else:
                start, end = out_to_slice[
                    coreir_name_to_peak_name[port_remap_reversed[port]]
                ]

            ext = ss.Op(ss.primops.Extract, end, start)
            ext_pe = solver.create_term(ext, pe0)

            out_symbol_width = out_symbol.get_sort().get_width()
            if out_symbol_width == ext_pe.get_sort().get_width():
                solver.fts.add_invar(
                    solver.create_term(solver.ops.Equal, out_symbol, ext_pe)
                )
            else:
                out_symbol_short = solver.fts.make_term(
                    ss.Op(ss.primops.Extract, ext_pe.get_sort().get_width() - 1, 0),
                    out_symbol,
                )

                solver.fts.add_invar(
                    solver.create_term(solver.ops.Equal, out_symbol_short, ext_pe)
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

        if mode == "ROM":
            mode_val = 2
            mode_excl_val = 0
        else:
            mode_val = 1
            mode_excl_val = 1

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
            port_remap_mem(mode, str(in_symbol).split(f"{mem_name}.")[1], port_remap)
            for in_symbol in in_symbols
        ]
        used_outputs = [
            port_remap_mem(mode, str(out_symbol).split(f"{mem_name}.")[1], port_remap)
            for out_symbol in out_symbols
        ]

        mem_inputs, mem_outputs = load_new_mem_tile(
            solver, mem_name, mem_tile, config_dict, used_inputs, used_outputs
        )

        # constrain_cycle_starting_addr(solver, mem_name, metadata)

        used_mem_inputs = []

        # Reset, clock, and flush
        # solver.rsts.append(mem_inputs[f"rst_n_{mem_name}"])
        # used_mem_inputs.append(mem_inputs[f"rst_n_{mem_name}"])
        solver.clks.append(mem_inputs[f"clk_{mem_name}"])
        used_mem_inputs.append(mem_inputs[f"clk_{mem_name}"])
        solver.flushes.append(mem_inputs[f"flush_{mem_name}"])
        used_mem_inputs.append(mem_inputs[f"flush_{mem_name}"])

        for in_symbol in in_symbols:
            port = str(in_symbol).split(f"{mem_name}.")[1]

            # Need to fix this for verify-pnr
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

        for out_symbol in out_symbols:
            port = str(out_symbol).split(f"{mem_name}.")[1]

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
        name = str(node)
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
    else:  # if it's a route node, do the same thing as for I/O nodes
        for in_symbol in in_symbols:
            for out_symbol in out_symbols:
                solver.fts.add_invar(
                    solver.create_term(solver.ops.Equal, in_symbol, out_symbol)
                )


# def nx_to_smt(graph, interconnect, file_info=None, app_dir=None):
def nx_to_smt(graph, interconnect, solver, app_dir=None):
    if not os.path.exists(solver.app_dir):
        os.mkdir(solver.app_dir)

    solver.interconnect = interconnect

    stencil_valid_to_port_controller = {}

    for node, data in graph.nodes(data=True):
        if "port_controller" in str(node) and 'inst' in data and data['inst'].module.name == "Mem":
            curr_node = node
            while len(graph.out_edges(curr_node)) != 0:
                assert len(graph.out_edges(curr_node)) == 1, f"Port controller {node} has more than one output"
                prev_node = curr_node
                for edge in graph.out_edges(curr_node):
                    curr_node = edge[1]

            stencil_valid_name = f"{edge[1]}.{graph.edges[edge]['sink_port']}"
            solver.stencil_valid_to_port_controller[stencil_valid_name] = node

    node_symbols = {}
    node_symbols["in"] = {}
    node_symbols["out"] = {}

    for node, data in graph.nodes(data=True):
        symbols = {}

        in_symbols = []
        for in_ in graph.in_edges(node):  # all edges going into a node?
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

        node_symbols_in = {}
        node_symbols_out = {}
        if "inst" not in data:
            assert (
                node == "in"
                or node == "out"
                or data["node_type"] == "route"
                # ), "Only in and out nodes should not have an inst attribute"
            ), "Only route nodes should not have an inst attribute"
            node_to_smt(
                solver,
                "route",
                in_symbols,
                out_symbols,
                data,
                node,
                node_symbols["in"],
                node_symbols["out"],
            )
        else:
            tile_type = data["inst"].module.ref_name
            # print(node, " ", in_symbols, " ", out_symbols)
            node_to_smt(
                solver,
                tile_type,
                in_symbols,
                out_symbols,
                data,
                node,
                node_symbols["in"],
                node_symbols["out"],
            )
        # node_symbols["in"].update(node_symbols_in)
        # node_symbols["out"].update(node_symbols_out)


    for source, sink, data in graph.edges(data=True):
        source_symbol = node_symbols[source][f'{source}.{data["source_port"]}']
        sink_symbol = node_symbols[sink][f'{sink}.{data["sink_port"]}']
        solver.fts.add_invar(
            solver.create_term(solver.ops.Equal, source_symbol, sink_symbol)
        )
    return solver, node_symbols["in"], node_symbols["out"]



def coreir_to_nx(cmod):  # cmod = coreir file
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


def pnr_to_nx(pmod, cmod):  # pmod = pnr file
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
        else:
            name = str(node)
        # if node is a tile node, map to instance
        if name in node_to_inst_dict.keys():
            # if (node in pmod.get_tiles()):
            g.add_node(
                str(node),
                inst=node_to_inst_dict[name],
                node_type="tile",
                node_name=name,
            )
        else:  # if node is a route node, add to graph directly
            g.add_node(str(node), node_type="route", node_name=name)
            assert (
                node not in pmod.get_tiles() or node in pmod.get_regs()
            ), f"Tile node that's not register {name} claimed as route node"
            # if (node in pmod.get_tiles()):
            #     print(str(node))

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
        # breakpoint()
    return g

    # find if edge[0],[1] are tile or route nodes
