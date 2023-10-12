import kratos as kts
from lake.attributes.config_reg_attr import ConfigRegAttr
from lake.top.memory_interface import MemoryPort, MemoryPortExclusionAttr


class MemtileConfig(kts.Generator):
    def __init__(self, name, memtile_kts, configs):
        super().__init__(f"{name}_config")

        # self._clk = self.clock("clk")

        memtile_kts.core.CC.wrapper("/aha/test.sv", name)
        # self.add_child_generator(name, memtile_kts.core.dut)

        # kts.passes.create_module_instantiation(self[name].internal_generator)

        # self._rst_n = self.reset("rst_n")
        # self._clk_en = self.input("clk_en", 1)

        # for port_name, port in memtile_kts.core_interface.input_ports.items():
        #     self.port(port_name, port[0], kts.PortDirection.In)
        #     breakpoint()
        #     self.wire(self[name].ports[port_name], self.ports[port_name])

        # for port_name, port in memtile_kts.core_interface.output_ports.items():
        #     self.port(port_name, port[0], kts.PortDirection.Out)
        #     self.wire(self.ports[port_name], self[name].ports[port_name])

        # for config, config_port in configs:
        #     self.wire(self[name].internal_generator.get_port(config_port[0]), kts.const(config[1], config_port[1].width))

    def get_liftable_ports(self, module):
        """
        Use this method to return all other ports that can be safely lifted
        """
        liftable = []
        int_gen = module.internal_generator
        # Now get the config registers from the top definition
        for port_name in int_gen.get_port_names():
            curr_port = int_gen.get_port(port_name)
            attrs = curr_port.find_attribute(lambda a: isinstance(a, ConfigRegAttr))

            if len(attrs) == 0:
                liftable.append(curr_port)

        return liftable

    def lift_ports(self, module):
        liftable_ports = self.get_liftable_ports(self[module])
        for port in liftable_ports:
            pname = port.name
            if pname == "clk":
                tmp_clk = self.clock("clk")
                self.wire(tmp_clk, port)
            elif pname == "rst_n":
                tmp_rst = self.reset("rst_n")
                self.wire(tmp_rst, port)
            elif pname == "clk_en":
                tmp_clk_en = self.clock_en("clk_en")
                self.wire(tmp_clk_en, port)
            else:
                # Need to get the attributes and copy them up...
                port_attrs = port.attributes
                tmp_port = self.port_from_def(port, name=f"{port.name}_f")
                for attr in port_attrs:
                    tmp_port.add_attribute(attr)

                if kts.PortDirection.In == port.port_direction:
                    self.wire(tmp_port, port)
                else:
                    self.wire(port, tmp_port)
