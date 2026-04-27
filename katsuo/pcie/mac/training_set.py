from amaranth import *
from amaranth.lib import wiring, data, enum, stream

from katsuo.stream import Packet

from ..code import Symbol

from .. import pipe
from . import LinkSignature

class TSType(enum.Enum, shape = 8):
    TS1 = 0x4a
    TS2 = 0x45
    TS1_INVERTED = 0xb5
    TS2_INVERTED = 0xba

class DataRate(enum.Flag, shape = 8):
    GEN_1 = 1 << 1

class TrainingControl(enum.Flag, shape = 8):
    HOT_RESET = 1 << 0
    DISABLE_LINK = 1 << 1
    LOOPBACK = 1 << 2
    DISABLE_SCRAMBLING = 1 << 3
    COMPLIANCE_RECEIVE = 1 << 4

class TrainingSet(data.Struct):
    ts_type: TSType
    link: Symbol
    lane: Symbol
    n_fts: 8
    data_rate: DataRate
    training_control: TrainingControl

class TrainingSetSender(wiring.Component):
    def __init__(self, width):
        assert width in (1, 2, 4, 8, 16)
        super().__init__({
            'i': wiring.In(stream.Signature(TrainingSet)),
            'o': wiring.Out(stream.Signature(Packet(data.ArrayLayout(Symbol, width)))),
        })

        self._width = width

    def elaborate(self, platform):
        m = Module()

        idx = Signal(range(16 // self._width))

        m.d.sync += self.o.valid.eq(0)
        m.d.sync += self.o.p.last.eq(0)
        with m.If(self.i.valid | (idx > 0)):
            m.d.sync += self.o.valid.eq(1)
            m.d.sync += idx.eq(idx + 1)

        for i in range(16 // self._width):
            with m.If(idx == i):
                for j in range(self._width):
                    data = self.o.p.data[j]
                    match i * self._width + j:
                        case 0:
                            m.d.sync += data.eq(Symbol.COM)
                        case 1:
                            m.d.sync += data.eq(self.i.p.link)
                        case 2:
                            m.d.sync += data.eq(self.i.p.lane)
                        case 3:
                            m.d.sync += data.eq(self.i.p.n_fts)
                        case 4:
                            m.d.sync += data.eq(self.i.p.data_rate)
                        case 5:
                            m.d.sync += data.eq(self.i.p.training_control)
                        case _:
                            m.d.sync += data.eq(self.i.p.ts_type)
                    
                    if i * self._width + j == 15:
                            m.d.sync += self.o.p.last.eq(1)
                            m.d.comb += self.i.ready.eq(1)

        # Keep previous state if output not accepted.
        with m.If(self.o.valid & ~self.o.ready):
            m.d.sync += self.o.p.eq(self.o.p)
            m.d.sync += self.o.valid.eq(1)
            m.d.sync += idx.eq(idx)
            m.d.comb += self.i.ready.eq(0)

        return m


class TrainingSetReceiver(wiring.Component):
    def __init__(self, width):
        assert width == 2
        super().__init__({
            'o': wiring.Out(stream.Signature(TrainingSet, always_ready = True)),
            #'ts': wiring.Out(TrainingSet),
            #'valid': wiring.Out(1),
            'data': wiring.In(data.ArrayLayout(Symbol, width)),
        })

        self._width = width

    def elaborate(self, platform):
        m = Module()

        idx = Signal(range(16))

        m.d.sync += self.o.valid.eq(0)

        with m.If(idx > 0):
            m.d.sync += idx.eq(idx + 2)

        with m.Switch(idx):
            with m.Case(1):
                m.d.sync += self.o.p.link.eq(self.data[0])
                m.d.sync += self.o.p.lane.eq(self.data[1])
            with m.Case(2):
                m.d.sync += self.o.p.lane.eq(self.data[0])
                m.d.sync += self.o.p.n_fts.eq(self.data[1])
            with m.Case(3):
                m.d.sync += self.o.p.n_fts.eq(self.data[0])
                m.d.sync += self.o.p.data_rate.eq(self.data[1])
            with m.Case(4):
                m.d.sync += self.o.p.data_rate.eq(self.data[0])
                m.d.sync += self.o.p.training_control.eq(self.data[1])
            with m.Case(5):
                m.d.sync += self.o.p.training_control.eq(self.data[0])
                m.d.sync += self.o.p.ts_type.eq(self.data[1])
            with m.Case(6):
                m.d.sync += self.o.p.ts_type.eq(self.data[0])
                with m.If(self.data[1] != self.data[0]):
                    m.d.sync += idx.eq(0)
            with m.Case(7, 8, 9, 10, 11, 12, 13):
                with m.If((Value.cast(self.data[0]) != Value.cast(self.o.p.ts_type)) | (Value.cast(self.data[1]) != Value.cast(self.o.p.ts_type))):
                    m.d.sync += idx.eq(0)
            with m.Case(14):
                with m.If((Value.cast(self.data[0]) != Value.cast(self.o.p.ts_type)) | (Value.cast(self.data[1]) != Value.cast(self.o.p.ts_type))):
                    m.d.sync += idx.eq(0)
                with m.Else():
                    m.d.sync += self.o.valid.eq(Value.cast(self.o.p.ts_type) != 0) # FIXME: Better filtering
            with m.Case(15):
                with m.If(Value.cast(self.data[0]) == Value.cast(self.o.p.ts_type)):
                    m.d.sync += self.o.valid.eq(Value.cast(self.o.p.ts_type) != 0) # FIXME: Better filtering
                m.d.sync += idx.eq(0)

        with m.If(self.data[0] == Symbol.COM):
            m.d.sync += idx.eq(2)
            m.d.sync += self.o.p.link.eq(self.data[1])

        with m.If(self.data[1] == Symbol.COM):
            m.d.sync += idx.eq(1)

        return m
