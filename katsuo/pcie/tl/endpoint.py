from amaranth import *
from amaranth.lib import wiring, data, stream

from katsuo.stream import Packet, PriorityArbiter, Dispatcher, connect_pipeline

from katsuo import tilelink
from katsuo.tilelink import csr

from .packet import Packetizer, Depacketizer, TLP, Type

from .config_handler import ConfigurationHandler
from .config_space import ConfigurationSpace

from .msi import MsiHandler
from .mem_handler import MemHandler
from .test_timer import TestTimer

class Endpoint(wiring.Component):
    def __init__(self, *, width):
        super().__init__({
            'i': wiring.In(stream.Signature(Packet(data.ArrayLayout(8, width)))),
            'o': wiring.Out(stream.Signature(Packet(data.ArrayLayout(8, width)))),
        })

        self._width = width

    def elaborate(self, platform):
        m = Module()

        m.submodules.config_space = config_space = ConfigurationSpace()

        # RX pipeline
        m.submodules.depacketizer = depacketizer = Depacketizer(width = self._width)
        m.submodules.dispatcher = dispatcher = Dispatcher(TLP(self._width))

        connect_pipeline(m,
            wiring.flipped(self.i),
            depacketizer,
            dispatcher,
        )

        # TX pipeline
        m.submodules.arbiter = arbiter = PriorityArbiter(TLP(self._width))
        m.submodules.packetizer = packetizer = Packetizer(width = self._width)

        connect_pipeline(m,
            arbiter,
            packetizer,
            wiring.flipped(self.o),
        )

        # Config handler
        m.submodules.config_handler = config_handler = ConfigurationHandler(width = self._width)
        wiring.connect(m, config_handler.bus, config_space.bus)

        connect_pipeline(m,
            dispatcher.get_output(lambda p: Value.cast(p.h.type).matches(Type.CfgRd0, Type.CfgWr0)),
            config_handler,
            arbiter.get_input(),
        )

        # MSI handler
        m.submodules.msi_handler = msi_handler = MsiHandler(width = self._width, msi_cap = config_space.msi)
        m.d.comb += msi_handler.id.eq(config_handler.id)

        connect_pipeline(m,
            msi_handler,
            arbiter.get_input(),
        )

        # Memory handler
        m.submodules.mem_handler = mem_handler = MemHandler(width = self._width)
        m.d.comb += mem_handler.id.eq(config_handler.id)

        connect_pipeline(m,
            dispatcher.get_output(lambda p: Value.cast(p.h.type).matches(Type.MRd_32, Type.MWr_32)),
            mem_handler,
            arbiter.get_input(),
        )

        # Memory
        #m.submodules.memory = memory = tilelink.Memory(width = 4, size = 4096) 
        #wiring.connect(m, mem_handler.bus, memory.bus)

        m.submodules.csr_bridge = csr_bridge = csr.Bridge(width = self._width, addr_width = 12)
        wiring.connect(m, mem_handler.bus, csr_bridge.bus)

        # Test peripheral
        m.submodules.test_timer = test_timer = TestTimer()
        wiring.connect(m, csr_bridge.csr_bus, test_timer.bus)
        m.d.comb += msi_handler.irq.eq(test_timer.irq)

        # Blackhole unhandled packets.
        blackhole = dispatcher.get_output(lambda p: 1)
        m.d.comb += blackhole.ready.eq(1)

        with m.If(blackhole.valid):
            m.d.sync += Print(Format('Blackholing packet: {}', blackhole.p))

        return m
