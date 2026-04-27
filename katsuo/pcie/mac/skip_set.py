from amaranth import *
from amaranth.lib import wiring, data, stream

from katsuo.stream import Packet

from ..code import Symbol

class SkipSetSender(wiring.Component):
    def __init__(self, width):
        assert width in (1, 2, 4)
        super().__init__({
            'o': wiring.Out(stream.Signature(Packet(data.ArrayLayout(Symbol, width)))),
        })

        self._width = width

    def elaborate(self, platform):
        m = Module()

        # According to the PCIe spec, skip sets should be sent at an average rate of 1180-1538 symbol times.
        interval = 1180 // self._width # TODO: Dividing by width is not necessarily correct, we could be running a double-wide stream at half duty.

        pending = Signal(range(4))
        inc_pending = Signal()
        dec_pending = Signal()
        cnt = Signal(range(interval), init = interval - 1)

        m.d.sync += cnt.eq(cnt - 1)
        with m.If(cnt == 0):
            m.d.sync += cnt.eq(interval - 1)
            m.d.comb += inc_pending.eq(1)

        with m.If(inc_pending & ~dec_pending):
            m.d.sync += pending.eq(pending + 1)
        with m.Elif(~inc_pending & dec_pending):
            m.d.sync += pending.eq(pending - 1)

        idx = Signal(range(4 // self._width))

        m.d.sync += self.o.valid.eq(0)
        m.d.sync += self.o.p.last.eq(0)
        with m.If((pending > 0) | (idx > 0)):
            m.d.sync += self.o.valid.eq(1)
            m.d.sync += idx.eq(idx + 1)

        for i in range(4 // self._width):
            with m.If(idx == i):
                for j in range(self._width):
                    data = self.o.p.data[j]
                    match i * self._width + j:
                        case 0:
                            m.d.sync += data.eq(Symbol.COM)
                        case 1:
                            m.d.sync += data.eq(Symbol.SKP)
                        case 2:
                            m.d.sync += data.eq(Symbol.SKP)
                        case 3:
                            m.d.sync += data.eq(Symbol.SKP)
                            m.d.sync += self.o.p.last.eq(1)
                            m.d.comb += dec_pending.eq(1)

        # Keep previous state if output not accepted.
        with m.If(self.o.valid & ~self.o.ready):
            m.d.sync += self.o.p.eq(self.o.p)
            m.d.sync += self.o.valid.eq(1)
            m.d.sync += idx.eq(idx)
            m.d.comb += dec_pending.eq(0)

        return m
