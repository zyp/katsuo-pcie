from amaranth import *
from amaranth.lib import stream, wiring, data

from katsuo.stream import Packet

class LaneAligner(wiring.Component):
    def __init__(self, *, shape, width, token, always_ready = True):
        super().__init__({
            'i': wiring.In(stream.Signature(data.ArrayLayout(shape, width), always_ready = always_ready)),
            'o': wiring.Out(stream.Signature(data.ArrayLayout(shape, width), always_ready = always_ready)),
        })

        self._shape = shape
        self._width = width
        self._token = token

    def elaborate(self, platform):
        m = Module()

        buf = Signal(data.ArrayLayout(self._shape, self._width * 2))
        skew = Signal(range(self._width))

        m.d.comb += [
            buf[self._width:].eq(self.i.p),
            self.o.valid.eq(self.i.valid),
        ]

        if not self.i.signature.always_ready:
            m.d.comb += self.i.ready.eq(self.o.ready)

        with m.Switch(skew):
            for i in range(self._width):
                with m.Case(i):
                    m.d.comb += self.o.p.eq(buf[i:i+self._width])

        with m.If(self.i.valid & self.i.ready):
            m.d.sync += buf[:self._width].eq(buf[self._width:])

            for i in range(self._width):
                with m.If(buf[self._width + i] == self._token):
                    m.d.sync += skew.eq(i)

        return m

class OverflowChecker(wiring.Component):
    '''Overflow checker for a stream of packets.

    Input is always ready, and any overflow will cause the current packet to be dropped.

    Args:
        packet: Packet shape.

    Attributes:
        i (stream): Input stream.
        o (stream): Output stream.
    '''

    def __init__(self, *, packet: Packet):
        if not isinstance(packet, Packet):
            raise TypeError('packet must be an instance of Packet')
        
        if not packet.semantics.has_first:
            raise TypeError('packet must support discard')

        super().__init__({
            'i': wiring.In(stream.Signature(packet, always_ready = True)),
            'o': wiring.Out(stream.Signature(packet)),
        })

    def elaborate(self, platform):
        m = Module()

        overflow = Signal()

        m.d.comb += [
            self.o.valid.eq(self.i.valid),
            self.o.p.eq(self.i.p),
        ]

        # Clear overflow when a new packet starts.
        with m.If(self.i.valid & self.i.p.first):
            m.d.sync += overflow.eq(0)

        # Set overflow when the output is valid but not ready.
        with m.If(self.o.valid & ~self.o.ready):
            m.d.sync += overflow.eq(1)

        # Drop remaining data when the overflow flag is set and we're not at the start of a new packet.
        with m.If(overflow & ~self.o.p.first):
            m.d.comb += self.o.valid.eq(0)
        
        return m
