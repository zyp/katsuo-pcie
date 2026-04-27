from amaranth import *

from amaranth_soc import csr
from amaranth_soc.csr import reg

class ConstantAction(reg.FieldAction):
    def __init__(self, shape, value):
        super().__init__(shape, access = 'r')
        self._value = value
    
    def elaborate(self, platform):
        m = Module()
        m.d.comb += self.port.r_data.eq(self._value)
        return m

class Constant(csr.Register, access = 'r'):
    def __init__(self, shape, value):
        super().__init__({
            'value': csr.Field(ConstantAction, shape, value),
        })

class Variable(csr.Register, access = 'rw'):
    def __init__(self, shape, init = 0):
        super().__init__({
            'value': csr.Field(csr.action.RW, shape, init = init),
        })

class CapabilityStructure:
    def __init__(self, *, id: int, name: str, size: int):
        self._id = id
        self._name = name
        self._size = size # Auto size if None?
        self._registers = []

    def add(self, offset: int, name: str, reg: csr.Register):
        self._registers.append((name, offset, reg))
        # TODO: Check offset
        setattr(self, name, reg)

    def _add_registers(self, builder, offset, next):
        with builder.Cluster(f'cap_{self._name}'):
            builder.add('id', offset = offset + 0x00, reg = Constant(8, self._id))
            builder.add('next', offset = offset + 0x01, reg = Constant(8, next))

            for name, reg_offset, reg in self._registers:
                builder.add(name, offset = offset + reg_offset, reg = reg)

class PmCapability(CapabilityStructure):
    def __init__(self):
        super().__init__(id = 0x01, name = 'pm', size = 8)

        self.add(0x02, 'pmc', Constant(16, 0x0003))

class PcieCapability(CapabilityStructure):
    def __init__(self):
        super().__init__(id = 0x10, name = 'pcie', size = 60)

        self.add(0x02, 'capabilities', Constant(16, 0x0002))
        self.add(0x04, 'device_capabilities', Constant(32, 0x00008000))
        self.add(0x08, 'device_control', Constant(16, 0x0810))
        self.add(0x0a, 'device_status', Constant(16, 0x0000))
        self.add(0x0c, 'link_capabilities', Constant(32, 0x00000011))
        self.add(0x10, 'link_control', Constant(16, 0x0000))
        self.add(0x12, 'link_status', Constant(16, 0x0011))
        self.add(0x24, 'device_capabilities_2', Constant(32, 0))
        self.add(0x28, 'device_control_2', Constant(16, 0))
        self.add(0x2a, 'device_status_2', Constant(16, 0))
        self.add(0x2c, 'link_capabilities_2', Constant(32, 0x00000002))
        self.add(0x30, 'link_control_2', Constant(16, 0))
        self.add(0x32, 'link_status_2', Constant(16, 0))
