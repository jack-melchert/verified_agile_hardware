from gemstone.common.configurable import ConfigRegister
import re


def get_config_addr(self, reg_addr: int, feat_addr: int, x: int, y: int):
    tile_id = self.get_tile_id(x, y)
    tile = self.tile_circuits[(x, y)]
    addr = (reg_addr << tile.feature_config_slice.start) | (
        feat_addr << tile.tile_id_width
    )
    addr = addr | tile_id
    return addr


def get_garnet_inputs(solver):
    input_vars = []
    for i in solver.fts.inputvars:
        solver.fts.promote_inputvar(i)
        input_vars.append(i)

    input_vars = sorted(input_vars, key=lambda x: str(x))

    input_dict = {}
    for i in input_vars:
        input_dict[str(i)] = i

    return input_dict


def get_garnet_btor_outputs(solver, btor_filename):
    output_symbols = {}
    with open(btor_filename) as f:
        for line in f:
            if " output " in line:
                output_var = line.split()[3]
                output_symbols[output_var] = solver.fts.lookup(output_var)

    return output_symbols


def config_garnet(
    interconnect, bitstream, garnet_filename, configed_garnet_filename, interconnect_def, placement, id_to_name
):

    bitstream_dict = {b[0]: b[1] for b in bitstream}

    used_bitstreams = set()

    config = {}

    for loc, tile in interconnect.tile_circuits.items():
        for feature in tile.features():
            for child in feature.children():
                if isinstance(child, ConfigRegister):
                    if feature.instance_name is None:
                        # print(tile.instance_name, feature.name() + "_inst0", child.instance_name, "none")
                        name = f"\{tile.instance_name}.{feature.name()}_inst0.{child.instance_name}_O"
                    else:
                        # print(tile.instance_name, feature.instance_name, child.instance_name)
                        name = f"\{tile.instance_name}.{feature.instance_name}.{child.instance_name}_O"

                    feature_addr = tile.features().index(feature)
                    child_addr = child.addr
                    tile_id_width = tile.tile_id_width
                    slice_start = tile.feature_config_slice.start
                    tile_id = interconnect.get_tile_id(*loc)
                    addr = (
                        tile_id
                        | (child_addr << slice_start)
                        | (feature_addr << tile_id_width)
                    )
                    if addr in bitstream_dict:
                        config[name] = {
                            "width": child.width,
                            "addr": addr,
                            "value": bitstream_dict[addr],
                        }
                        print(name, addr, bitstream_dict[addr])
                        used_bitstreams.add(addr)
                    else:
                        config[name] = {"width": child.width, "addr": addr, "value": 0}

    for addr in bitstream_dict:
        if addr not in used_bitstreams:
            print(f"Unused bitstream: {addr}")

    IOs = []

    for id, loc in placement.items():
        if "I" in id:
            name = id_to_name[id]

            if "io16in" in name:
                prefix = "glb2io_16"
            else:
                prefix = "io2glb_16"
            
        elif "i" in id:
            name = id_to_name[id]

            if "io16in" in name:
                prefix = "glb2io_1"
            else:
                prefix = "io2glb_1"

        x = loc[0]
        y = loc[1]
        x_hex = hex(x)[2:]
        y_hex = hex(y)[2:]

        if len(x_hex) == 1:
            x_hex = "0" + x_hex

        if len(y_hex) == 1:
            y_hex = "0" + y_hex

        IOs.append(
            f"{prefix}_X{x_hex}_Y{y_hex}"
        )

    interconnect_def_new = interconnect_def.split()[0:3]

    discarded_inputs = []

    

    for line in interconnect_def.split()[3:-1]:
        used_input = False

        for IO in IOs:
            if IO in line:
                used_input = True
        for l in ['clk', 'flush', 'reset', 'stall']:
            if l in line:
                used_input = True


        if used_input:
            interconnect_def_new.append(line)
        else:
            discarded_inputs.append(line.replace(",", "") + ";")


    interconnect_def_new.append(interconnect_def.split()[-1])

    interconnect_def_new = "\n".join(interconnect_def_new)

    # Read in garnet file and write out to configed_garnet_filename



    with open(garnet_filename, "r") as f:
        garnet_lines = f.readlines()

    f = open(configed_garnet_filename, "w")

    reading_inputs = False
    reading_unused_inputs = False
    found_interconnect_def = False

    for line in garnet_lines:

        if "module Interconnect" in line:
            found_interconnect_def = True

        if found_interconnect_def and ");" in line:
            found_interconnect_def = False
            f.write(interconnect_def_new)
            continue

        if found_interconnect_def:
            continue

        if reading_inputs:
            f.write(line)
            f.write(
                f"  assign {signal} = {config[signal]['width']}'d{config[signal]['value']};\n"
            )
            reading_inputs = False
        elif reading_unused_inputs:
            reading_unused_inputs = False
        else:

            ls = line.split()
            if len(ls) > 1 and ls[0] == "input":
                if ls[1][0] == "\\":
                    signal = ls[1]
                elif len(ls) > 2 and ls[2][0] == "\\":
                    signal = ls[2]
                else:
                    signal = ls[-1]

                if signal in config:
                    reading_inputs = True

                if signal in discarded_inputs:
                    reading_unused_inputs = True

            ls = line.split()
            if len(ls) > 1 and ls[0] == "output":
                if ls[1][0] == "\\":
                    signal = ls[1]
                elif len(ls) > 2 and ls[2][0] == "\\":
                    signal = ls[2]
                else:
                    signal = ls[-1]

                if signal in discarded_inputs:
                    reading_unused_inputs = True

            if not (reading_inputs or reading_unused_inputs):
                f.write(line)

    f.close()


def remove_config_regs(garnet_filename, configed_garnet_filename):

    # Read in garnet file and write out to configed_garnet_filename
    with open(garnet_filename, "r") as f:
        garnet_lines = f.readlines()

    f = open(configed_garnet_filename, "w")

    found_config = False

    for line in garnet_lines:

        if "ConfigRegister" in line and "config_reg_" in line:
            found_config = True

        if not found_config:
            f.write(line)

        if ");" in line and found_config:
            found_config = False

    f.close()
