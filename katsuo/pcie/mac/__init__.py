from amaranth import *
from amaranth.lib import wiring, data, stream

from katsuo.stream import Packet, PriorityArbiter, connect_pipeline

from ..code import Symbol

from .. import pipe

class LinkSignature(wiring.Signature):
    def __init__(self, width):
        super().__init__({
            'rx': wiring.Out(stream.Signature(data.ArrayLayout(Symbol, width), always_ready = True)),
            'tx': wiring.In(stream.Signature(Packet(data.ArrayLayout(Symbol, width)))),
            'link_up': wiring.Out(1),
        })

from .ltssm import LTSSM
from .skip_set import SkipSetSender
from .training_set import TrainingSetReceiver, TrainingSetSender

class MediaAccessLayer(wiring.Component):
    def __init__(self, *, phy_width):
        super().__init__({
            'pipe': wiring.Out(pipe.Signature(phy_width)),
            'link': wiring.Out(LinkSignature(phy_width)),

            'ts_strobe': wiring.Out(1),
        })

        self._phy_width = phy_width

    def elaborate(self, platform):
        m = Module()

        m.submodules.ltssm = ltssm = LTSSM(phy_width = self._phy_width)

        m.d.comb += self.link.link_up.eq(ltssm.l0)

        with m.If((Value.cast(self.pipe.rx_data[0]) == 0) & (Value.cast(self.pipe.rx_data[1]) == 0)):
            m.d.comb += ltssm.rx_idle.eq(1)

        with m.If((self.pipe.rx_data[0] == Symbol.COM) | (self.pipe.rx_data[1] == Symbol.COM)):
            m.d.comb += ltssm.rx_comma.eq(1)

        # TS RX
        m.submodules.ts_rx = ts_rx = TrainingSetReceiver(width = self._phy_width)
        m.d.comb += ts_rx.data.eq(self.pipe.rx_data)
        connect_pipeline(m,
            ts_rx,
            ltssm.i_ts,
        )
        m.d.comb += self.ts_strobe.eq(ts_rx.o.valid)

        # DLL RX
        m.d.comb += [
            self.link.rx.p.eq(self.pipe.rx_data),
            self.link.rx.valid.eq(1),
        ]

        # TX arbiter.
        m.submodules.tx_arbiter = tx_arbiter = PriorityArbiter(Packet(data.ArrayLayout(Symbol, self._phy_width)))
        m.d.comb += [
            self.pipe.tx_data.eq(tx_arbiter.o.p.data),
            tx_arbiter.o.ready.eq(1),
        ]

        # SKP TX pipeline.
        m.submodules.skp_tx = skp_tx = SkipSetSender(width = self._phy_width)
        connect_pipeline(m,
            skp_tx,
            tx_arbiter.get_input(),
        )

        # TS TX pipeline.
        m.submodules.ts_tx = ts_tx = TrainingSetSender(width = self._phy_width)
        connect_pipeline(m,
            ltssm.o_ts,
            ts_tx,
            tx_arbiter.get_input(),
        )

        # DLL TX pipeline.
        connect_pipeline(m,
            wiring.flipped(self.link.tx),
            tx_arbiter.get_input(),
        )

        return m
