def transform_config(config):
    transformed_config = {}

    transformed_config["starting_addr"] = config["cycle_starting_addr"][0]
    transformed_config["dimensionality"] = len(config["cycle_stride"])

    for i in range(transformed_config["dimensionality"]):
        if "cycle_stride" in config:
            transformed_config[f"strides_{i}"] = config["cycle_stride"][i]

        if "extent" in config:
            transformed_config[f"ranges_{i}"] = config["extent"][i]

    return transformed_config


def lake_config_to_config(config_dict, lake_configs):
    config_to_controller["stencil_valid"] = "stencil_valid"
    config_to_controller["in2agg_0"] = "agg_only_0"
    config_to_controller["in2agg_1"] = "agg_only_1"
    config_to_controller["sram2tb_0"] = "sram_tb_shared_0"
    config_to_controller["sram2tb_1"] = "sram_tb_shared_1"
    config_to_controller["tb2out_0"] = "tb_only_0"
    config_to_controller["tb2out_1"] = "tb_only_1"

    config = config_dict.copy()

    for controller, controller_config in config["config"].items():
        for k, v in controller_config.items():
            config["config"][controller][k] = v

    return config


class AddresssGeneratorModel:
    def __init__(self, name, iterator_support, address_width):
        self.name = name
        self.iterator_support = iterator_support
        self.address_width = address_width

        self.config = {}

        self.config["starting_addr"] = 0
        self.config["dimensionality"] = 0

        self.address = 0

        for i in range(self.iterator_support):
            self.config[f"strides_{i}"] = 0

    def set_config(self, new_config):
        for key, config_val in new_config.items():
            if key not in self.config:
                AssertionError("Gave bad config...")
            else:
                self.config[key] = config_val

        self.address = self.config["starting_addr"]

    def get_address(self):
        return self.address

    def step(self, curr_dim):
        offset = self.config[f"strides_{curr_dim}"]
        self.address = self.address + offset

        if self.address >= 2**self.address_width:
            self.address = 0


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
            if key not in self.config:
                AssertionError("Gave bad config...")
            else:
                self.config[key] = config_val
        for i in range(self.iterator_support):
            self.dim_cnt[i] = 0
        self.address = 0 + self.config["starting_addr"]

    def get_address(self):
        return self.address

    def step(self):
        for i in range(self.config["dimensionality"]):
            if i == 0:
                update_curr = True

            if update_curr:
                self.dim_cnt[i] = self.dim_cnt[i] + 1
                if self.dim_cnt[i] == self.config[f"ranges_{i}"]:
                    self.dim_cnt[i] = 0
                else:
                    break
            else:
                break

        self.address = self.config["starting_addr"]
        for i in range(self.config["dimensionality"]):
            offset = self.dim_cnt[i] * self.config[f"strides_{i}"]
            self.address = self.address + offset


def simulate_mem_tile_counters(
    config, lake_configs, cycles, iterator_support, address_width=16
):
    # So in order to get the valid starting address, dim count, read address, and write address, we need to run the
    # SchedGenModel for a number of cycles and record the outputs at each cycle

    # Unfortunately, lake doesn't have a real model of the memory tile behavior, so this will be fairly hardcoded

    # 4 address generator models: 1 for each of the 4 memory controllers
    agg_only_agg_write_sched_gen_0 = SchedGenModel(
        "agg_only_agg_write_sched_gen_0",
        iterator_support=iterator_support,
        address_width=address_width,
    )
    agg_sram_shared_agg_read_sched_gen_0 = SchedGenModel(
        "agg_sram_shared_agg_read_sched_gen_0",
        iterator_support=iterator_support,
        address_width=address_width,
    )
    sram_tb_shared_output_sched_gen_0 = SchedGenModel(
        "sram_tb_shared_output_sched_gen_0",
        iterator_support=iterator_support,
        address_width=address_width,
    )
    tb_only_tb_read_sched_gen_0 = SchedGenModel(
        "tb_only_tb_read_sched_gen_0",
        iterator_support=iterator_support,
        address_width=address_width,
    )

    # Times 2 for dual ported memory
    agg_only_agg_write_sched_gen_1 = SchedGenModel(
        "agg_only_agg_write_sched_gen_1",
        iterator_support=iterator_support,
        address_width=address_width,
    )
    agg_sram_shared_agg_read_sched_gen_1 = SchedGenModel(
        "agg_sram_shared_agg_read_sched_gen_1",
        iterator_support=iterator_support,
        address_width=address_width,
    )
    sram_tb_shared_output_sched_gen_1 = SchedGenModel(
        "sram_tb_shared_output_sched_gen_1",
        iterator_support=iterator_support,
        address_width=address_width,
    )
    tb_only_tb_read_sched_gen_1 = SchedGenModel(
        "tb_only_tb_read_sched_gen_1",
        iterator_support=iterator_support,
        address_width=address_width,
    )

    # One for stencil valid
    stencil_valid = SchedGenModel(
        "stencil_valid", iterator_support=iterator_support, address_width=address_width
    )

    # Now we have to do address generator simulation as well (this is different from the AddGenModel even though the name is the same)
    sram_only_output_addr_gen_0 = AddresssGeneratorModel(
        "sram_only_output_addr_gen_0",
        iterator_support=iterator_support,
        address_width=9,
    )
    sram_only_output_addr_gen_1 = AddresssGeneratorModel(
        "sram_only_output_addr_gen_1",
        iterator_support=iterator_support,
        address_width=9,
    )
    tb_only_tb_read_addr_gen_0 = AddresssGeneratorModel(
        "tb_only_tb_read_addr_gen_0", iterator_support=iterator_support, address_width=4
    )
    tb_only_tb_read_addr_gen_1 = AddresssGeneratorModel(
        "tb_only_tb_read_addr_gen_1", iterator_support=iterator_support, address_width=4
    )

    agg_only_agg_write_addr_gen_0 = AddresssGeneratorModel(
        "agg_only_agg_write_addr_gen_0",
        iterator_support=iterator_support,
        address_width=3,
    )
    agg_only_agg_write_addr_gen_1 = AddresssGeneratorModel(
        "agg_only_agg_write_addr_gen_1",
        iterator_support=iterator_support,
        address_width=3,
    )
    tb_only_tb_write_addr_gen_0 = AddresssGeneratorModel(
        "tb_only_tb_write_addr_gen_0",
        iterator_support=iterator_support,
        address_width=4,
    )
    tb_only_tb_write_addr_gen_1 = AddresssGeneratorModel(
        "tb_only_tb_write_addr_gen_1",
        iterator_support=iterator_support,
        address_width=4,
    )

    # config = lake_config_to_config(config_dict, lake_configs)
    lake_configs = {k: v for k, v in lake_configs}

    # For some reason mapping from config to controllers is this:
    config_to_controller = {}

    config_to_controller["stencil_valid"] = stencil_valid
    config_to_controller["in2agg_0"] = agg_only_0
    config_to_controller["in2agg_1"] = agg_only_1
    config_to_controller["sram2tb_0"] = sram_tb_shared_0
    config_to_controller["sram2tb_1"] = sram_tb_shared_1
    config_to_controller["tb2out_0"] = tb_only_0
    config_to_controller["tb2out_1"] = tb_only_1

    # Read config and configure each controller
    for controller, controller_config in config["config"].items():
        if controller in config_to_controller:
            transformed_config = transform_config(controller_config)
            config_to_controller[controller].set_config(transformed_config)

    config_to_read_controller = {}
    config_to_read_controller["sram2tb_0"] = (
        "sram_only_output_addr_gen_0",
        sram_only_output_addr_gen_0,
    )
    config_to_read_controller["sram2tb_1"] = (
        "sram_only_output_addr_gen_1",
        sram_only_output_addr_gen_1,
    )
    config_to_read_controller["tb2out_0"] = (
        "tb_only_tb_read_addr_gen_0",
        tb_only_tb_read_addr_gen_0,
    )
    config_to_read_controller["tb2out_1"] = (
        "tb_only_tb_read_addr_gen_1",
        tb_only_tb_read_addr_gen_1,
    )

    config_to_write_controller = {}
    config_to_write_controller["in2agg_0"] = (
        "agg_only_agg_write_addr_gen_0",
        agg_only_agg_write_addr_gen_0,
    )
    config_to_write_controller["in2agg_1"] = (
        "agg_only_agg_write_addr_gen_1",
        agg_only_agg_write_addr_gen_1,
    )
    config_to_write_controller["sram2tb_0"] = (
        "tb_only_tb_write_addr_gen_0",
        tb_only_tb_write_addr_gen_0,
    )
    config_to_write_controller["sram2tb_1"] = (
        "tb_only_tb_write_addr_gen_1",
        tb_only_tb_write_addr_gen_1,
    )

    # addrgen_to_read_controller = {}
    # addrgen_to_read_controller[sram_tb_shared_0] = sram_only_output_addr_gen_0
    # addrgen_to_read_controller[sram_tb_shared_1] = sram_only_output_addr_gen_1
    # addrgen_to_read_controller[tb_only_0] = tb_only_tb_read_addr_gen_0
    # addrgen_to_read_controller[tb_only_1] = tb_only_tb_read_addr_gen_1

    # addrgen_to_write_controller = {}
    # addrgen_to_write_controller[agg_only_0] = agg_only_agg_write_addr_gen_0
    # addrgen_to_write_controller[agg_only_1] = agg_only_agg_write_addr_gen_1
    # addrgen_to_write_controller[tb_only_0] = tb_only_tb_write_addr_gen_0
    # addrgen_to_write_controller[tb_only_1] = tb_only_tb_write_addr_gen_1

    # Config each address generator
    for controller, controller_config in config["config"].items():
        if controller in config_to_read_controller:
            lake_name = config_to_read_controller[controller][0]
            new_config = {}
            new_config["cycle_starting_addr"] = [
                lake_configs[lake_name + "_starting_addr"]
            ]

            strides = []
            for i in range(controller_config["dimensionality"]):
                strides.append(lake_configs[lake_name + "_strides_" + str(i)])

            new_config["cycle_stride"] = strides
            config_to_read_controller[controller][1].set_config(
                transform_config(new_config)
            )

        if controller in config_to_write_controller:
            lake_name = config_to_write_controller[controller][0]
            new_config = {}
            new_config["cycle_starting_addr"] = [
                lake_configs[lake_name + "_starting_addr"]
            ]

            strides = []
            for i in range(controller_config["dimensionality"]):
                strides.append(lake_configs[lake_name + "_strides_" + str(i)])

            new_config["cycle_stride"] = strides
            config_to_write_controller[controller][1].set_config(
                transform_config(new_config)
            )

    addr_out = {}
    dim_out = {}
    read_addr_out = {}
    write_addr_out = {}

    for controller_name in config_to_controller:
        addr_out[controller_name] = []
        dim_out[controller_name] = []

        if controller_name in config_to_read_controller:
            read_addr_out[controller_name] = []

        if controller_name in config_to_write_controller:
            write_addr_out[controller_name] = []

    for cycle in range(cycles):
        # Collect outputs
        for controller_name in config_to_controller:
            controller = config_to_controller[controller_name]
            addr_out[controller_name].append(controller.get_address())
            dim_out[controller_name].append(controller.dim_cnt.copy())

            # read address gen
            if controller_name in config_to_read_controller:
                read_controller = config_to_read_controller[controller_name][1]
                read_addr_out[controller_name].append(read_controller.get_address())

            # write address gen
            if controller_name in config_to_write_controller:
                write_controller = config_to_write_controller[controller_name][1]
                write_addr_out[controller_name].append(write_controller.get_address())

        # Step all controllers
        for controller_name in config_to_controller:
            controller = config_to_controller[controller_name]

            step_controller = cycle == controller.get_address()

            if step_controller:

                curr_dim = 0

                if controller in config["config"]:
                    extent = config["config"][controller_name]["extent"]

                    for i in range(len(extent)):
                        if (
                            controller.dim_cnt[i]
                            == config["config"][controller_name]["extent"][i]
                        ):
                            curr_dim = i
                            break

                if controller_name in config_to_read_controller:
                    read_controller = config_to_read_controller[controller_name][1]
                    read_controller.step(curr_dim)

                if controller_name in config_to_write_controller:
                    write_controller = config_to_write_controller[controller_name][1]
                    write_controller.step(curr_dim)

                controller.step()

    breakpoint()

    return addr_out, dim_out, read_addr_out, write_addr_out
