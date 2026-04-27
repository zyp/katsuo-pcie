from amaranth import *
from amaranth.lib import wiring, stream, data

from katsuo.stream import Packet

from .packet import MemHeader, Type, ID
from .capability import CapabilityStructure, Variable

class MsiCapability(CapabilityStructure):
    def __init__(self):
        super().__init__(id = 0x05, name = 'msi', size = 12)

        self.add(0x02, 'message_control', Variable(16, 0x0002))
        self.add(0x04, 'message_address', Variable(32))
        self.add(0x08, 'message_data', Variable(16))

class MsiHandler(wiring.Component):
    def __init__(self, *, width = 4, msi_cap):
        assert width == 4
        super().__init__({
            'o': wiring.Out(stream.Signature(Packet(data.ArrayLayout(8, width), header_shape = MemHeader()))),
            'id': wiring.In(ID),
            'irq': wiring.In(1),
        })
        self._msi_cap = msi_cap

    def elaborate(self, platform):
        m = Module()

        irq_pending = Signal()

        m.d.comb += [
            self.o.p.h.type.eq(Type.MWr_32),
            self.o.p.h.length.eq(1),
            self.o.p.h.requester_id.eq(self.id),
            self.o.p.h.tag.eq(0),
            self.o.p.h.last_dw_be.eq(0),
            self.o.p.h.first_dw_be.eq(0x3),
            self.o.p.h.address_32.eq(self._msi_cap.message_address.f.value.data),
            self.o.p.d.eq(self._msi_cap.message_data.f.value.data),
            self.o.p.last.eq(1),
            self.o.valid.eq(irq_pending & self._msi_cap.message_control.f.value.data[0]),
        ]

        with m.If(self.irq):
            m.d.sync += irq_pending.eq(1)
        
        with m.If(self.o.valid & self.o.ready):
            m.d.sync += irq_pending.eq(0)

        return m
