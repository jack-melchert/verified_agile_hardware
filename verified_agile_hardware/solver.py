import smt_switch as ss
import smt_switch.pysmt_frontend as fe
import pono
import os


class Solver:
    def __init__(self):
        self.fe_solver = fe.Solver("cvc5")
        self.solver = self.fe_solver.solver
        self.convert = self.fe_solver.converter.convert
        self.fts = pono.FunctionalTransitionSystem(self.solver)
        self.ur = pono.Unroller(self.fts)
        self.ops = ss.primops
        self.module_smt = {}
        self.bboxes = {}
        self.file_info = {}
        self.app_dir = ""
        self.rsts = []
        self.clks = []
        self.flushes = []

    def create_bvsort(self, width):
        return self.solver.make_sort(ss.sortkinds.BV, width)

    def create_boolsort(self):
        return self.solver.make_sort(ss.sortkinds.BOOL)

    def create_sort(self, kind, *args):
        return self.solver.make_sort(kind, *args)

    def create_fts_input_var(self, name, sort):
        return self.fts.make_inputvar(name, sort)

    def create_fts_state_var(self, name, sort):
        return self.fts.make_statevar(name, sort)

    def create_symbol(self, name, sort):
        return self.solver.make_symbol(name, sort)

    def create_term(self, op, *args):
        return self.solver.make_term(op, *args)

    def create_const(self, value, sort):
        return self.solver.make_term(value, sort)

    def assert_formula(self, formula):
        self.solver.assert_formula(formula)

    def read_btor2(self, filename):
        if not os.path.isfile(filename):
            raise FileNotFoundError("File does not exist: {}".format(filename))
        pono.BTOR2Encoder(filename, self.fts)

    def check_sat(self):
        return self.solver.check_sat()


class Rewriter(ss.TermDagVisitor):
    def __init__(self, solver, terms, suffix=""):
        self._solver = solver
        self.rewritten_terms = {}
        self.suffix = suffix
        self.state_vars = []
        self.new_state_vars = []
        self.terms = terms

    def rewrite(self):
        for term in self.terms:
            self.walk_dag(term)

        for term in self.state_vars:
            new_term = self.rewritten_terms[term]
            old_state_target = self._solver.fts.state_updates[term]
            new_state_target = self.rewritten_terms[old_state_target]
            self._solver.fts.assign_next(new_term, new_state_target)
            self.new_state_vars.append(new_term)

        for name, term in self._solver.fts.named_terms.items():
            if self.suffix not in name:
                if term in self.rewritten_terms:
                    new_term = self.rewritten_terms[term]
                    self._solver.fts.name_term(name + self.suffix, new_term)

    def visit_term(self, term, new_children):
        try:
            return self.rewritten_terms[term]
        except KeyError:
            pass

        op = term.get_op()

        if op:
            new_term = self._solver.solver.make_term(op, new_children)
        elif term.is_symbolic_const():
            name = str(term)

            if self.suffix not in str(term):
                name += self.suffix

            sort = term.get_sort()

            if self._solver.fts.is_input_var(term):
                new_term = self._solver.create_fts_input_var(name, sort)
            elif self._solver.fts.is_curr_var(term):
                self.state_vars.append(term)
                new_term = self._solver.create_fts_state_var(name, sort)
            else:
                new_term = self._solver.create_symbol(name, sort)

        else:
            new_term = term

        self.rewritten_terms[term] = new_term
        return new_term
