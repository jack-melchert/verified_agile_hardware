import smt_switch as ss
import smt_switch.pysmt_frontend as fe
import pono


class Solver:
    def __init__(self):
        self.fe_solver = fe.Solver("cvc5")
        self.solver = self.fe_solver.solver
        self.fts = pono.FunctionalTransitionSystem(self.solver)
        self.ur = pono.Unroller(self.fts)
        self.ops = ss.primops

    def create_bvsort(self, width):
        return self.solver.make_sort(ss.sortkinds.BV, width)

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
