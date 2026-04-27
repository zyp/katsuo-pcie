from amaranth import *
from amaranth.lib import wiring, data, stream, crc

from katsuo.stream import Packet, connect_pipeline

from .misc import LaneAligner
from ..code import Symbol

class DLLPacket(data.Struct):
    data: 32

class DLLPacketSender(wiring.Component):
    def __init__(self, phy_width):
        assert phy_width in (1, 2, 4, 8)
        super().__init__({
            'i': wiring.In(stream.Signature(DLLPacket)),
            'o': wiring.Out(stream.Signature(Packet(data.ArrayLayout(Symbol, phy_width)))),
            #'data': wiring.Out(data.ArrayLayout(Symbol, width)),
            #'valid': wiring.Out(1),
            #'done': wiring.Out(1),
        })

        self._width = phy_width

    def elaborate(self, platform):
        m = Module()

        payload = Signal(data.ArrayLayout(8, 4))
        m.d.comb += Value.cast(payload).eq(self.i.payload)

        m.submodules.crc = crc_module = crc.Algorithm(
            crc_width = 16,
            polynomial = 0x100b,
            initial_crc = 0xffff,
            reflect_input = True,
            reflect_output = True,
            xor_output = 0xffff,
        )(32).create()
        m.d.comb += [
            crc_module.start.eq(self.i.valid),
            crc_module.valid.eq(self.i.valid),
            crc_module.data.eq(self.i.payload),
        ]

        checksum = Signal(data.ArrayLayout(8, 2))
        m.d.comb += Value.cast(checksum).eq(crc_module.crc)

        idx = Signal(range(8 // self._width))
        #m.d.comb += self.i.ready.eq(idx == 8 // self._width - 1)

        #m.d.comb += self.done.eq((idx == 0) & self.valid)

        m.d.sync += self.o.valid.eq(0)
        m.d.sync += self.o.p.last.eq(0)
        with m.If(self.i.valid | ((idx > 0) & (idx < 3))):
            m.d.sync += self.o.valid.eq(1)
            m.d.sync += idx.eq(idx + 1)

        for i in range(8 // self._width):
            with m.If(idx == i):
                for j in range(self._width):
                    #lane = self.data[j]
                    lane = self.o.p.data[j]
                    match i * self._width + j:
                        case 0:
                            m.d.sync += lane.eq(Symbol.SDP)
                        case 1:
                            m.d.sync += lane.eq(payload[0])
                        case 2:
                            m.d.sync += lane.eq(payload[1])
                        case 3:
                            m.d.sync += lane.eq(payload[2])
                        case 4:
                            m.d.sync += lane.eq(payload[3])
                        case 5:
                            m.d.sync += lane.eq(checksum[0])
                        case 6:
                            m.d.sync += lane.eq(checksum[1])
                        case 7:
                            m.d.sync += lane.eq(Symbol.END)
                            m.d.sync += self.o.p.last.eq(1)
                            m.d.comb += self.i.ready.eq(1)

        # Keep previous state if output not accepted.
        with m.If(self.o.valid & ~self.o.ready):
            m.d.sync += self.o.p.eq(self.o.p)
            m.d.sync += self.o.valid.eq(1)
            m.d.sync += idx.eq(idx)
            m.d.comb += self.i.ready.eq(0)

        return m

class Depacketizer(wiring.Component):
    '''DLLP Depacketizer.

    Converts a stream of symbols into a stream of raw DLLP payloads.

    SDP symbol must be aligned to the first lane in the input stream.

    Args:
        phy_width: Input stream width in symbols.

    Attributes:
        i (stream): Input stream.
        o (stream): Output stream.
    '''

    def __init__(self, *, phy_width):
        super().__init__({
            'i': wiring.In(stream.Signature(data.ArrayLayout(Symbol, phy_width), always_ready = True)),
            'o': wiring.Out(stream.Signature(data.ArrayLayout(8, 6), always_ready = True)),
        })

        self._phy_width = phy_width

        if phy_width & (phy_width - 1) != 0:
            raise ValueError('phy_width must be a power of 2')
        if phy_width > 8:
            raise ValueError('phy_width must be less than or equal to 8')

    def elaborate(self, platform):
        m = Module()

        buf = Signal(data.ArrayLayout(Symbol, 8))

        for i in range(6):
            m.d.comb += self.o.p[i].eq(buf[i + 1].d)

        with m.If(self.i.valid):
            m.d.sync += buf.eq(Cat(buf[self._phy_width:], self.i.p))

            m.d.comb += self.o.valid.eq(
                (buf[0] == Symbol.SDP) &
                (Cat(symbol.k for symbol in buf[1:7]) == 0) & 
                (buf[7] == Symbol.END))

        return m

class CrcChecker(wiring.Component):
    '''CRC Checker.

    CRC error causes the packet to be dropped.

    Attributes:
        i (stream): Input stream.
        o (stream): Output stream.
    '''

    def __init__(self):
        super().__init__({
            'i': wiring.In(stream.Signature(data.ArrayLayout(8, 6), always_ready = True)),
            'o': wiring.Out(stream.Signature(DLLPacket, always_ready = True)),
        })

    def elaborate(self, platform):
        m = Module()

        m.submodules.crc_checker = crc_checker = crc.Algorithm(
            crc_width = 16,
            polynomial = 0x100b,
            initial_crc = 0xffff,
            reflect_input = True,
            reflect_output = True,
            xor_output = 0xffff
        )(48).create()

        valid = Signal()
        m.d.sync += [
            valid.eq(self.i.valid),
            self.o.p.eq(self.i.p[3::-1]),
        ]

        m.d.comb += [
            crc_checker.data.eq(self.i.p),
            crc_checker.valid.eq(1),
            crc_checker.start.eq(1),
            self.o.valid.eq(valid & crc_checker.match_detected),
        ]

        return m

class DLLPacketReceiver(wiring.Component):
    def __init__(self, phy_width):
        super().__init__({
            'i': wiring.In(stream.Signature(data.ArrayLayout(Symbol, phy_width), always_ready = True)),
            'o': wiring.Out(stream.Signature(DLLPacket, always_ready = True)),
        })

        self._phy_width = phy_width
    
    def elaborate(self, platform):
        m = Module()

        m.submodules.lane_aligner = lane_aligner = LaneAligner(shape = Symbol, width = self._phy_width, token = Symbol.SDP)
        m.submodules.depacketizer = depacketizer = Depacketizer(phy_width = self._phy_width)
        m.submodules.crc_checker = crc_checker = CrcChecker()

        connect_pipeline(m,
            wiring.flipped(self.i),
            lane_aligner,
            depacketizer,
            crc_checker,
            wiring.flipped(self.o),
        )

        return m
