from verified_agile_hardware.lake_utils import mem_tile_constraint_generator


def test_addr_gen_model():

    config_dict = {}
    config_dict["starting_addr"] = 4
    config_dict["dimensionality"] = 2
    config_dict["strides_0"] = 1
    config_dict["strides_1"] = 64
    config_dict["ranges_0"] = 63
    config_dict["ranges_1"] = 64

    addr_out, dim_out = mem_tile_constraint_generator(config_dict, 100)

    assert addr_out[0] == 4
    assert addr_out[1] == 4
    assert addr_out[2] == 4
    assert addr_out[3] == 4
    assert addr_out[4] == 4
    assert addr_out[5] == 5
    assert addr_out[66] == 66
    assert addr_out[67] == 68
    assert addr_out[68] == 68
    assert addr_out[69] == 69

    assert dim_out[0] == [0, 0]
    assert dim_out[1] == [0, 0]
    assert dim_out[2] == [0, 0]
    assert dim_out[3] == [0, 0]
    assert dim_out[4] == [0, 0]
    assert dim_out[5] == [1, 0]
    assert dim_out[66] == [62, 0]
    assert dim_out[67] == [0, 1]
    assert dim_out[68] == [0, 1]
    assert dim_out[69] == [1, 1]
