import coreir
import networkx as nx
from verified_agile_hardware.solver import Solver, Rewriter


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


def node_to_smt(solver, tile_type, in_symbols, out_symbols, data):
    if tile_type == "global.IO" or tile_type == "global.BitIO":
        for in_symbol in in_symbols:
            for out_symbol in out_symbols:
                solver.assert_formula(
                    solver.create_term(solver.ops.Equal, in_symbol, out_symbol)
                )
    elif tile_type == "global.PE":
        pass
    elif tile_type == "cgralib.Mem":
        pass
    elif tile_type == "cgralib.Pond":
        pass
    elif tile_type == "coreir.reg":
        name = data["inst"].name
        reg_in = solver.create_fts_input_var(f"{name}.reg_in", in_symbols[0].get_sort())
        reg_val = solver.create_fts_state_var(
            f"{name}.reg_val", in_symbols[0].get_sort()
        )
        for in_symbol in in_symbols:
            solver.assert_formula(
                solver.create_term(solver.ops.Equal, in_symbol, reg_in)
            )
        solver.fts.assign_next(reg_val, reg_in)
        for out_symbol in out_symbols:
            solver.assert_formula(
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
        solver.assert_formula(
            solver.create_term(solver.ops.Equal, out_symbols[0], const)
        )
    else:
        raise NotImplementedError(f"Tile type {tile_type} not supported")


def nx_to_smt(graph):
    solver = Solver()

    for node, data in graph.nodes(data=True):
        if "inst" not in data:
            assert (
                node == "in" or node == "out"
            ), "Only in and out nodes should not have an inst attribute"
        else:
            tile_type = data["inst"].module.ref_name

            symbols = {}

            in_symbols = []
            for in_ in graph.in_edges(node):
                edge_info = graph.edges[in_]
                name = f"{in_[1]}.{graph.edges[in_]['sink_port']}"
                if name not in symbols:
                    symbols[name] = solver.create_symbol(
                        name, solver.create_bvsort(edge_info["bitwidth"])
                    )
                in_symbols.append(symbols[name])

            out_symbols = []
            for out_ in graph.out_edges(node):
                edge_info = graph.edges[out_]
                name = f"{out_[0]}.{graph.edges[out_]['source_port']}"
                if name not in symbols:
                    symbols[name] = solver.create_symbol(
                        name, solver.create_bvsort(edge_info["bitwidth"])
                    )
                out_symbols.append(symbols[name])

            node_to_smt(solver, tile_type, in_symbols, out_symbols, data)


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
