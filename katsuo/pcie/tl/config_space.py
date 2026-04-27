from amaranth import *
from amaranth.lib import wiring
from amaranth.sim import Simulator, SimulatorContext

from amaranth_soc import csr
from amaranth_soc.csr import reg

from .capability import *

from .msi import MsiCapability

class CommandRegister(csr.Register, access = 'rw'):
    def __init__(self):
        super().__init__({
            'io_space_enable': csr.Field(csr.action.RW, 1),
            'memory_space_enable': csr.Field(csr.action.RW, 1),
            'bus_master_enable': csr.Field(csr.action.RW, 1),
            'special_cycle_enable': csr.Field(ConstantAction, 1, 0),
            'memory_write_and_invalidate': csr.Field(ConstantAction, 1, 0),
            'vga_palette_snoop': csr.Field(ConstantAction, 1, 0),
            'parity_error_response': csr.Field(ConstantAction, 1, 0), # TODO: mandatory?
            'idsel_stepping_wait_cycle_control': csr.Field(ConstantAction, 1, 0),
            'serr_enable': csr.Field(ConstantAction, 1, 0), # TODO: mandatory?
            'fast_back_to_back_transactions_enable': csr.Field(ConstantAction, 1, 0),
            'interrupt_disable': csr.Field(ConstantAction, 1, 0), # May be used
        })

class BaseAddressRegister(csr.Register, access = 'rw'):
    def __init__(self, addr_width, *, type = 0):
        super().__init__({
            'constant': csr.Field(ConstantAction, addr_width, type),
            'addr': csr.Field(csr.action.RW, 32 - addr_width),
        })

class ConfigurationSpace(wiring.Component):
    def __init__(self):
        super().__init__({
            'bus': wiring.In(csr.Signature(addr_width = 12, data_width = 8)),
        })

        self.msi = MsiCapability()

        capabilities = [
            PcieCapability(),
            self.msi,
            PmCapability(),
        ]

        regs = csr.Builder(addr_width = 12, data_width = 8)

        regs.add('vendor_id', offset = 0x00, reg = Constant(16, 0x1234)) 
        regs.add('device_id', offset = 0x02, reg = Constant(16, 0x5678))
        regs.add('command', offset = 0x04, reg = CommandRegister())
        regs.add('status', offset = 0x06, reg = Constant(16, 0x0010))

        regs.add('revision_id', offset = 0x08, reg = Constant(8, 0x00))
        regs.add('class_code', offset = 0x09, reg = Constant(24, 0xff0000))

        regs.add('header_type', offset = 0x0e, reg = Constant(8, 0x00))

        regs.add('bar0', offset = 0x10, reg = BaseAddressRegister(addr_width = 20))
        #regs.add('bar1', offset = 0x14, reg = BaseAddressRegister(addr_width = 12, type = 1))
        regs.add('cap_ptr', offset = 0x34, reg = Constant(8, 0x40))

        offset = 0x40
        for cap in capabilities[:-1]:
            cap._add_registers(regs, offset = offset, next = offset + cap._size)
            offset += cap._size
        capabilities[-1]._add_registers(regs, offset = offset, next = 0)

        self._bridge = csr.Bridge(regs.as_memory_map())
        self.bus.memory_map = self._bridge.bus.memory_map

    def elaborate(self, platform):
        m = Module()

        m.submodules.bridge = self._bridge
        wiring.connect(m, wiring.flipped(self.bus), self._bridge.bus)

        return m

try:
    from tlp import CfgRd0, CfgWr0
except ImportError:
    pass
else:
    class SimConfigurationSpace:
        def __init__(self):
            self.dut = ConfigurationSpace()
            self.sim = Simulator(self.dut)
            self.sim.add_clock(125e-6)
            self.sim.add_testbench(self.testbench, background = True)
            self.request = None
            self.response = None
        
        async def testbench(self, ctx: SimulatorContext):
            with ctx.critical():
                await ctx.tick()
            while True:
                if self.request is not None:
                    tlp = self.request
                    self.request = None
                    with ctx.critical():
                        match tlp:
                            case CfgRd0():
                                data = await self.read(ctx, tlp.address, tlp.first_be)
                                print(f'R: {tlp.first_be:04b} {tlp.address:03x}: {int.from_bytes(data, 'little'):08x}')
                                self.response = tlp.completion(data = data)
                            case CfgWr0():
                                await self.write(ctx, tlp.address, tlp.first_be, tlp.data)
                                print(f'W: {tlp.first_be:04b} {tlp.address:03x}: {int.from_bytes(tlp.data, 'little'):08x}')
                                self.response = tlp.completion()
                await ctx.tick()

        async def read(self, ctx: SimulatorContext, address: int, be: int):
            buf = bytearray(4)
            for i in range(4):
                if be & (1 << i):
                    ctx.set(self.dut.bus.addr, address + i)
                    ctx.set(self.dut.bus.r_stb, 1)
                    #*_, buf[i] = await ctx.tick().sample(self.dut.bus.r_data)
                    await ctx.tick()
                    buf[i] = ctx.get(self.dut.bus.r_data)
                ctx.set(self.dut.bus.r_stb, 0)
            return bytes(buf)
        
        async def write(self, ctx: SimulatorContext, address: int, be: int, data: bytes):
            for i in range(4):
                if be & (1 << i):
                    ctx.set(self.dut.bus.addr, address + i)
                    ctx.set(self.dut.bus.w_data, data[i])
                    ctx.set(self.dut.bus.w_stb, 1)
                    await ctx.tick()
                ctx.set(self.dut.bus.w_stb, 0)

        def handle(self, tlp):
            self.request = tlp
            self.response = None
            while self.request is not None:
                self.sim.run()
            return self.response

    if __name__ == '__main__':
        foo = SimConfigurationSpace()
        with foo.sim.write_vcd('config_space.vcd'):
            res = foo.handle(CfgRd0(requester_id = 0x9abc, tag = 0x12, first_be = 0b1111, bus_device_function = 0x0008_0000, address = 0x00))
            print(res)
