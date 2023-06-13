import smt_switch as ss
import smt_switch.pysmt_frontend as fe
import numpy


def conv_smt_test():
    s = fe.Solver("cvc5")
    solver = s.solver

    image_width = 64
    image_height = 64

    kernel_width = 3
    kernel_height = 3

    bvsort16 = solver.make_sort(ss.sortkinds.BV, 16)

    # Create an SMT variable (symbol) for every input pixel
    in_image_symbols = []
    for y in range(image_height):
        in_image_symbols.append([])
        for x in range(image_width):
            in_image_symbols[y].append(
                solver.make_symbol(f"in_image_{x}_{y}", bvsort16)
            )
    # Create SMT variable for every kernel value
    kernel_symbols = []
    for y in range(kernel_height):
        kernel_symbols.append([])
        for x in range(kernel_width):
            kernel_symbols[y].append(solver.make_symbol(f"kernel_{x}_{y}", bvsort16))

    # Create array of output equations
    # out_symbols[y][x] is the equation representing the output pixel value at that point
    out_symbols = []
    for i_y in range(image_height):
        out_symbols.append([])
        for i_x in range(image_width):
            accum = []
            for k_y in range(kernel_height):
                for k_x in range(kernel_width):
                    if i_y + k_y < len(in_image_symbols) and i_x + k_x < len(
                        in_image_symbols[i_y + k_y]
                    ):
                        accum.append(
                            solver.make_term(
                                ss.primops.BVMul,
                                in_image_symbols[i_y + k_y][i_x + k_x],
                                kernel_symbols[k_y][k_x],
                            )
                        )

            if len(accum) > 1:
                out_symbols[i_y].append(solver.make_term(ss.primops.BVAdd, *accum))

    # Numpy convolution of the input image with the kernel
    in_image = numpy.random.randint(
        0, 2**8, (image_height, image_width), dtype=numpy.uint16
    )
    kernel = numpy.random.randint(
        0, 2**8, (kernel_height, kernel_width), dtype=numpy.uint16
    )
    out_image = numpy.zeros((image_height, image_width), dtype=numpy.uint16)

    for i_y in range(image_height):
        for i_x in range(image_width):
            accum = 0
            for k_y in range(kernel_height):
                for k_x in range(kernel_width):
                    if i_y + k_y < len(in_image) and i_x + k_x < len(
                        in_image[i_y + k_y]
                    ):
                        accum += in_image[i_y + k_y][i_x + k_x] * kernel[k_y][k_x]
            out_image[i_y][i_x] = accum

    # Add constraints to the solver
    for y in range(image_height):
        for x in range(image_width):
            solver.assert_formula(
                solver.make_term(
                    ss.primops.Equal,
                    in_image_symbols[y][x],
                    solver.make_term(int(in_image[y][x]), bvsort16),
                )
            )

    for y in range(kernel_height):
        for x in range(kernel_width):
            solver.assert_formula(
                solver.make_term(
                    ss.primops.Equal,
                    kernel_symbols[y][x],
                    solver.make_term(int(kernel[y][x]), bvsort16),
                )
            )

    # Add output constraints
    for y in range(image_height):
        for x in range(image_width):
            if y < len(out_symbols) and x < len(out_symbols[y]):
                solver.assert_formula(
                    solver.make_term(
                        ss.primops.Equal,
                        out_symbols[y][x],
                        solver.make_term(int(out_image[y][x]), bvsort16),
                    )
                )

    # Check satisfiability
    print(solver.check_sat())
