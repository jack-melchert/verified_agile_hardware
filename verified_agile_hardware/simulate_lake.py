import subprocess


class AddresssGeneratorModel:
    def __init__(self, name, iterator_support, address_width):
        self.name = name
        self.iterator_support = iterator_support
        self.address_width = address_width

        self.config = {}

        self.config["starting_addr"] = 0
        self.config["dimensionality"] = 0

        self.address = 0
        self.next_dim = 0

        for i in range(self.iterator_support):
            self.config[f"strides_{i}"] = 0

    def set_config(self, new_config):
        for key, config_val in new_config.items():
            if key in self.config:
                self.config[key] = config_val

        self.address = self.config["starting_addr"]

    def get_address(self):
        return self.address

    def step(self, curr_dim):
        offset = self.config[f"strides_{self.next_dim}"]
        self.address = self.address + offset

        if self.address >= 2**self.address_width:
            self.address = 0

        self.next_dim = curr_dim


class SchedGenModel:
    def __init__(self, name, iterator_support, address_width):
        self.name = name
        self.iterator_support = iterator_support
        self.address_width = address_width

        self.config = {}

        self.config["starting_addr"] = 0
        self.config["dimensionality"] = 0

        self.dim_cnt = []

        self.address = 0

        for i in range(self.iterator_support):
            self.config[f"ranges_{i}"] = 0
            self.config[f"strides_{i}"] = 0
            self.dim_cnt.append(0)

    def set_config(self, new_config):
        for key, config_val in new_config.items():
            if key in self.config:
                self.config[key] = config_val
        for i in range(self.iterator_support):
            self.dim_cnt[i] = 0
        self.address = self.config["starting_addr"]

    def get_address(self):
        return self.address

    def step(self):

        curr_dim = 0
        while curr_dim < self.config["dimensionality"]:
            self.dim_cnt[curr_dim] = self.dim_cnt[curr_dim] + 1
            if self.dim_cnt[curr_dim] == self.config[f"ranges_{curr_dim}"] + 2:
                self.dim_cnt[curr_dim] = 0
            else:
                break
            curr_dim = curr_dim + 1

        offset = self.config[f"strides_{curr_dim}"]
        self.address = self.address + offset


def simulate_mem_tile_counters(
    config, lake_configs, cycles, iterator_support, address_width=16
):

    lake_configs_dict = {k: v for (k, v) in lake_configs}

    # So in order to get the valid starting address, dim count, read address, and write address, we need to run the
    # SchedGenModel for a number of cycles and record the outputs at each cycle

    # Unfortunately, lake doesn't have a real model of the memory tile behavior, so this will be fairly hardcoded
    sched_gens = {}

    # 4 address generator models: 1 for each of the 4 memory controllers
    sched_gens["agg_only_agg_write_sched_gen_0_sched_addr_gen"] = SchedGenModel(
        "agg_only_agg_write_sched_gen_0",
        iterator_support=3,
        address_width=11,
    )
    sched_gens["sram_tb_shared_output_sched_gen_0_sched_addr_gen"] = SchedGenModel(
        "sram_tb_shared_output_sched_gen_0",
        iterator_support=6,
        address_width=11,
    )
    sched_gens["tb_only_tb_read_sched_gen_0_sched_addr_gen"] = SchedGenModel(
        "tb_only_tb_read_sched_gen_0",
        iterator_support=6,
        address_width=11,
    )

    # Times 2 for dual ported memory
    sched_gens["agg_only_agg_write_sched_gen_1_sched_addr_gen"] = SchedGenModel(
        "agg_only_agg_write_sched_gen_1",
        iterator_support=3,
        address_width=11,
    )
    sched_gens["sram_tb_shared_output_sched_gen_1_sched_addr_gen"] = SchedGenModel(
        "sram_tb_shared_output_sched_gen_1",
        iterator_support=6,
        address_width=11,
    )
    sched_gens["tb_only_tb_read_sched_gen_1_sched_addr_gen"] = SchedGenModel(
        "tb_only_tb_read_sched_gen_1",
        iterator_support=6,
        address_width=11,
    )

    # One for stencil valid
    sched_gens["stencil_valid_sched_gen_sched_addr_gen"] = SchedGenModel(
        "stencil_valid_sched_gen_sched_addr_gen",
        iterator_support=6,
        address_width=11,
    )

    addr_gens = {}

    # Now we have to do address generator simulation as well
    addr_gens["sram_only_output_addr_gen_0"] = AddresssGeneratorModel(
        "sram_only_output_addr_gen_0",
        iterator_support=iterator_support,
        address_width=9,
    )
    addr_gens["sram_only_output_addr_gen_1"] = AddresssGeneratorModel(
        "sram_only_output_addr_gen_1",
        iterator_support=iterator_support,
        address_width=9,
    )
    addr_gens["tb_only_tb_read_addr_gen_0"] = AddresssGeneratorModel(
        "tb_only_tb_read_addr_gen_0", iterator_support=iterator_support, address_width=4
    )
    addr_gens["tb_only_tb_read_addr_gen_1"] = AddresssGeneratorModel(
        "tb_only_tb_read_addr_gen_1", iterator_support=iterator_support, address_width=4
    )

    addr_gens["agg_sram_shared_addr_gen_0"] = AddresssGeneratorModel(
        "agg_sram_shared_addr_gen_0",
        iterator_support=iterator_support,
        address_width=9,
    )
    addr_gens["agg_sram_shared_addr_gen_1"] = AddresssGeneratorModel(
        "agg_sram_shared_addr_gen_1",
        iterator_support=iterator_support,
        address_width=9,
    )

    addr_gens["agg_only_agg_write_addr_gen_0"] = AddresssGeneratorModel(
        "agg_only_agg_write_addr_gen_0",
        iterator_support=iterator_support,
        address_width=3,
    )
    addr_gens["agg_only_agg_write_addr_gen_1"] = AddresssGeneratorModel(
        "agg_only_agg_write_addr_gen_1",
        iterator_support=iterator_support,
        address_width=3,
    )
    addr_gens["tb_only_tb_write_addr_gen_0"] = AddresssGeneratorModel(
        "tb_only_tb_write_addr_gen_0",
        iterator_support=iterator_support,
        address_width=4,
    )
    addr_gens["tb_only_tb_write_addr_gen_1"] = AddresssGeneratorModel(
        "tb_only_tb_write_addr_gen_1",
        iterator_support=iterator_support,
        address_width=4,
    )

    sched_gen_to_read_addr_gen = {}
    sched_gen_to_read_addr_gen["sram_tb_shared_output_sched_gen_0_sched_addr_gen"] = (
        addr_gens["sram_only_output_addr_gen_0"]
    )
    sched_gen_to_read_addr_gen["sram_tb_shared_output_sched_gen_1_sched_addr_gen"] = (
        addr_gens["sram_only_output_addr_gen_1"]
    )
    sched_gen_to_read_addr_gen["tb_only_tb_read_sched_gen_0_sched_addr_gen"] = (
        addr_gens["tb_only_tb_read_addr_gen_0"]
    )
    sched_gen_to_read_addr_gen["tb_only_tb_read_sched_gen_1_sched_addr_gen"] = (
        addr_gens["tb_only_tb_read_addr_gen_1"]
    )

    # These two are special cases
    # They use the last 2 bits of of agg_only write sched gen as the address
    # Step is the one cycle registered reduction and of the 2 bit sliced address
    sched_gen_to_read_addr_gen["agg_only_agg_write_sched_gen_0_sched_addr_gen"] = (
        addr_gens["agg_sram_shared_addr_gen_0"]
    )
    sched_gen_to_read_addr_gen["agg_only_agg_write_sched_gen_1_sched_addr_gen"] = (
        addr_gens["agg_sram_shared_addr_gen_1"]
    )
    # Doesn't have config for stride but it should be 1
    for n, v in addr_gens["agg_sram_shared_addr_gen_0"].config.items():
        if "strides" in n:
            addr_gens["agg_sram_shared_addr_gen_0"].config[n] = 1

    for n, v in addr_gens["agg_sram_shared_addr_gen_1"].config.items():
        if "strides" in n:
            addr_gens["agg_sram_shared_addr_gen_1"].config[n] = 1

    sched_gen_to_write_addr_gen = {}
    sched_gen_to_write_addr_gen["agg_only_agg_write_sched_gen_0_sched_addr_gen"] = (
        addr_gens["agg_only_agg_write_addr_gen_0"]
    )
    sched_gen_to_write_addr_gen["agg_only_agg_write_sched_gen_1_sched_addr_gen"] = (
        addr_gens["agg_only_agg_write_addr_gen_1"]
    )

    sched_gen_to_write_addr_gen["sram_tb_shared_output_sched_gen_0_sched_addr_gen"] = (
        addr_gens["tb_only_tb_write_addr_gen_0"]
    )
    sched_gen_to_write_addr_gen["sram_tb_shared_output_sched_gen_1_sched_addr_gen"] = (
        addr_gens["tb_only_tb_write_addr_gen_1"]
    )

    # Gotta handle these weird loop names
    loops_to_sched_gen = {}
    loops_to_sched_gen["agg_only_agg_write_sched_gen_0_sched_addr_gen"] = (
        "agg_only_loops_in2buf_0"
    )
    loops_to_sched_gen["sram_tb_shared_output_sched_gen_0_sched_addr_gen"] = (
        "sram_tb_shared_loops_buf2out_autovec_read_0"
    )
    loops_to_sched_gen["tb_only_tb_read_sched_gen_0_sched_addr_gen"] = (
        "tb_only_loops_buf2out_read_0"
    )
    loops_to_sched_gen["agg_only_agg_write_sched_gen_1_sched_addr_gen"] = (
        "agg_only_loops_in2buf_1"
    )
    loops_to_sched_gen["sram_tb_shared_output_sched_gen_1_sched_addr_gen"] = (
        "sram_tb_shared_loops_buf2out_autovec_read_1"
    )
    loops_to_sched_gen["tb_only_tb_read_sched_gen_1_sched_addr_gen"] = (
        "tb_only_loops_buf2out_read_1"
    )
    loops_to_sched_gen["stencil_valid_sched_gen_sched_addr_gen"] = "loops_stencil_valid"

    sched_and_addr_gen_dict = sched_gens.copy()
    sched_and_addr_gen_dict.update(addr_gens)

    for addr_gen_name, addr_gen in sched_and_addr_gen_dict.items():
        new_config = {}

        for config_name, lake_config in lake_configs:
            if addr_gen_name in config_name:
                new_config[config_name.split(addr_gen_name + "_")[1]] = lake_config

            if (
                addr_gen_name in loops_to_sched_gen
                and loops_to_sched_gen[addr_gen_name] in config_name
            ):
                new_config[
                    config_name.split(loops_to_sched_gen[addr_gen_name] + "_")[1]
                ] = lake_config

        addr_gen.set_config(new_config)

    addr_out = {}
    dim_out = {}
    read_addr_out = {}
    write_addr_out = {}

    for controller_name in sched_gens:
        addr_out[controller_name] = []
        dim_out[controller_name] = []

        if controller_name in sched_gen_to_read_addr_gen:
            read_addr_out[controller_name] = []

        if controller_name in sched_gen_to_write_addr_gen:
            write_addr_out[controller_name] = []

    for cycle in range(cycles):
        # Collect outputs
        for controller_name, controller in sched_gens.items():
            addr_out[controller_name].append(controller.get_address())
            dim_out[controller_name].append(controller.dim_cnt.copy())

            # read address gen
            if controller_name in sched_gen_to_read_addr_gen:
                read_controller = sched_gen_to_read_addr_gen[controller_name]
                read_addr_out[controller_name].append(read_controller.get_address())

            # write address gen
            if controller_name in sched_gen_to_write_addr_gen:
                write_controller = sched_gen_to_write_addr_gen[controller_name]
                write_addr_out[controller_name].append(write_controller.get_address())

        # Step all controllers
        for controller_name, controller in sched_gens.items():

            step_controller = cycle == controller.get_address()

            if step_controller:

                curr_dim = 0

                if controller_name in loops_to_sched_gen:
                    loop_name = loops_to_sched_gen[controller_name]

                    dimensionality = loop_name + "_dimensionality"

                    if dimensionality in lake_configs_dict:
                        extents = []
                        for dim in range(lake_configs_dict[dimensionality]):
                            r = loop_name + "_ranges_" + str(dim)
                            extent = lake_configs_dict[r]

                            if controller.dim_cnt[dim] == extent:
                                curr_dim = dim + 1
                                break

                if controller_name in sched_gen_to_read_addr_gen:
                    read_controller = sched_gen_to_read_addr_gen[controller_name]
                    if (
                        "agg_sram_shared_addr_gen"
                        not in sched_gen_to_read_addr_gen[controller_name].name
                    ):
                        read_controller.step(curr_dim)
                    else:
                        # agg sram shared addr gen is a special case
                        # Only steps if the last 2 bits of the agg only sched gen address are 0
                        # Get last two bits of controller.get_address()
                        last_two_bits = controller.get_address() & 0b11
                        if last_two_bits == 3:
                            read_controller.step(curr_dim)

                if controller_name in sched_gen_to_write_addr_gen:
                    write_controller = sched_gen_to_write_addr_gen[controller_name]
                    write_controller.step(curr_dim)

                controller.step()

        # Special case

    # There is a pipeline register between the sram_tb_shared sched gen and the tb write addr gen
    # Need to delay this controller write addr by one cycle
    write_registered_step = [
        "sram_tb_shared_output_sched_gen_0_sched_addr_gen",
        "sram_tb_shared_output_sched_gen_1_sched_addr_gen",
    ]
    read_registered_step = [
        "agg_only_agg_write_sched_gen_0_sched_addr_gen",
        "agg_only_agg_write_sched_gen_1_sched_addr_gen",
    ]

    for controller_name in write_registered_step:
        write_addr_out[controller_name] = [0] + write_addr_out[controller_name][:-1]

    for controller_name in read_registered_step:
        read_addr_out[controller_name] = [0] + read_addr_out[controller_name][:-1]

    return addr_out, dim_out, read_addr_out, write_addr_out


def simulate_counters(app_dir, tile_name, tile_type, max_cycles, symbols_to_collect):

    # First, create a verilog testbench for the tile tile
    tile_tb = f"""
module {tile_name}_simulation_tb();
    reg clk;
    reg rst_n;
    reg flush;

    {tile_name} {tile_name}_inst (
        .clk(clk),
        .rst_n(rst_n),
        .flush(flush)
    );

    integer k = 0;

    initial begin

        clk = 0;

        rst_n = 1;
        flush = 0;

        #10 rst_n = 0;
        #10 rst_n = 1;

        #10 flush = 1;
        #10 flush = 0;


        // Run simulation
        for(k = 0; k<{max_cycles}; k=k+1)
        begin
    """
    for addr in symbols_to_collect:
        tile_tb += f"""
        $display({tile_name}_inst.{tile_type}.{addr});
        """

    tile_tb += f"""
            #10;
        end

        $finish;

    end
    
    always begin
        #5 clk = ~clk;
    end
endmodule
    """

    # write this to a file
    with open(f"{app_dir}/{tile_name}_simulation_tb.v", "w") as f:
        f.write(tile_tb)

    sources = [
        f"{app_dir}/{tile_name}_simulation_tb.v",
        f"{app_dir}/{tile_name}_simulation.v",
        f"/aha/garnet/garnet.v",
    ]

    vtile_name = tile_name.replace("$", "_")

    # Run the simulation using icarus
    cmd = [
        "iverilog",
        "-o",
        f"{app_dir}/{vtile_name}_simulation_tb",
        *sources,
        "-s",
        f"{tile_name}_simulation_tb",
    ]

    # print("Running command", cmd)
    sim_res = subprocess.run(cmd, capture_output=True, text=True)
    # check for errors
    if sim_res.returncode != 0:
        print("Error running iverilog")
        print(sim_res.stderr)
        breakpoint()

    # Run the simulation
    cmd = [f"{app_dir}/{vtile_name}_simulation_tb"]
    # print("Running command", cmd)
    sim_res = subprocess.run(cmd, capture_output=True, text=True)

    # check for errors
    if sim_res.returncode != 0:
        print("Error running testbench")
        print(sim_res.stderr)
        breakpoint()

    sim_res = sim_res.stdout.split("\n")
    sim_res = [s.strip() for s in sim_res if s != ""]

    # Deinterleave sim_res
    addr_out = {}

    for addr in symbols_to_collect:
        addr_out[addr] = []

    while sim_res:
        for addr in symbols_to_collect:
            addr_out[addr].append(int(sim_res.pop(0)))

    return addr_out
