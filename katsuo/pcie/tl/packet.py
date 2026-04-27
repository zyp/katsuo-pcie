from amaranth import *
from amaranth.lib import enum, data

class Header(data.ArrayLayout):
    def __init__(self, *, width, _view_type = None):
        if width not in [4, 8, 12, 16]:
            raise ValueError('Unsupported header width')
        super().__init__(8, width)
        self._view_type = _view_type

    def __call__(self, value):
        if self._view_type is None:
            return HeaderView(self, value)
        else:
            return self._view_type(self, value)

class HeaderView(data.View):
    def word(self, n):
        if n * 4 >= len(self):
            raise IndexError('Header word index out of range')
        return self[n * 4:(n + 1) * 4]

    @property
    def format(self):
        return Format(self[0][5:])

    @property
    def type(self):
        return Type(self[0])
    
    @property
    def length(self):
        return Cat(self[3], self[2][:2])

class ConfigurationHeader(Header):
    def __init__(self):
        super().__init__(width = 16, _view_type = ConfigurationHeaderView)

class ConfigurationHeaderView(HeaderView):
    @property
    def requester_id(self):
        return ID(Cat(self[5], self[4]))

    @property
    def tag(self):
        return self[6]

    @property
    def first_dw_be(self):
        return self[7][0:4]
    
    @property
    def target_id(self):
        return ID(Cat(self[9], self[8]))

    @property
    def register_number(self):
        return Cat(self[11][2:], self[10][:4])

class MemHeader(Header):
    def __init__(self):
        super().__init__(width = 16, _view_type = MemHeaderView)

class MemHeaderView(HeaderView):
    @property
    def requester_id(self):
        return ID(Cat(self[5], self[4]))

    @property
    def tag(self):
        return self[6]

    @property
    def last_dw_be(self):
        return self[7][4:8]
    
    @property
    def first_dw_be(self):
        return self[7][0:4]
    
    @property
    def address_32(self):
        return Cat(self[11], self[10], self[9], self[8])

    @property
    def address_64(self):
        return Cat(self[15], self[14], self[13], self[12], self[11], self[10], self[9], self[8])

    @property
    def address_auto(self):
        return Mux(self[0][5], self.address_64, self.address_32)

class CompletionHeader(Header):
    def __init__(self):
        super().__init__(width = 16, _view_type = CompletionHeaderView)

class CompletionHeaderView(HeaderView):
    @property
    def completer_id(self):
        return ID(Cat(self[5], self[4]))

    @property
    def requester_id(self):
        return ID(Cat(self[9], self[8]))

    # TODO: status
    # TODO: bcm

    @property
    def byte_count(self):
        return Cat(self[7], self[6][:4])

    @property
    def tag(self):
        return self[10]
    
    @property
    def lower_address(self):
        return self[11]

class Format(enum.Enum, shape = 3):
    H3 = 0
    H4 = 1
    H3D = 2
    H4D = 3

    def with_type(self, type):
        return (self.value << 5) | type

class Type(enum.Enum, shape = 8):
    MRd_32 = Format.H3.with_type(0x00)
    MRd_64 = Format.H4.with_type(0x00)
    MWr_32 = Format.H3D.with_type(0x00)
    MWr_64 = Format.H4D.with_type(0x00)

    CfgRd0 = Format.H3.with_type(0x04)
    CfgWr0 = Format.H3D.with_type(0x04)

    Cpl = Format.H3.with_type(0x0a)
    CplD = Format.H3D.with_type(0x0a)

    Msg_RC = Format.H4.with_type(0x10)
    Msg_Addr = Format.H4.with_type(0x11)
    Msg_ID = Format.H4.with_type(0x12)
    Msg_Broadcast = Format.H4.with_type(0x13)
    Msg_Local = Format.H4.with_type(0x14)
    Msg_Gather = Format.H4.with_type(0x15)

    MsgD_RC = Format.H4D.with_type(0x10)
    MsgD_Addr = Format.H4D.with_type(0x11)
    MsgD_ID = Format.H4D.with_type(0x12)
    MsgD_Broadcast = Format.H4D.with_type(0x13)
    MsgD_Local = Format.H4D.with_type(0x14)
    MsgD_Gather = Format.H4D.with_type(0x15)

class ID(data.Struct):
    function: 3
    device: 5
    bus: 8

from amaranth.lib import wiring, stream
from katsuo.stream import Packet

class TLP(Packet):
    def __init__(self, width):
        super().__init__(data.ArrayLayout(8, width), header_shape = Header(width = 16))

class Depacketizer(wiring.Component):
    def __init__(self, width):
        assert width == 4
        super().__init__({
            'i': wiring.In(stream.Signature(Packet(data.ArrayLayout(8, width)))),
            'o': wiring.Out(stream.Signature(Packet(data.ArrayLayout(8, width), header_shape = Header(width = 16)))),
        })

    def elaborate(self, platform):
        m = Module()

        idx = Signal(range(5))

        m.d.comb += [
            self.o.p.data.eq(self.i.p.data),
            self.o.p.last.eq(self.i.p.last),
        ]

        with m.Switch(idx):
            for i in range(4):
                with m.Case(i):
                    m.d.comb += self.i.ready.eq(1)
                    with m.If(self.i.valid):
                        m.d.sync += self.o.p.header.word(i).eq(self.i.p.data)
                        m.d.sync += idx.eq(i + 1)
                        if i == 2:
                            with m.Switch(self.o.p.header.format):
                                with m.Case(Format.H3D):
                                    m.d.sync += idx.eq(4)
                                with m.Case(Format.H3):
                                    m.d.sync += idx.eq(5)
                        if i == 3:
                            with m.Switch(self.o.p.header.format):
                                with m.Case(Format.H4D):
                                    m.d.sync += idx.eq(4)
                                with m.Case(Format.H4):
                                    m.d.sync += idx.eq(5)

            # Output data after header.
            with m.Case(4):
                m.d.comb += [
                    self.i.ready.eq(self.o.ready),
                    self.o.valid.eq(self.i.valid),
                ]

            # Output header without data.
            with m.Case(5):
                m.d.comb += [
                    self.o.valid.eq(1),
                    self.o.p.last.eq(1),
                ]

        with m.If(self.o.ready & self.o.valid & self.o.p.last):
            m.d.sync += idx.eq(0)

        return m

class Packetizer(wiring.Component):
    def __init__(self, width):
        assert width == 4
        super().__init__({
            'i': wiring.In(stream.Signature(Packet(data.ArrayLayout(8, width), header_shape = Header(width = 16)))),
            'o': wiring.Out(stream.Signature(Packet(data.ArrayLayout(8, width)))),
        })

    def elaborate(self, platform):
        m = Module()

        idx = Signal(range(5))

        with m.Switch(idx):
            for i in range(4):
                with m.Case(i):
                    with m.If(self.i.valid):
                        m.d.comb += self.o.valid.eq(1)
                        m.d.comb += self.o.p.data.eq(self.i.p.header.word(i))
                        with m.If(self.o.ready):
                            m.d.sync += idx.eq(i + 1)
                            if i == 2:
                                with m.If(self.i.p.header.format == Format.H3):
                                    m.d.comb += self.i.ready.eq(1)
                                    m.d.comb += self.o.p.last.eq(self.i.p.last)
                                    m.d.sync += idx.eq(4)
                                with m.If(self.i.p.header.format == Format.H3D):
                                    m.d.sync += idx.eq(4)
                            if i == 3:
                                with m.If(self.i.p.header.format == Format.H4):
                                    m.d.comb += self.i.ready.eq(1)
                                    m.d.comb += self.o.p.last.eq(self.i.p.last)
            with m.Default():
                m.d.comb += [
                    self.i.ready.eq(self.o.ready),
                    self.o.valid.eq(self.i.valid),
                    self.o.p.data.eq(self.i.p.data),
                    self.o.p.last.eq(self.i.p.last),
                ]
            
        # TODO: Check whether this logic is sound when the packet has no data.

        with m.If(self.i.valid & self.i.ready & self.i.p.last):
            m.d.sync += idx.eq(0)

        return m
