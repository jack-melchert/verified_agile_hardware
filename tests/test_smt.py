from verified_agile_hardware.solver import Solver
import smt_switch as ss


def test_function():
    solver = Solver()

    # Create a bitvector sort of width 16
    bvsort16 = solver.create_bvsort(16)
    x = solver.create_symbol("x", bvsort16)
    y = solver.create_symbol("y", bvsort16)
    x_plus_y = solver.create_term(solver.ops.BVAdd, x, y)
    f = solver.create_symbol(
        "f",
        solver.solver.make_sort(ss.sortkinds.FUNCTION, [bvsort16, bvsort16, bvsort16]),
    )
    fx = solver.create_term(ss.primops.Apply, f, x, y)
    solver.assert_formula(solver.create_term(solver.ops.Equal, fx, x_plus_y))

    a = solver.create_symbol("a", bvsort16)
    b = solver.create_symbol("b", bvsort16)
    a_plus_b = solver.create_term(solver.ops.BVAdd, a, b)

    ax = solver.create_term(solver.ops.Equal, a, x)
    by = solver.create_term(solver.ops.Equal, b, y)
    axby = solver.create_term(solver.ops.And, ax, by)

    out = solver.create_term(
        solver.ops.Not, solver.create_term(solver.ops.Equal, fx, a_plus_b)
    )
    solver.assert_formula(solver.create_term(solver.ops.And, axby, out))

    # check sat
    assert solver.check_sat().is_unsat()


def test_function_application():
    solver = Solver()

    # Create a bitvector sort of width 16
    bvsort16 = solver.create_bvsort(16)

    x = solver.solver.make_param("x", bvsort16)
    y = solver.solver.make_param("y", bvsort16)
    x_plus_y = solver.create_term(solver.ops.BVAdd, x, y)
    f = solver.create_symbol(
        "f",
        solver.solver.make_sort(ss.sortkinds.FUNCTION, [bvsort16, bvsort16, bvsort16]),
    )
    fx = solver.create_term(ss.primops.Apply, f, x, y)

    # for all x, y. f(x, y) = x + y
    solver.assert_formula(
        solver.create_term(
            ss.primops.Forall, x, y, solver.create_term(solver.ops.Equal, fx, x_plus_y)
        )
    )

    one = solver.create_term(1, bvsort16)
    two = solver.create_term(2, bvsort16)
    three = solver.create_term(3, bvsort16)
    four = solver.create_term(4, bvsort16)
    seven = solver.create_term(7, bvsort16)

    # f(1, 2) != 3
    f12 = solver.create_term(ss.primops.Apply, f, one, two)
    solver.assert_formula(
        solver.create_term(
            solver.ops.Not, solver.create_term(solver.ops.Equal, f12, three)
        )
    )

    # f(2, 2) = 4
    solver.assert_formula(
        solver.create_term(
            solver.ops.Equal, solver.create_term(ss.primops.Apply, f, two, two), four
        )
    )

    # f(3, 4) = 7
    solver.assert_formula(
        solver.create_term(
            solver.ops.Equal,
            solver.create_term(ss.primops.Apply, f, three, four),
            seven,
        )
    )

    # check sat
    assert solver.check_sat().is_unsat()
