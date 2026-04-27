from amaranth import *
from amaranth.lib import wiring, stream, data

from amaranth_soc import csr
from katsuo.stream import Packet

from .packet import Header, ConfigurationHeader, CompletionHeader, Type, ID

class ConfigurationHandler(wiring.Component):
    def __init__(self, *, width = 4):
        assert width == 4
        super().__init__({
            'i': wiring.In(stream.Signature(Packet(data.ArrayLayout(8, width), header_shape = ConfigurationHeader()))),
            'o': wiring.Out(stream.Signature(Packet(data.ArrayLayout(8, width), header_shape = CompletionHeader()))),
            'bus': wiring.Out(csr.Signature(addr_width = 12, data_width = 8)),
            'id': wiring.Out(ID),
        })

    def elaborate(self, platform):
        m = Module()

        idx = Signal(range(5))
        read_be = Signal(4)
        write_be = Signal(4)

        with m.Switch(self.i.p.header.type):
            with m.Case(Type.CfgRd0):
                m.d.comb += self.o.p.h.type.eq(Type.CplD)
            with m.Case(Type.CfgWr0):
                m.d.comb += self.o.p.h.type.eq(Type.Cpl)

        m.d.comb += [
            self.o.p.h.length.eq(self.i.p.h.type == Type.CfgRd0),
            self.o.p.h.completer_id.eq(self.id),
            # TODO: status (although 0 is success)
            self.o.p.h.byte_count.eq(4),
            self.o.p.h.requester_id.eq(self.i.p.h.requester_id),
            self.o.p.h.tag.eq(self.i.p.h.tag),

            self.o.p.last.eq(1),
        ]

        with m.FSM() as fsm:
            with m.State('REQUEST'):
                with m.If(self.i.valid):
                    m.d.sync += self.id.eq(self.i.p.header.target_id)
                    m.d.sync += idx.eq(idx + 1)

                    with m.If(self.i.p.header.type == Type.CfgRd0):
                        m.d.comb += read_be.eq(self.i.p.header.first_dw_be)

                    with m.If(self.i.p.header.type == Type.CfgWr0):
                        m.d.comb += write_be.eq(self.i.p.header.first_dw_be)

                    with m.If(idx == 4):
                        m.d.sync += idx.eq(0)
                        m.next = 'COMPLETION'

            with m.State('COMPLETION'):
                m.d.comb += self.o.valid.eq(1)

                with m.If(self.o.ready):
                    m.d.comb += self.i.ready.eq(1)
                    m.next = 'REQUEST'

        m.d.comb += self.bus.addr.eq(Cat(idx[:2], self.i.p.header.register_number))
        for i in range(4):
            with m.If(idx == i):
                m.d.comb += [
                    self.bus.w_data.eq(self.i.p.data[i]),
                    self.bus.r_stb.eq(read_be[i]),
                    self.bus.w_stb.eq(write_be[i]),
                ]
            with m.If(idx == i + 1):
                m.d.sync += self.o.p.data[i].eq(self.bus.r_data)

        return m
