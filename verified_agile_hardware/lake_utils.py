from verified_agile_hardware.solver import Solver, Rewriter
import smt_switch as ss


def get_mem_btor_outputs(btor_filename):
    output_vars = []
    with open(btor_filename) as f:
        for line in f:
            if " output " in line:
                output_vars.append(line.split()[3])
    return output_vars


def get_mem_inputs(solver, mem_name):
    input_vars = []
    for i in solver.fts.inputvars:
        if mem_name in str(i):
            input_vars.append(i)

    input_vars = sorted(input_vars, key=lambda x: str(x))
    return input_vars


# def copy_terms(old_solver, new_solver, name, term):
#     op = term.get_op()
#     if op:
#         return self._solver.make_term(op, new_children)
#     else:
#         return self._solver.make_symbol(name, term.get_sort())


def load_new_mem_tile(solver, mem_tile_btor_file, suffix="_rewritten"):
    # solver = Solver()

    solver.read_btor2(mem_tile_btor_file)

    Rewriter(solver, "_memtile0").rewrite()
    Rewriter(solver, "_memtile1").rewrite()

    # symbols = set()
    # for n, term in solver.fts.named_terms.items():
    #     symbols.update(ss.get_free_symbolic_consts(term))

    # sub_map = {}
    # for t in symbols:
    #     if solver.fts.is_input_var(t):
    #         sub_map[t] = solver.create_fts_input_var(
    #             str(t) + suffix, t.get_sort()
    #         )
    #         # existing_solver.create_fts_input_var(
    #         #     str(t) + suffix, existing_solver.copy_sort_from_other_solver(t.get_sort())
    #         # )
    #     else:
    #         sub_map[t] = solver.create_fts_state_var(
    #             str(t) + suffix, t.get_sort()
    #         )
    #         # existing_solver.create_fts_state_var(
    #         #     str(t) + suffix, existing_solver.copy_sort_from_other_solver(t.get_sort())
    #         # )

    # solver.fts.replace_terms(sub_map)

    # # solver.copy_fts_from_other_solver(solver, suffix)

    # for n,v in solver.fts.named_terms.items():
    #     if suffix not in n:
    #         n += suffix

    #     if v.is_symbolic_const():
    #         solver.fts.name_term(n, v)
    #     else:
    #         children = [t for t in v]
    #         op = v.get_op()
    #         solver.solver.make_term(op, children)
