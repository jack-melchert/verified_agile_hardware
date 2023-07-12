def get_mem_btor_outputs(btor_filename):
    output_vars = []
    with open(btor_filename) as f:
        for line in f:
            if " output " in line:
                output_vars.append(line.split()[3])
    return output_vars
