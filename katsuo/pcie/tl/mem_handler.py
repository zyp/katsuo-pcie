from amaranth import *
from amaranth.lib import wiring, stream, data

from katsuo.stream import Packet

from katsuo import tilelink

from .packet import MemHeader, CompletionHeader, Type, ID

class MemHandler(wiring.Component):
    def __init__(self, *, width = 4):
        assert width == 4
        addr_width = 12
        #max_burst_size = 1 << addr_width
        max_burst_size = width
        super().__init__({
            'i': wiring.In(stream.Signature(Packet(data.ArrayLayout(8, width), header_shape = MemHeader()))),
            'o': wiring.Out(stream.Signature(Packet(data.ArrayLayout(8, width), header_shape = CompletionHeader()))),
            'bus': wiring.Out(tilelink.Signature(width = width, addr_width = addr_width, max_burst_size = max_burst_size)),
            'id': wiring.In(ID),
        })

    def elaborate(self, platform):
        m = Module()

        # wtf iverilog
        init = Signal()
        m.d.sync += init.eq(1)
        with m.If(init):
            m.d.comb += self.o.p.h.eq(0)

        # /wtf

        beat_idx = Signal(10)

        m.d.comb += [
            self.bus.a.address[2:].eq(self.i.p.h.address_auto[2:]),
            self.bus.a.data.eq(self.i.p.data),
            self.bus.a.mask.eq(self.i.p.h.first_dw_be),

            self.o.p.data.eq(self.bus.d.data),
            self.o.p.last.eq(beat_idx == self.o.p.h.length - 1),

            self.o.p.h.type.eq(Type.CplD),
            self.o.p.h.length.eq(Mux(self.bus.d.size > 1, (1 << self.bus.d.size)[2:], 1)),
            self.o.p.h.completer_id.eq(self.id),
            # TODO: status (although 0 is success)
            self.o.p.h.byte_count.eq(1 << self.bus.d.size),
            self.o.p.h.requester_id.eq(self.i.p.h.requester_id),
            self.o.p.h.tag.eq(self.i.p.h.tag),
        ]

        unsupported = Signal()

        with m.Switch(self.i.p.h.length):
            # TODO: Zero-length accesses are valid. They don't transfer data, but follow sequencing rules and can be used for barriers.
            with m.Case(1):
                with m.Switch(self.i.p.h.first_dw_be):
                    with m.Case(0x1, 0x2, 0x4, 0x8):
                        m.d.comb += self.bus.a.size.eq(0)
                    with m.Case(0x3, 0xc):
                        m.d.comb += self.bus.a.size.eq(1)
                    with m.Case(0xf):
                        m.d.comb += self.bus.a.size.eq(2)
                    with m.Default():
                        m.d.comb += unsupported.eq(1)
                with m.Switch(self.i.p.h.first_dw_be):
                    with m.Case(0x1, 0x3, 0xf):
                        m.d.comb += self.bus.a.address[:2].eq(0)
                    with m.Case(0x2):
                        m.d.comb += self.bus.a.address[:2].eq(1)
                    with m.Case(0x4, 0xc):
                        m.d.comb += self.bus.a.address[:2].eq(2)
                    with m.Case(0x8):
                        m.d.comb += self.bus.a.address[:2].eq(3)
            for i in range(1, 10):
                with m.Case(1 << i):
                    m.d.comb += self.bus.a.size.eq(i + 2)
                    with m.If((self.i.p.h.first_dw_be != 0xf) | (self.i.p.h.last_dw_be != 0xf) | (self.i.p.h.address_auto & ((4 << i) - 1) != 0)):
                        m.d.comb += unsupported.eq(1)
            with m.Default():
                m.d.comb += unsupported.eq(1)

        with m.FSM() as fsm:
            with m.State('IDLE'):
                with m.If(self.i.valid):
                    with m.Switch(self.i.p.header.type):
                        with m.Case(Type.MWr_32, Type.MWr_64):
                            m.next = 'WRITE'
                        with m.Case(Type.MRd_32, Type.MRd_64):
                            m.next = 'READ'
                    
                    with m.If(unsupported):
                        m.next = 'ABORT'
            
            with m.State('WRITE'):
                m.d.comb += [
                    self.i.ready.eq(self.bus.a.ready),
                    self.bus.a.valid.eq(self.i.valid),
                    self.bus.a.opcode.eq(tilelink.A.Opcode.PutFullData),
                ]

                with m.If(self.i.valid & self.i.p.last):
                    m.next = 'WRITE_ACK'

            with m.State('WRITE_ACK'):
                # This could technically arrive in the last cycle of the WRITE state if connected to a zero-latency memory,
                # but that's impractical, so we leave it out for now.
                m.d.comb += self.bus.d.ready.eq(1)
                with m.If(self.bus.d.valid):
                    m.next = 'IDLE'

            with m.State('READ'):
                m.d.comb += [
                    self.bus.a.valid.eq(1),
                    self.bus.a.opcode.eq(tilelink.A.Opcode.Get),
                ]
                m.d.sync += beat_idx.eq(0)

                with m.If(self.bus.a.ready):
                    m.next = 'READ_DATA'

            with m.State('READ_DATA'):
                m.d.comb += [
                    self.bus.d.ready.eq(self.o.ready),
                    self.o.valid.eq(self.bus.d.valid),
                ]

                with m.If(self.o.ready & self.o.valid):
                    m.d.sync += beat_idx.eq(beat_idx + 1)

                    with m.If(self.o.p.last):
                        m.d.comb += self.i.ready.eq(1)
                        m.next = 'IDLE'

            with m.State('ABORT'):
                # TODO: Return a completion with the CA status

                # Release the request.
                m.d.comb += self.i.ready.eq(1)

                with m.If(self.i.valid & self.i.p.last):
                    m.next = 'IDLE'

        return m
