from amaranth import *
from amaranth.lib import wiring, stream

from ..code import Symbol

from .training_set import DataRate, TrainingControl, TSType, TrainingSet

class LTSSM(wiring.Component):
    def __init__(self, phy_width):
        super().__init__({
            'i_ts': wiring.In(stream.Signature(TrainingSet, always_ready = True)),
            'o_ts': wiring.Out(stream.Signature(TrainingSet)),

            'rx_idle': wiring.In(1),
            'rx_comma': wiring.In(1),

            'l0': wiring.Out(1),
        })

    def elaborate(self, platform):
        m = Module()

        tx_cnt = Signal(16)
        rx_cnt = Signal(16)
        timeout_cnt = Signal(16)

        link = Signal(Symbol)
        lane = Signal(Symbol)

        m.d.sync += self.o_ts.valid.eq(0)

        def send(ts_type, link, lane):
            m.d.sync += [
                self.o_ts.p.ts_type.eq(ts_type),
                self.o_ts.p.link.eq(link),
                self.o_ts.p.lane.eq(lane),
                self.o_ts.p.n_fts.eq(127),
                self.o_ts.p.data_rate.eq(DataRate.GEN_1),
                self.o_ts.p.training_control.eq(TrainingControl.DISABLE_SCRAMBLING),
                self.o_ts.valid.eq(1),
            ]

        with m.FSM():
            with m.State('Polling.Active'):
                if platform is not None:
                    m.d.comb += platform.request('la', 0).o.eq(1)
                # Send TS1/PAD/PAD
                send(TSType.TS1, Symbol.PAD, Symbol.PAD)

                # Count sent training sets
                with m.If(self.o_ts.valid & self.o_ts.ready & (rx_cnt > 0)):
                    m.d.sync += tx_cnt.eq(tx_cnt + 1)

                # Count received training sets
                with m.If(self.i_ts.valid):
                    m.d.sync += rx_cnt.eq(rx_cnt + 1)

                # TODO: Handle polarity inversion

                # Advance state when enough training sets have been exchanged
                with m.If((tx_cnt >= 1024) & (rx_cnt >= 8)):
                    m.next = 'Polling.Config'
                    m.d.sync += tx_cnt.eq(0)
                    m.d.sync += rx_cnt.eq(0)

            with m.State('Polling.Config'):
                if platform is not None:
                    m.d.comb += platform.request('la', 1).o.eq(1)
                # Send TS2/PAD/PAD
                send(TSType.TS2, Symbol.PAD, Symbol.PAD)

                # Count sent training sets after receiving first TS2
                with m.If(self.o_ts.valid & self.o_ts.ready & (rx_cnt > 0)):
                    m.d.sync += tx_cnt.eq(tx_cnt + 1)

                # Count received TS2
                with m.If(self.i_ts.valid & (self.i_ts.p.ts_type == TSType.TS2)):
                    m.d.sync += rx_cnt.eq(rx_cnt + 1)

                m.d.sync += timeout_cnt.eq(timeout_cnt + 1)
                with m.If(timeout_cnt >= 10000):
                    m.d.sync += rx_cnt.eq(0)
                    m.d.sync += tx_cnt.eq(0)
                    m.d.sync += timeout_cnt.eq(0)
                    m.next = 'Polling.Active'

                # Advance state when enough training sets have been exchanged
                with m.If((tx_cnt >= 16) & (rx_cnt >= 8)):
                    m.next = 'Config.LinkWidth.Start'
                    m.d.sync += tx_cnt.eq(0)
                    m.d.sync += rx_cnt.eq(0)

            with m.State('Config.LinkWidth.Start'):
                if platform is not None:
                    m.d.comb += platform.request('la', 2).o.eq(1)
                # Send TS1/PAD/PAD
                send(TSType.TS1, Symbol.PAD, Symbol.PAD)

                # Count received TS1/link/PAD
                with m.If(self.i_ts.valid & (self.i_ts.p.ts_type == TSType.TS1) & (self.i_ts.p.link != Symbol.PAD)):
                    m.d.sync += rx_cnt.eq(rx_cnt + 1)
                    with m.If(rx_cnt >= 1):
                        m.d.sync += link.eq(self.i_ts.p.link)
                        m.next = 'Config.LinkWidth.Accept'
                        m.d.sync += rx_cnt.eq(0)

            with m.State('Config.LinkWidth.Accept'):
                if platform is not None:
                    m.d.comb += platform.request('la', 3).o.eq(1)
                # Send TS1/link/PAD
                send(TSType.TS1, link, Symbol.PAD)

                # Count received TS1/link/lane
                with m.If(self.i_ts.valid & (self.i_ts.p.ts_type == TSType.TS1) & (self.i_ts.p.lane != Symbol.PAD)):
                    m.d.sync += rx_cnt.eq(rx_cnt + 1)
                    with m.If(rx_cnt >= 1):
                        m.d.sync += lane.eq(self.i_ts.p.lane)
                        m.next = 'Config.LaneNum.Wait'
                        m.d.sync += rx_cnt.eq(0)

            with m.State('Config.LaneNum.Wait'):
                if platform is not None:
                    m.d.comb += platform.request('la', 4).o.eq(1)
                # Send TS1/link/lane
                send(TSType.TS1, link, 0)

                # Count received TS2
                with m.If(self.i_ts.valid & (self.i_ts.p.ts_type == TSType.TS2)):
                    m.d.sync += rx_cnt.eq(rx_cnt + 1)
                    with m.If(rx_cnt >= 1):
                        m.next = 'Config.Complete'
                        m.d.sync += rx_cnt.eq(0)

            with m.State('Config.Complete'):
                if platform is not None:
                    m.d.comb += platform.request('la', 5).o.eq(1)
                # Send TS2/link/lane
                send(TSType.TS2, link, 0)

                # Count received TS2
                with m.If(self.i_ts.valid & (self.i_ts.p.ts_type == TSType.TS2)):
                    m.d.sync += rx_cnt.eq(rx_cnt + 1)
                    with m.If(rx_cnt >= 8):
                        m.next = 'Config.Idle'
                        m.d.sync += rx_cnt.eq(0)

            with m.State('Config.Idle'):
                if platform is not None:
                    m.d.comb += platform.request('la', 6).o.eq(1)

                m.d.sync += rx_cnt.eq(0)
                with m.If(self.rx_idle):
                    m.d.sync += rx_cnt.eq(rx_cnt + 2)

                with m.If((rx_cnt >= 4) | (tx_cnt >= 2)):
                    m.d.sync += tx_cnt.eq(tx_cnt + 2)

                m.d.sync += timeout_cnt.eq(timeout_cnt + 1)
                with m.If(timeout_cnt >= 10000):
                    m.d.sync += rx_cnt.eq(0)
                    m.d.sync += tx_cnt.eq(0)
                    m.d.sync += timeout_cnt.eq(0)
                    m.next = 'Polling.Active'

                with m.If(tx_cnt >= 16):
                    m.d.sync += rx_cnt.eq(0)
                    m.d.sync += tx_cnt.eq(0)
                    m.d.sync += timeout_cnt.eq(0)
                    m.next = 'L0'

            with m.State('L0'):
                if platform is not None:
                    m.d.comb += platform.request('la', 7).o.eq(1)
                m.d.comb += self.l0.eq(1)

                m.d.sync += timeout_cnt.eq(timeout_cnt + 1)
                with m.If(self.rx_comma):
                    m.d.sync += timeout_cnt.eq(0)

                with m.If(timeout_cnt >= 10000):
                    m.d.sync += timeout_cnt.eq(0)
                    m.next = 'Polling.Active'

        return m
