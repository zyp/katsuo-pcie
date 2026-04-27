from amaranth import *
from amaranth.lib import wiring, io

from .. import pipe
from ..code import Symbol

# This is based on code from Yumewatari, reused under the terms of the 0BSD license.

class ExtRef(Elaboratable):
    def __init__(self, port: io.DifferentialPort, *, freq, cd = 'refclk', loc = None):
        self._port = port
        self._freq = freq
        self._cd = cd
        self._loc = loc
    
    def elaborate(self, platform):
        m = Module()

        refclk = Signal(attrs = {'keep': 'true'})
        m.submodules.extref = Instance('EXTREFB',
            i_REFCLKP = self._port.p,
            i_REFCLKN = self._port.n,
            o_REFCLKO = refclk,
            p_REFCK_PWDNB = '0b1',
            p_REFCK_RTERM = '0b1',
            p_REFCK_DCBIAS_EN = '0b0',
        )
        if self._loc is not None:
            m.submodules.extref.attrs['LOC'] = f'EXTREF{self._loc}'

        m.d.comb += ClockSignal(self._cd).eq(refclk)
        if self._freq is not None and platform is not None:
            platform.add_clock_constraint(refclk, self._freq)

        return m

class DivClkOut(Elaboratable):
    def __init__(self, domain, output, *, divide_by = 1000):
        self._domain = domain
        self._output = output
        self._half_period = int(divide_by // 2)

    def elaborate(self, platform):
        m = Module()

        cnt = Signal(range(self._half_period))

        m.d[self._domain] += cnt.eq(cnt - 1)

        with m.If(cnt == 0):
            m.d[self._domain] += cnt.eq(self._half_period - 1)
            m.d[self._domain] += self._output.eq(~self._output)
        
        return m

class DCUInstance(Elaboratable):
    def __init__(self, *, loc, ch, **kwargs):
        self._kwargs = {k.replace('_CHx_', f'_CH{ch}_'): v for k, v in kwargs.items()}
        self._loc = loc

    def elaborate(self, platform):
        dcu = Instance('DCUA', **self._kwargs)
        dcu.attrs['LOC'] = f'DCU{self._loc}'
        return dcu

class ECP5SerDes(wiring.Component):
    #def __init__(self, resource_name = 'sma', *, loc = 0, ch = 1):
    def __init__(self, resource_name = 'pcie_x1', *, loc = 0, ch = 0, pins = None):
        super().__init__({
            'pipe': wiring.In(pipe.Signature(2)),
        })

        self._resource_name = resource_name
        self._loc = loc
        self._ch = ch
        self._pins = pins

        self.cd_refclk = ClockDomain()
        self.cd_tx = ClockDomain()
        self.cd_rx = ClockDomain()

    def elaborate(self, platform):
        m = Module()

        tx_width = 2
        rx_width = 2

        if platform is not None:
            pins = platform.request(self._resource_name, dir = '-')
            resource = platform.lookup(self._resource_name)
            refclk_freq = next(s for s in resource.ios if s.name == 'clk').clock.frequency
        else:
            pins = self._pins
            refclk_freq = 100e6
        vco_multiplier = round(2.5e9 / refclk_freq)

        m.domains.refclk = self.cd_refclk
        m.domains.tx     = self.cd_tx
        m.domains.rx     = self.cd_rx

        m.domains.tx_f   = ClockDomain()
        m.domains.tx_h   = ClockDomain()

        if platform is not None:
            m.submodules += DivClkOut('tx', platform.request('clkout', 0).o)
            #m.submodules += DivClkOut('rx', platform.request('clkout', 1).o)
            m.submodules += DivClkOut('tx_f', platform.request('clkout', 1).o)
            #m.d.comb += platform.request('clkout', 1).o.eq(ClockSignal('tx'))

            m.submodules += DivClkOut('tx', platform.request('led', 0).o, divide_by = 250e6 / tx_width)
            m.submodules += DivClkOut('rx', platform.request('led', 1).o, divide_by = 250e6 / rx_width)
            m.submodules += DivClkOut('refclk', platform.request('led', 2).o, divide_by = refclk_freq)

        m.submodules.extref = ExtRef(pins.clk, freq = refclk_freq)

        tx_clk = Signal(attrs = {'keep': 'true'})
        m.d.comb += ClockSignal('tx').eq(tx_clk)
        if platform is not None:
            platform.add_clock_constraint(tx_clk, 250e6 / tx_width)
        rx_clk = Signal(attrs = {'keep': 'true'})
        m.d.comb += ClockSignal('rx').eq(rx_clk)
        if platform is not None:
            platform.add_clock_constraint(rx_clk, 250e6 / rx_width)

        # Data buses
        rx_bus = Signal(24)
        tx_bus = Signal(24)

        m.d.comb += [
            self.pipe.rx_data[0].eq(rx_bus[0:9]),
            self.pipe.rx_data[1].eq(rx_bus[12:21]),
            self.pipe.rx_status.eq(Mux(rx_bus[9:12] > rx_bus[21:24], rx_bus[9:12], rx_bus[21:24])),

            tx_bus[0:9].eq(self.pipe.tx_data[0]),
            tx_bus[12:21].eq(self.pipe.tx_data[1]),
            # TODO: Control signals.
        ]

        # RX reset logic
        rx_startup_time = 10_000_000
        rx_startup_cnt = Signal(range(rx_startup_time + 1), init = rx_startup_time)
        rx_rst = Signal(init = 1)

        with m.If(rx_startup_cnt > 0):
            m.d.tx += rx_startup_cnt.eq(rx_startup_cnt - 1)
        with m.Else():
            m.d.tx += rx_rst.eq(0)

        # RX PCS reset logic
        rx_pcs_max_errors = 10
        rx_pcs_error_cnt = Signal(range(rx_pcs_max_errors + 1), init = 0)
        #rx_pcs_startup_time = 10_000_000
        rx_pcs_startup_time = 100_000
        rx_pcs_startup_cnt = Signal(range(rx_pcs_startup_time + 1), init = rx_pcs_startup_time)
        rx_pcs_rst = Signal(init = 1)

        with m.If(rx_pcs_startup_cnt > 0):
            m.d.rx += rx_pcs_startup_cnt.eq(rx_pcs_startup_cnt - 1)
        with m.Else():
            m.d.rx += rx_pcs_rst.eq(0)

        with m.If(rx_pcs_rst == 0):
            with m.If(rx_bus[:9] == 0x1EE):
                m.d.rx += rx_pcs_error_cnt.eq(rx_pcs_error_cnt + 1)

        with m.If(rx_pcs_error_cnt >= rx_pcs_max_errors):
            m.d.rx += rx_pcs_rst.eq(1)
            m.d.rx += rx_pcs_startup_cnt.eq(rx_pcs_startup_time)
            m.d.rx += rx_pcs_error_cnt.eq(0)

        ## TX pattern generator (for testing)
        #cnt = Signal(4)
        #m.d.tx += cnt.eq(cnt + 1)
        #m.d.comb += tx_bus.eq(cnt)
        #with m.If(cnt == 0):
        #    m.d.comb += tx_bus.eq(Symbol.COM)

        #m.d.comb += tx_bus.eq((1 << 11) | (1 << 23)) # Force electric idle

        rx_los   = Signal()
        rx_lol   = Signal()
#        rx_lsm   = Signal()
#        rx_inv   = Signal()
#        rx_det   = Signal()
#        tx_lol   = Signal()

        m.d.comb += ResetSignal('rx').eq(rx_lol)

        if platform is not None:
            m.d.comb += platform.request("led", 5).o.eq(ResetSignal('tx'))
            m.d.comb += platform.request("led", 6).o.eq(rx_lol)
            m.d.comb += platform.request("led", 7).o.eq(rx_los)


#        rx_clk_i = Signal()
#        #rx_clk_o = Signal()
#        rx_clk_o = ClockSignal('pcie_rx')
#        tx_clk_i = Signal()
#        tx_clk_o = Signal()
#
#        pcie_det_en = Signal()
#        pcie_ct     = Signal()
#        pcie_done   = Signal()
#        pcie_con    = Signal()
#
#
#
#        m.d.comb += tx_clk_i.eq(tx_clk_o)
#        m.d.comb += rx_clk_i.eq(rx_clk_o)
#
#        m.d.comb += platform.request("clkout", 0).o.eq(tx_clk_i)
#
#        #m.d.comb += [
#        #    platform.request("led", 0).o.eq(tx_lol),
#        #    platform.request("led", 1).o.eq(rx_lol),
#        #    platform.request("led", 2).o.eq(rx_los),
#        #    platform.request("led", 3).o.eq(rx_lsm),
#        #    platform.request("led", 4).o.eq(rx_inv),
#        #    platform.request("led", 5).o.eq(rx_det),
#        #]
#
        #dcu = Instance('DCUA',
        dcu = DCUInstance(loc = self._loc, ch = self._ch,
#            #============================ DCU
#            # DCU — power management
            p_D_MACROPDB            = "0b1",
            p_D_IB_PWDNB            = "0b1",    # undocumented (required for RX)
            p_D_TXPLL_PWDNB         = "0b1",
            i_D_FFC_MACROPDB        = 1,

            # DCU — reset
            i_D_FFC_MACRO_RST       = 0,
            i_D_FFC_DUAL_RST        = 0,
            i_D_FFC_TRST            = 0,

            # DCU — clocking
            i_D_REFCLKI             = ClockSignal('refclk'),
            o_D_FFS_PLOL            = ResetSignal('tx'), # PLL loss of lock
            p_D_REFCK_MODE          = {
                8: '0b011',
                10: '0b001',
                16: '0b010',
                20: '0b000',
                25: '0b100',
            }[vco_multiplier],
            p_D_TX_MAX_RATE         = "2.5",    # 2.5 Gbps
            p_D_TX_VCO_CK_DIV       = {
                1: "0b000",
                2: "0b010",
                4: "0b100",
                8: "0b101",
                16: "0b110",
                32: "0b111",
            }[1],
            p_D_BITCLK_LOCAL_EN     = "0b1",    # undocumented (PCIe sample code used)


            # DCU ­— unknown
            p_D_CMUSETBIASI         = "0b00",   # begin undocumented (PCIe sample code used)
            p_D_CMUSETI4CPP         = "0d4",
            p_D_CMUSETI4CPZ         = "0d3",
            p_D_CMUSETI4VCO         = "0b00",
            p_D_CMUSETICP4P         = "0b01",
            p_D_CMUSETICP4Z         = "0b101",
            p_D_CMUSETINITVCT       = "0b00",
            p_D_CMUSETISCL4VCO      = "0b000",
            p_D_CMUSETP1GM          = "0b000",
            p_D_CMUSETP2AGM         = "0b000",
            p_D_CMUSETZGM           = "0b100",
            p_D_SETIRPOLY_AUX       = "0b10",
            p_D_SETICONST_AUX       = "0b01",
            p_D_SETIRPOLY_CH        = "0b10",
            p_D_SETICONST_CH        = "0b10",
            p_D_SETPLLRC            = "0d1",
            p_D_RG_EN               = "0b0",
            p_D_RG_SET              = "0b00",   # end undocumented

            # DCU — FIFOs
            p_D_LOW_MARK            = "0d4",
            p_D_HIGH_MARK           = "0d12",

            #============================ CHx common
            # CHx — protocol
            p_CHx_PROTOCOL          = "PCIE",
            p_CHx_PCIE_MODE         = "0b1",

#            p_CHx_PROTOCOL          = "10BSER",
#            p_CHx_UC_MODE           = "0b1",
            p_CHx_ENC_BYPASS        = "0b0",    # Bypass 8b10b encoder
            p_CHx_DEC_BYPASS        = "0b0",    # Bypass 8b10b decoder

            #============================ CHx receive
            # CHx RX ­— power management
            p_CHx_RPWDNB            = "0b1",
            i_CHx_FFC_RXPWDNB       = 1,

            # CHx RX ­— reset
            i_CHx_FFC_RRST          = rx_rst,
            i_CHx_FFC_LANE_RX_RST   = rx_pcs_rst,
#            i_CHx_FFC_RRST          = rc.rx_serdes_rst,
#            i_CHx_FFC_LANE_RX_RST   = rc.rx_pcs_rst,

            # CHx RX ­— input
            i_CHx_HDINP             = pins.rx.p,
            i_CHx_HDINN             = pins.rx.n,
            i_CHx_FFC_SB_INV_RX     = 0,

            p_CHx_RTERM_RX          = "0d22",   # 50 Ohm (wizard value used, does not match D/S)
            p_CHx_RXIN_CM           = "0b11",   # CMFB (wizard value used)
            p_CHx_RXTERM_CM         = "0b11",   # RX Input (wizard value used)

            # CHx RX ­— clocking
            i_CHx_RX_REFCLK         = ClockSignal('refclk'),
            o_CHx_FF_RX_PCLK        = rx_clk,
            i_CHx_FF_RXI_CLK        = ClockSignal('tx'),
            i_CHx_FF_EBRD_CLK       = ClockSignal('tx_h'),

            p_CHx_CDR_MAX_RATE      = "2.5",    # 2.5 Gbps
            p_CHx_RX_DCO_CK_DIV     = {
                1: "0b000",
                2: "0b010",
                4: "0b100",
                8: "0b101",
                16: "0b110",
                32: "0b111",
            }[1],
            p_CHx_RX_GEAR_MODE      = {1: "0b0", 2: "0b1"}[rx_width],
            p_CHx_FF_RX_H_CLK_EN    = {1: "0b0", 2: "0b1"}[rx_width],
            p_CHx_FF_RX_F_CLK_DIS   = {1: "0b0", 2: "0b1"}[rx_width],
            p_CHx_SEL_SD_RX_CLK     = "0b1",    # FIFO driven by recovered clock

            p_CHx_AUTO_FACQ_EN      = "0b1",    # undocumented (wizard value used)
            p_CHx_AUTO_CALIB_EN     = "0b1",    # undocumented (wizard value used)
            p_CHx_PDEN_SEL          = "0b1",    # phase detector disabled on LOS

            p_CHx_DCOATDCFG         = "0b00",   # begin undocumented (PCIe sample code used)
            p_CHx_DCOATDDLY         = "0b00",
            p_CHx_DCOBYPSATD        = "0b1",
            p_CHx_DCOCALDIV         = "0b010",
            p_CHx_DCOCTLGI          = "0b011",
            p_CHx_DCODISBDAVOID     = "0b1",
            p_CHx_DCOFLTDAC         = "0b00",
            p_CHx_DCOFTNRG          = "0b010",
            p_CHx_DCOIOSTUNE        = "0b010",
            p_CHx_DCOITUNE          = "0b00",
            p_CHx_DCOITUNE4LSB      = "0b010",
            p_CHx_DCOIUPDNX2        = "0b1",
            p_CHx_DCONUOFLSB        = "0b101",
            p_CHx_DCOSCALEI         = "0b01",
            p_CHx_DCOSTARTVAL       = "0b010",
            p_CHx_DCOSTEP           = "0b11",   # end undocumented

            # CHx RX — loss of signal
            o_CHx_FFS_RLOS          = rx_los,
            p_CHx_RLOS_SEL          = "0b1",
            p_CHx_RX_LOS_EN         = "0b1",
            p_CHx_RX_LOS_LVL        = "0b100",  # Lattice "TBD" (wizard value used)
            p_CHx_RX_LOS_CEQ        = "0b11",   # Lattice "TBD" (wizard value used)

#            # CHx RX — loss of lock
            o_CHx_FFS_RLOL          = rx_lol,
            #o_CHx_FFS_RLOL          = platform.request("led", 6).o,
            #o_CHx_FFS_RLOL          = ResetSignal('rx'),

            # CHx RX — link state machine
#            i_CHx_FFC_SIGNAL_DETECT = rx_det,
#            o_CHx_FFS_LS_SYNC_STATUS= rx_lsm,
            p_CHx_ENABLE_CG_ALIGN   = "0b1",
            p_CHx_UDF_COMMA_MASK    = "0x3ff",  # compare all 10 bits
            p_CHx_UDF_COMMA_A       = "0x283",  # K28.5 inverted
            p_CHx_UDF_COMMA_B       = "0x17C",  # K28.5

            p_CHx_CTC_BYPASS        = "0b0",    # bypass CTC FIFO
            p_CHx_MIN_IPG_CNT       = "0b11",   # minimum interpacket gap of 4
            p_CHx_MATCH_4_ENABLE    = "0b0",    # 4 character skip matching
            p_CHx_CC_MATCH_1        = "0x1BC",  # K28.5
            p_CHx_CC_MATCH_2        = "0x11C",  # K28.0
            p_CHx_CC_MATCH_3        = "0x11C",  # K28.0
            p_CHx_CC_MATCH_4        = "0x11C",  # K28.0

            # CHx RX — data
            **{"o_CHx_FF_RX_D_%d" % n: rx_bus[n] for n in range(len(rx_bus))},

            #============================ CHx transmit
            # CHx TX — power management
            p_CHx_TPWDNB            = "0b1",
            i_CHx_FFC_TXPWDNB       = 1,

            # CHx TX ­— reset
            i_CHx_FFC_LANE_TX_RST   = 0,

            # CHx TX ­— output
            o_CHx_HDOUTP            = pins.tx.p,
            o_CHx_HDOUTN            = pins.tx.n,

            p_CHx_TXAMPLITUDE       = "0d1000", # 1000 mV
            p_CHx_RTERM_TX          = "0d19",   # 50 Ohm

            p_CHx_TDRV_SLICE0_CUR   = "0b011",  # 400 uA
            p_CHx_TDRV_SLICE0_SEL   = "0b01",   # main data
            p_CHx_TDRV_SLICE1_CUR   = "0b000",  # 100 uA
            p_CHx_TDRV_SLICE1_SEL   = "0b00",   # power down
            p_CHx_TDRV_SLICE2_CUR   = "0b11",   # 3200 uA
            p_CHx_TDRV_SLICE2_SEL   = "0b01",   # main data
            p_CHx_TDRV_SLICE3_CUR   = "0b11",   # 3200 uA
            p_CHx_TDRV_SLICE3_SEL   = "0b01",   # main data
            p_CHx_TDRV_SLICE4_CUR   = "0b11",   # 3200 uA
            p_CHx_TDRV_SLICE4_SEL   = "0b01",   # main data
            p_CHx_TDRV_SLICE5_CUR   = "0b00",   # 800 uA
            p_CHx_TDRV_SLICE5_SEL   = "0b00",   # power down

            # CHx TX ­— clocking
            o_CHx_FF_TX_PCLK        = tx_clk,
            i_CHx_FF_TXI_CLK        = ClockSignal('tx'),

            o_CHx_FF_TX_F_CLK = ClockSignal('tx_f'),
            o_CHx_FF_TX_H_CLK = ClockSignal('tx_h'),

            p_CHx_TX_GEAR_MODE      = {1: "0b0", 2: "0b1"}[tx_width],
            #p_CHx_FF_TX_H_CLK_EN    = {1: "0b0", 2: "0b1"}[tx_width],
            #p_CHx_FF_TX_F_CLK_DIS   = {1: "0b0", 2: "0b1"}[tx_width],
            p_CHx_FF_TX_H_CLK_EN    = "0b1",
            p_CHx_FF_TX_F_CLK_DIS   = "0b0",

            # CHx TX — data
            **{"i_CHx_FF_TX_D_%d" % n: tx_bus[n] for n in range(len(tx_bus))},

            # CHx DET
            #i_CHx_FFC_PCIE_DET_EN   = pcie_det_en,
            #i_CHx_FFC_PCIE_CT       = pcie_ct,
            #o_CHx_FFS_PCIE_DONE     = pcie_done,
            #o_CHx_FFS_PCIE_CON      = pcie_con,
        )
        #dcu.attrs['LOC'] = f'DCU{self._loc}'
        m.submodules += dcu

        return m

