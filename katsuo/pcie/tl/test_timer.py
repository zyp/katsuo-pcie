from amaranth import *
from amaranth.lib import wiring

from amaranth_soc import csr

class TestTimer(wiring.Component):
    def __init__(self):
        super().__init__({
            'bus': wiring.In(csr.Signature(addr_width = 12, data_width = 8)),
            'irq': wiring.Out(1),
        })

        regs = csr.Builder(addr_width = 12, data_width = 8)

        self.cnt = regs.add('cnt', offset = 0x00, reg = csr.Register(csr.Field(csr.action.R, 32), access="r")) 

        self._bridge = csr.Bridge(regs.as_memory_map())
        self.bus.memory_map = self._bridge.bus.memory_map

    def elaborate(self, platform):
        m = Module()

        limit = 125_000_000

        m.submodules.bridge = self._bridge
        wiring.connect(m, wiring.flipped(self.bus), self._bridge.bus)

        cnt = Signal(range(limit))
        m.d.comb += self.cnt.f.r_data.eq(cnt)
        m.d.sync += cnt.eq(cnt + 1)

        with m.If(cnt == limit - 1):
            m.d.sync += cnt.eq(0)
            m.d.comb += self.irq.eq(1)

        return m
