from amaranth import *
from amaranth.lib import wiring, data, stream, crc

from katsuo.stream import Packet, connect_pipeline

from .misc import LaneAligner, OverflowChecker
from ..code import Symbol

class TLPacketSender(wiring.Component):
    def __init__(self, *, phy_width, tl_width):
        assert phy_width == 2
        super().__init__({
            'i': wiring.In(stream.Signature(Packet(32))),
            'o': wiring.Out(stream.Signature(Packet(data.ArrayLayout(Symbol, phy_width)))),
        })

        self._width = phy_width

    def elaborate(self, platform):
        m = Module()

        sequence_number = Signal(12)

        m.submodules.crc = crc_module = crc.Algorithm(
            crc_width = 32,
            polynomial = 0x04c11db7,
            initial_crc = 0xffffffff,
            reflect_input = True,
            reflect_output = True,
            xor_output = 0xffffffff,
        )(16).create()

        m.d.comb += [
            #crc_module.data.eq(self.i.p.data),
            crc_module.data.eq(Cat(
                self.o.p.data[0].d,
                self.o.p.data[1].d,
            )),
        ]

        with m.FSM() as fsm:
            with m.State('IDLE'):
                with m.If(self.i.valid):
                    m.next = 'START'

            with m.State('START'):
                m.d.comb += [
                    crc_module.start.eq(1),
                    self.o.valid.eq(1),
                    self.o.p.data[0].eq(0),
                    self.o.p.data[1].eq(Symbol.STP),
                ]
                with m.If(self.o.ready):
                    m.next = 'SEQ'

            with m.State('SEQ'):
                m.d.comb += [
                    self.o.valid.eq(1),
                    self.o.p.data[0].eq(sequence_number[8:]),
                    self.o.p.data[1].eq(sequence_number[:8]),
                ]
                with m.If(self.o.ready):
                    m.d.comb += crc_module.valid.eq(1)
                    m.next = 'DATA_H'

            with m.State('DATA_H'):
                m.d.comb += [
                    self.o.valid.eq(self.i.valid),
                    #self.o.p.data[0].eq(self.i.p.data[24:32]),
                    #self.o.p.data[1].eq(self.i.p.data[16:24]),
                    self.o.p.data[0].eq(self.i.p.data[0:8]),
                    self.o.p.data[1].eq(self.i.p.data[8:16]),
                ]
                with m.If(self.o.valid & self.o.ready):
                    m.d.comb += crc_module.valid.eq(1)
                    m.next = 'DATA_L'

            with m.State('DATA_L'):
                m.d.comb += [
                    self.o.valid.eq(self.i.valid),
                    #self.o.p.data[0].eq(self.i.p.data[8:16]),
                    #self.o.p.data[1].eq(self.i.p.data[0:8]),
                    self.o.p.data[0].eq(self.i.p.data[16:24]),
                    self.o.p.data[1].eq(self.i.p.data[24:32]),
                    self.i.ready.eq(self.o.ready),
                ]
                with m.If(self.o.valid & self.o.ready):
                    m.d.comb += crc_module.valid.eq(1)
                    m.next = 'DATA_H'
                    with m.If(self.i.p.last):
                        m.next = 'CRC_H'

            with m.State('CRC_H'):
                m.d.comb += [
                    self.o.valid.eq(1),
                    self.o.p.data[0].eq(crc_module.crc[0:8]),
                    self.o.p.data[1].eq(crc_module.crc[8:16]),
                ]
                with m.If(self.o.ready):
                    m.next = 'CRC_L'

            with m.State('CRC_L'):
                m.d.comb += [
                    self.o.valid.eq(1),
                    self.o.p.data[0].eq(crc_module.crc[16:24]),
                    self.o.p.data[1].eq(crc_module.crc[24:32]),
                ]
                with m.If(self.o.ready):
                    m.next = 'END'

            with m.State('END'):
                m.d.comb += [
                    self.o.valid.eq(1),
                    self.o.p.data[0].eq(Symbol.END),
                    self.o.p.data[1].eq(0),
                    self.o.p.last.eq(1),
                ]
                m.d.sync += sequence_number.eq(sequence_number + 1)
                with m.If(self.o.ready):
                    m.next = 'IDLE'

        return m

class Depacketizer(wiring.Component):
    '''TLP Depacketizer.

    Converts a stream of symbols into a packetized stream of words.

    STP symbol must be aligned to the first lane in the input stream.
    Output stream will prepend two null bytes to pad the DL header (sequence number) to four bytes which downstream CRC calculation must take into account.
    Any unexpected K-symbols will be treated as errors and cause the current packet to be dropped.

    Args:
        phy_width: Input stream width in symbols.
        tl_width: Output stream width in bytes.

    Attributes:
        i (stream): Input stream.
        o (stream): Output stream.
    '''

    def __init__(self, *, phy_width, tl_width):
        super().__init__({
            'i': wiring.In(stream.Signature(data.ArrayLayout(Symbol, phy_width), always_ready = True)),
            'o': wiring.Out(stream.Signature(Packet(data.ArrayLayout(8, tl_width), semantics = Packet.Semantics.FIRST_LAST), always_ready = True)),
        })

        self._phy_width = phy_width
        self._tl_width = tl_width

        if phy_width > tl_width:
            raise ValueError('phy_width must be less than or equal to tl_width')
        if phy_width & (phy_width - 1) != 0:
            raise ValueError('phy_width must be a power of 2')

        assert tl_width == 4, 'Only tl_width of 4 is supported for now'
        # Relaxing this requires adding unaligned END detection and a way to communicate this in the output stream.

    def elaborate(self, platform):
        m = Module()

        # xxx STP seq seq D00
        # D00 D01 D02 D03 D04
        # D04 D05 D06 D07 END
        buf = Signal(data.ArrayLayout(Symbol, 1 + self._tl_width))

        with m.If(self.i.valid):
            m.d.sync += buf.eq(Cat(buf[self._phy_width:], self.i.p))

        for i in range(self._tl_width):
            m.d.comb += self.o.p.data[i].eq(buf[i].d)

        m.d.comb += self.o.p.last.eq(buf[-1] == Symbol.END)

        beat = Signal(range(self._tl_width // self._phy_width))

        with m.FSM() as fsm:
            with m.State('WAIT_FOR_STP'):
                m.d.comb += [
                    self.o.p.data[0].eq(0),
                    self.o.p.data[1].eq(0),
                    self.o.p.first.eq(1),
                ]

                with m.If(self.i.valid & (buf[1] == Symbol.STP)):
                    m.d.comb += self.o.valid.eq(1)
                    m.d.sync += beat.eq(1)
                    m.next = 'WAIT_FOR_END'

                    # Check for unexpected K-symbols.
                    with m.If(Cat(symbol.k for symbol in buf[2:]).any()):
                        m.d.comb += self.o.valid.eq(0)
                        m.next = 'WAIT_FOR_STP'
            
            with m.State('WAIT_FOR_END'):
                with m.If(self.i.valid):
                    m.d.comb += self.o.valid.eq(beat == 0)
                    m.d.sync += beat.eq(beat + 1)

                    with m.If(self.o.p.last):
                        m.next = 'WAIT_FOR_STP'

                    # Check for unexpected K-symbols.
                    with m.If(Cat(symbol.k for symbol in buf[:-1]).any()):
                        m.d.comb += self.o.valid.eq(0)
                        m.next = 'WAIT_FOR_STP'

        return m

class CrcChecker(wiring.Component):
    '''CRC Checker.

    Expects the packet to have two bytes prepended to pad the sequence number to four bytes.
    CRC error causes the current packet to be dropped.

    Args:
        width: Stream width in bytes.

    Attributes:
        i (stream): Input stream.
        o (stream): Output stream.
    '''

    def __init__(self, *, width):
        super().__init__({
            'i': wiring.In(stream.Signature(Packet(data.ArrayLayout(8, width), semantics = Packet.Semantics.FIRST_LAST), always_ready = True)),
            'o': wiring.Out(stream.Signature(Packet(data.ArrayLayout(8, width), semantics = Packet.Semantics.FIRST_END), always_ready = True)),
        })

        assert width == 4, 'Only width of 4 is supported for now'

    def elaborate(self, platform):
        m = Module()

        m.submodules.crc_checker = crc_checker = crc.Algorithm(
            crc_width = 32,
            polynomial = 0x04c11db7,
            initial_crc = 0x09b93859, # This initial value accounts for the two prepended null bytes.
            reflect_input = True,
            reflect_output = True,
            xor_output = 0xffffffff,
        )(32).create()

        m.d.comb += [
            crc_checker.valid.eq(self.i.valid),
            crc_checker.data.eq(self.i.p.data),
            crc_checker.start.eq(self.i.p.first),
        ]

        last = Signal()
        m.d.sync += [
            self.o.valid.eq(self.i.valid),
            self.o.p.data.eq(self.i.p.data),
            self.o.p.first.eq(self.i.p.first),
            last.eq(self.i.p.last),
        ]

        m.d.comb += self.o.p.end.eq(last & crc_checker.match_detected)

        return m

class SeqNumberChecker(wiring.Component):
    '''Sequence Number Checker.

    Expects the sequence number to be in the first word of the packet.
    Sequence number mismatch causes the current packet to be dropped.
    Sequence numbers of successfully received packets are output on a separate stream.

    Args:
        width: Stream width in bytes.

    Attributes:
        i (stream): Input stream.
        o (stream): Output stream.
        o_seq (stream): Output stream for the sequence number of the received packet.
    '''

    def __init__(self, *, width):
        super().__init__({
            'i': wiring.In(stream.Signature(Packet(data.ArrayLayout(8, width), semantics = Packet.Semantics.FIRST_END))),
            'o': wiring.Out(stream.Signature(Packet(data.ArrayLayout(8, width), semantics = Packet.Semantics.FIRST_END))),
            'o_seq': wiring.Out(stream.Signature(12, always_ready = True)),
        })

        self._width = width

        assert width == 4, 'Only width of 4 is supported for now'

    def elaborate(self, platform):
        m = Module()

        seq = Signal(12)

        seq_expected = Signal(12)
        seq_valid = Signal()
        
        first = Signal()

        m.d.comb += [
            seq.eq(Cat(self.i.p.data[3], self.i.p.data[2])),

            self.i.ready.eq(self.o.ready),
            self.o.valid.eq(self.i.valid & seq_valid),
            self.o.p.data.eq(self.i.p.data),
            self.o.p.first.eq(first),
            self.o.p.end.eq(self.i.p.end),
        ]

        with m.If(self.i.valid & self.i.ready):
            m.d.sync += first.eq(self.i.p.first)

            with m.If(self.i.p.first):
                m.d.sync += self.o_seq.p.eq(seq)

                with m.If(seq == seq_expected):
                    m.d.sync += seq_valid.eq(1)
                    m.d.sync += seq_expected.eq(seq_expected + 1)
                with m.Else():
                    m.d.sync += seq_valid.eq(0)
            
            with m.If(self.i.p.end):
                m.d.comb += self.o_seq.valid.eq(1)

        return m

class TLPacketReceiver(wiring.Component):
    def __init__(self, *, phy_width, tl_width):
        super().__init__({
            'i': wiring.In(stream.Signature(data.ArrayLayout(Symbol, phy_width), always_ready = True)),
            'o': wiring.Out(stream.Signature(Packet(data.ArrayLayout(8, tl_width), semantics = Packet.Semantics.FIRST_END))),

            'ack_seq': wiring.Out(16),
        })

        self._phy_width = phy_width
        self._tl_width = tl_width
    
    def elaborate(self, platform):
        m = Module()

        m.submodules.lane_aligner = lane_aligner = LaneAligner(shape = Symbol, width = self._phy_width, token = Symbol.STP)
        m.submodules.depacketizer = depacketizer = Depacketizer(phy_width = self._phy_width, tl_width = self._tl_width)
        m.submodules.crc_checker = crc_checker = CrcChecker(width = self._tl_width)
        m.submodules.overflow_checker = overflow_checker = OverflowChecker(packet = Packet(data.ArrayLayout(8, self._tl_width), semantics = Packet.Semantics.FIRST_END))
        m.submodules.seq_checker = seq_checker = SeqNumberChecker(width = self._tl_width)

        connect_pipeline(m,
            wiring.flipped(self.i),
            lane_aligner,
            depacketizer,
            crc_checker,
            overflow_checker,
            seq_checker,
            wiring.flipped(self.o),
        )

        # Compat bullshit; old components expect the sequence number in weird endianness.
        with m.If(seq_checker.o_seq.valid):
            m.d.sync += self.ack_seq.eq(Cat(seq_checker.o_seq.p[8:], C(0, 4), seq_checker.o_seq.p[:8]))

        return m
