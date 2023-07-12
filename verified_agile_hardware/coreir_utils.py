import coreir
import networkx as nx


def coreir_to_pdf(nx_graph, filename):
    """
    Convert a NetworkX graph to a PDF.
    """
    from graphviz import Digraph

    dot = Digraph()
    for node in nx_graph.nodes:
        dot.node(node)
    for edge in nx_graph.edges:
        dot.edge(edge[0], edge[1], label=str(nx_graph.edges[edge]["attr"]))
    dot.render(filename)


def nx_to_smt(graph):
    for node, data in graph.nodes(data=True):
        if "inst" not in data:
            assert (
                node == "in" or node == "out"
            ), "Only in and out nodes should not have an inst attribute"
        else:
            tile_type = data["inst"].module.ref_name

            if tile_type == "global.IO":
                pass
            elif tile_type == "global.BitIO":
                pass
            elif tile_type == "global.PE":
                pass
            elif tile_type == "cgralib.Mem":
                pass
            elif tile_type == "cgralib.Pond":
                pass
            elif tile_type == "coreir.reg":
                pass
            elif tile_type == "corebit.const":
                pass
            elif tile_type == "coreir.const":
                pass
            else:
                raise NotImplementedError(f"Tile type {tile_type} not supported")


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
            source[0], sink[0], attr={"source_port": source[1], "sink_port": sink[1]}
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
