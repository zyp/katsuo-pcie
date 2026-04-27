from amaranth import *
from amaranth.lib import wiring, data, stream

from katsuo.stream import Packet, PacketQueue, PriorityArbiter, connect_pipeline, SyncFIFOBuffered

from ..code import Symbol

from .tlp import TLPacketSender, TLPacketReceiver
from .dllp import DLLPacketSender, DLLPacketReceiver

from ..mac import LinkSignature

class DataLinkLayer(wiring.Component):
    def __init__(self, *, phy_width, tl_width = 4):
        super().__init__({
            'link': wiring.In(LinkSignature(phy_width)),

            'o_tlp': wiring.Out(stream.Signature(Packet(data.ArrayLayout(8, tl_width)))),
            'i_tlp': wiring.In(stream.Signature(Packet(data.ArrayLayout(8, tl_width)))),
        })

        self._phy_width = phy_width
        self._tl_width = tl_width

        assert tl_width == 4
    
    def elaborate(self, platform):
        m = Module()

        m.submodules.tx_arbiter = tx_arbiter = PriorityArbiter(Packet(data.ArrayLayout(Symbol, self._phy_width)))
        connect_pipeline(m,
            tx_arbiter.o,
            wiring.flipped(self.link.tx),
        )

        # TLP RX pipeline
        m.submodules.tlp_receiver = tlp_receiver = TLPacketReceiver(phy_width = self._phy_width, tl_width = self._tl_width)
        m.submodules.rx_queue = rx_queue = PacketQueue(32, depth = 512, i_semantics = Packet.Semantics.FIRST_END, o_semantics = Packet.Semantics.LAST)

        connect_pipeline(m,
            wiring.flipped(self.link.rx),
            tlp_receiver,
            rx_queue,
            wiring.flipped(self.o_tlp),
        )

        # TLP TX pipeline
        m.submodules.tlp_sender = tlp_sender = TLPacketSender(phy_width = self._phy_width, tl_width = self._tl_width)
        m.submodules.tx_queue = tx_queue = PacketQueue(32, depth = 512, i_semantics = Packet.Semantics.LAST, o_semantics = Packet.Semantics.LAST)
        # Buffers around the tx_queue improves timing.
        #m.submodules.tx_buffer = tx_buffer = SyncFIFOBuffered(shape = Packet(32), depth = 1)
        #m.submodules.tx_buffer2 = tx_buffer2 = SyncFIFOBuffered(shape = Packet(32), depth = 1)
        # doesn't work, why?

        connect_pipeline(m,
            wiring.flipped(self.i_tlp),
            #tx_buffer,
            tx_queue,
            #tx_buffer2,
            tlp_sender,
            tx_arbiter.get_input(),
        )

        # DLLP RX pipeline
        m.submodules.dllp_receiver = dllp_receiver = DLLPacketReceiver(self._phy_width)

        connect_pipeline(m,
            wiring.flipped(self.link.rx),
            dllp_receiver,
        )

        # DLLP TX pipeline
        m.submodules.dllp_sender = dllp_sender = DLLPacketSender(self._phy_width)

        connect_pipeline(m,
            dllp_sender,
            tx_arbiter.get_input(),
        )

        # Dumb DLL state machine
        got_tlp = Signal()
        with m.If(self.link.rx.valid & (self.link.rx.p[0] == Symbol.STP) | (self.link.rx.p[1] == Symbol.STP)):
            m.d.sync += got_tlp.eq(1)

        idx = Signal(range(6))
        ack_seq = Signal.like(tlp_receiver.ack_seq)

        with m.If(dllp_sender.i.ready):
            m.d.sync += ack_seq.eq(tlp_receiver.ack_seq)

        with m.Switch(idx):
            with m.Case(0):
                with m.If(self.link.link_up):
                    m.d.sync += idx.eq(1)
                with m.If(got_tlp):
                    m.d.sync += idx.eq(4)
                    m.d.sync += got_tlp.eq(0)
            with m.Case(1):
                m.d.comb += Value.cast(dllp_sender.i.payload).eq(0xc0)
                m.d.comb += dllp_sender.i.valid.eq(1)
                with m.If(dllp_sender.i.ready):
                    m.d.sync += idx.eq(2)
            with m.Case(2):
                m.d.comb += Value.cast(dllp_sender.i.payload).eq(0xd0)
                m.d.comb += dllp_sender.i.valid.eq(1)
                with m.If(dllp_sender.i.ready):
                    m.d.sync += idx.eq(3)
            with m.Case(3):
                m.d.comb += Value.cast(dllp_sender.i.payload).eq(0xe0)
                m.d.comb += dllp_sender.i.valid.eq(1)
                with m.If(dllp_sender.i.ready):
                    m.d.sync += idx.eq(0)
            with m.Case(4):
                m.d.comb += dllp_sender.i.payload.data.eq(0x00 | (ack_seq << 16)) # ACK
                m.d.comb += dllp_sender.i.valid.eq(1)

        with m.If(~self.link.link_up):
            m.d.sync += idx.eq(0)

        return m
