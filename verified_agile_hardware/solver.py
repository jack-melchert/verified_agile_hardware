import smt_switch as ss
import smt_switch.pysmt_frontend as fe
import pono


class Solver:
    def __init__(self):
        self.fe_solver = fe.Solver("cvc5")
        self.solver = self.fe_solver.solver
        self.converter = self.fe_solver.converter.convert
        self.fts = pono.FunctionalTransitionSystem(self.solver)
        self.ur = pono.Unroller(self.fts)
        self.ops = ss.primops
        self.module_smt = {}

    def create_bvsort(self, width):
        return self.solver.make_sort(ss.sortkinds.BV, width)

    def create_sort(self, kind, *args):
        return self.solver.make_sort(kind, *args)

    def create_symbol(self, name, sort):
        return self.solver.make_symbol(name, sort)

    def create_term(self, op, *args):
        return self.solver.make_term(op, *args)

    def create_const(self, value, sort):
        return self.solver.make_term(value, sort)

    def assert_formula(self, formula):
        self.solver.assert_formula(formula)

    def read_btor2(self, filename):
        pono.BTOR2Encoder(filename, self.fts)

    def check_sat(self):
        return self.solver.check_sat()

    def create_node_smt(self, node):
        if node not in self.module_smt:
            self.module_smt[node] = self.solver.make_symbol(
                node, self.create_bvsort(32)
            )
        return self.module_smt[node]

    def node_to_smt(self, node, inputs):
        assert node in self.module_smt, f"Node {node} doesn't have a SMT representation"
        # Create a term for the node and assign inputs
