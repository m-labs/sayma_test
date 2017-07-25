from litex.gen import *
from litex.gen.genlib.resetsync import AsyncResetSynchronizer
from litex.gen.genlib.cdc import MultiReg, PulseSynchronizer, Gearbox
from litex.gen.genlib.misc import BitSlip, WaitTimer

from litex.soc.interconnect.csr import *
from litex.soc.cores.code_8b10b import Encoder, Decoder

# generic

class PhaseDetector(Module, AutoCSR):
    def __init__(self, nbits=8):
        self.mdata = Signal(8)
        self.sdata = Signal(8)

        self.reset = CSR()
        self.status = CSRStatus(2)

        # # #

        # ideal sampling (middle of the eye):
        #  _____       _____       _____
        # |     |_____|     |_____|     |_____|   data
        #    +     +     +     +     +     +      master sampling
        #       -     -     -     -     -     -   slave sampling (90°/bit period)
        # Since taps are fixed length delays, this ideal case is not possible
        # and we will fall in the 2 following possible cases:
        #
        # 1) too late sampling (idelay needs to be decremented):
        #  _____       _____       _____
        # |     |_____|     |_____|     |_____|   data
        #     +     +     +     +     +     +     master sampling
        #        -     -     -     -     -     -  slave sampling (90°/bit period)
        # on mdata transition, mdata != sdata
        #
        #
        # 2) too early sampling (idelay needs to be incremented):
        #  _____       _____       _____
        # |     |_____|     |_____|     |_____|   data
        #   +     +     +     +     +     +       master sampling
        #      -     -     -     -     -     -    slave sampling (90°/bit period)
        # on mdata transition, mdata == sdata

        transition = Signal()
        inc = Signal()
        dec = Signal()

        # find transition
        mdata_d = Signal(8)
        self.sync.serdes_5x += mdata_d.eq(self.mdata)
        self.comb += transition.eq(mdata_d != self.mdata)


        # find what to do
        self.comb += [
            inc.eq(transition & (self.mdata == self.sdata)),
            dec.eq(transition & (self.mdata != self.sdata))
        ]

        # error accumulator
        lateness = Signal(nbits, reset=2**(nbits - 1))
        too_late = Signal()
        too_early = Signal()
        reset_lateness = Signal()
        self.comb += [
            too_late.eq(lateness == (2**nbits - 1)),
            too_early.eq(lateness == 0)
        ]
        self.sync.serdes_5x += [
            If(reset_lateness,
                lateness.eq(2**(nbits - 1))
            ).Elif(~too_late & ~too_early,
                If(inc, lateness.eq(lateness - 1)),
                If(dec, lateness.eq(lateness + 1))
            )
        ]

        # control / status cdc
        self.specials += MultiReg(Cat(too_late, too_early), self.status.status)
        self.submodules.do_reset_lateness = PulseSynchronizer("sys", "serdes_5x")
        self.comb += [
            reset_lateness.eq(self.do_reset_lateness.o),
            self.do_reset_lateness.i.eq(self.reset.re)
        ]


class SerdesPLL(Module):
    def __init__(self, refclk_freq, linerate, vco_div=1):
        assert refclk_freq == 125e6
        assert linerate == 1.25e9

        self.lock = Signal()
        self.refclk = Signal()
        self.serdes_clk = Signal()
        self.serdes_20x_clk = Signal()
        self.serdes_5x_clk = Signal()

        # # #

        #----------------------
        # refclk:        125MHz
        # vco:          1250MHz
        #----------------------
        # serdes:      31.25MHz
        # serdes_20x:    625MHz
        # serdes_5x:  156.25MHz
        #----------------------
        self.linerate = linerate

        pll_locked = Signal()
        pll_fb = Signal()
        pll_serdes_clk = Signal()
        pll_serdes_20x_clk = Signal()
        pll_serdes_5x_clk = Signal()
        self.specials += [
            Instance("PLLE2_BASE",
                p_STARTUP_WAIT="FALSE", o_LOCKED=pll_locked,

                # VCO @ 1.25GHz / vco_div
                p_REF_JITTER1=0.01, p_CLKIN1_PERIOD=8.0,
                p_CLKFBOUT_MULT=10, p_DIVCLK_DIVIDE=vco_div,
                i_CLKIN1=self.refclk, i_CLKFBIN=pll_fb,
                o_CLKFBOUT=pll_fb,

                # 31.25MHz: serdes
                p_CLKOUT0_DIVIDE=40//vco_div, p_CLKOUT0_PHASE=0.0,
                o_CLKOUT0=pll_serdes_clk,

                # 625MHz: serdes_20x
                p_CLKOUT1_DIVIDE=2//vco_div, p_CLKOUT1_PHASE=0.0,
                o_CLKOUT1=pll_serdes_20x_clk,

                # 156.25MHz: serdes_5x
                p_CLKOUT2_DIVIDE=8//vco_div, p_CLKOUT2_PHASE=0.0,
                o_CLKOUT2=pll_serdes_5x_clk
            ),
            Instance("BUFG", i_I=pll_serdes_clk, o_O=self.serdes_clk),
            Instance("BUFG", i_I=pll_serdes_20x_clk, o_O=self.serdes_20x_clk),
            Instance("BUFG", i_I=pll_serdes_5x_clk, o_O=self.serdes_5x_clk)
        ]
        self.specials += MultiReg(pll_locked, self.lock)


class Series7Serdes(Module):
    def __init__(self, pll, pads, mode="master"):
        self.tx_pattern = Signal(40)
        self.tx_pattern_en = Signal()

        self.rx_pattern = Signal(40)

        self.rx_bitslip_value = Signal(6)
        self.rx_delay_rst = Signal()
        self.rx_delay_inc = Signal()
        self.rx_delay_ce = Signal()

        # # #

        self.submodules.encoder = ClockDomainsRenamer("serdes")(
            Encoder(4, True))
        self.decoders = [ClockDomainsRenamer("serdes")(
            Decoder(True)) for _ in range(4)]
        self.submodules += self.decoders

        # clocking
        # master mode:
        # - linerate/10 pll refclk provided by user
        # - linerate/10 slave refclk generated on clk_pads
        # slave mode:
        # - linerate/10 pll refclk provided by clk_pads
        self.clock_domains.cd_serdes = ClockDomain()
        self.clock_domains.cd_serdes_5x = ClockDomain()
        self.clock_domains.cd_serdes_20x = ClockDomain(reset_less=True)
        self.comb += [
            self.cd_serdes.clk.eq(pll.serdes_clk),
            self.cd_serdes_5x.clk.eq(pll.serdes_5x_clk),
            self.cd_serdes_20x.clk.eq(pll.serdes_20x_clk)
        ]
        self.specials += AsyncResetSynchronizer(self.cd_serdes, ~pll.lock)
        self.comb += self.cd_serdes_5x.rst.eq(self.cd_serdes.rst)

        # control/status cdc
        tx_pattern = Signal(40)
        tx_pattern_en = Signal()
        rx_pattern = Signal(40)
        rx_bitslip_value = Signal(6)
        self.specials += [
            MultiReg(self.tx_pattern, tx_pattern, "serdes"),
            MultiReg(self.tx_pattern_en, tx_pattern_en, "serdes"),
            MultiReg(rx_pattern, self.rx_pattern, "sys")
        ]
        self.specials += MultiReg(self.rx_bitslip_value, rx_bitslip_value, "serdes"),

        # tx clock (linerate/10)
        if mode == "master":
            self.submodules.tx_clk_gearbox = Gearbox(40, "serdes", 8, "serdes_5x")
            self.comb += self.tx_clk_gearbox.i.eq((0b1111100000 << 30) |
                                                  (0b1111100000 << 20) |
                                                  (0b1111100000 << 10) |
                                                  (0b1111100000 <<  0))
            clk_o = Signal()
            self.specials += [
                Instance("OSERDESE2",
                    p_DATA_WIDTH=8, p_TRISTATE_WIDTH=1,
                    p_DATA_RATE_OQ="DDR", p_DATA_RATE_TQ="BUF",
                    p_SERDES_MODE="MASTER",

                    o_OQ=clk_o,
                    i_OCE=1,
                    i_RST=ResetSignal("serdes"),
                    i_CLK=ClockSignal("serdes_20x"), i_CLKDIV=ClockSignal("serdes_5x"),
                    i_D1=self.tx_clk_gearbox.o[0], i_D2=self.tx_clk_gearbox.o[1],
                    i_D3=self.tx_clk_gearbox.o[2], i_D4=self.tx_clk_gearbox.o[3],
                    i_D5=self.tx_clk_gearbox.o[4], i_D6=self.tx_clk_gearbox.o[5],
                    i_D7=self.tx_clk_gearbox.o[6], i_D8=self.tx_clk_gearbox.o[7]
                ),
                Instance("OBUFDS",
                    i_I=clk_o,
                    o_O=pads.clk_p,
                    o_OB=pads.clk_n
                )
            ]

        # tx data
        self.submodules.tx_gearbox = Gearbox(40, "serdes", 8, "serdes_5x")
        self.sync.serdes += \
            If(tx_pattern_en,
                self.tx_gearbox.i.eq(tx_pattern)
            ).Else(
                self.tx_gearbox.i.eq(Cat(*[self.encoder.output[i] for i in range(4)]))
            )

        serdes_o = Signal()
        self.specials += [
            Instance("OSERDESE2",
                p_DATA_WIDTH=8, p_TRISTATE_WIDTH=1,
                p_DATA_RATE_OQ="DDR", p_DATA_RATE_TQ="BUF",
                p_SERDES_MODE="MASTER",

                o_OQ=serdes_o,
                i_OCE=1,
                i_RST=ResetSignal("serdes"),
                i_CLK=ClockSignal("serdes_20x"), i_CLKDIV=ClockSignal("serdes_5x"),
                i_D1=self.tx_gearbox.o[0], i_D2=self.tx_gearbox.o[1],
                i_D3=self.tx_gearbox.o[2], i_D4=self.tx_gearbox.o[3],
                i_D5=self.tx_gearbox.o[4], i_D6=self.tx_gearbox.o[5],
                i_D7=self.tx_gearbox.o[6], i_D8=self.tx_gearbox.o[7]
            ),
            Instance("OBUFDS",
                i_I=serdes_o,
                o_O=pads.tx_p,
                o_OB=pads.tx_n
            )
        ]

        # rx clock
        use_bufr = True
        if mode == "slave":
            clk_i = Signal()
            clk_i_bufg = Signal()
            self.specials += [
                Instance("IBUFDS",
                    i_I=pads.clk_p,
                    i_IB=pads.clk_n,
                    o_O=clk_i
                )
            ]
            if use_bufr:
                clk_i_bufr = Signal()
                self.specials += [
                    Instance("BUFR", i_I=clk_i, o_O=clk_i_bufr),
                    Instance("BUFG", i_I=clk_i_bufr, o_O=clk_i_bufg)
                ]
            else:
                self.specials += Instance("BUFG", i_I=clk_i, o_O=clk_i_bufg)
            self.comb += pll.refclk.eq(clk_i_bufg)

        # rx data
        self.submodules.rx_gearbox = Gearbox(8, "serdes_5x", 40, "serdes")
        self.submodules.rx_bitslip = ClockDomainsRenamer("serdes")(BitSlip(40))

        self.submodules.phase_detector = ClockDomainsRenamer("serdes_5x")(PhaseDetector())

        # use 2 serdes for phase detection: 1 master / 1 slave
        serdes_m_i_nodelay = Signal()
        serdes_s_i_nodelay = Signal()
        self.specials += [
            Instance("IBUFDS_DIFF_OUT",
                i_I=pads.rx_p,
                i_IB=pads.rx_n,
                o_O=serdes_m_i_nodelay,
                o_OB=serdes_s_i_nodelay
            )
        ]

        serdes_m_i_delayed = Signal()
        serdes_m_q = Signal(8)
        self.specials += [
            Instance("IDELAYE2",
                p_DELAY_SRC="IDATAIN", p_SIGNAL_PATTERN="DATA",
                p_CINVCTRL_SEL="FALSE", p_HIGH_PERFORMANCE_MODE="TRUE",
                p_REFCLK_FREQUENCY=200.0, p_PIPE_SEL="FALSE",
                p_IDELAY_TYPE="VARIABLE", p_IDELAY_VALUE=0,

                i_C=ClockSignal(),
                i_LD=self.rx_delay_rst,
                i_CE=self.rx_delay_ce,
                i_LDPIPEEN=0, i_INC=self.rx_delay_inc,

                i_IDATAIN=serdes_m_i_nodelay, o_DATAOUT=serdes_m_i_delayed
            ),
            Instance("ISERDESE2",
                p_DATA_WIDTH=8, p_DATA_RATE="DDR",
                p_SERDES_MODE="MASTER", p_INTERFACE_TYPE="NETWORKING",
                p_NUM_CE=1, p_IOBDELAY="IFD",

                i_DDLY=serdes_m_i_delayed,
                i_CE1=1,
                i_RST=ResetSignal("serdes"),
                i_CLK=ClockSignal("serdes_20x"), i_CLKB=~ClockSignal("serdes_20x"),
                i_CLKDIV=ClockSignal("serdes_5x"),
                i_BITSLIP=0,
                o_Q8=serdes_m_q[0], o_Q7=serdes_m_q[1],
                o_Q6=serdes_m_q[2], o_Q5=serdes_m_q[3],
                o_Q4=serdes_m_q[4], o_Q3=serdes_m_q[5],
                o_Q2=serdes_m_q[6], o_Q1=serdes_m_q[7]
            )
        ]
        self.comb += self.phase_detector.mdata.eq(serdes_m_q)

        serdes_s_i_delayed = Signal()
        serdes_s_q = Signal(8)
        serdes_s_idelay_value = int(1/(4*pll.linerate)/78e-12) # 1/4 bit period
        assert serdes_s_idelay_value < 32
        self.specials += [
            Instance("IDELAYE2",
                p_DELAY_SRC="IDATAIN", p_SIGNAL_PATTERN="DATA",
                p_CINVCTRL_SEL="FALSE", p_HIGH_PERFORMANCE_MODE="TRUE",
                p_REFCLK_FREQUENCY=200.0, p_PIPE_SEL="FALSE",
                p_IDELAY_TYPE="VARIABLE", p_IDELAY_VALUE=serdes_s_idelay_value,

                i_C=ClockSignal(),
                i_LD=self.rx_delay_rst,
                i_CE=self.rx_delay_ce,
                i_LDPIPEEN=0, i_INC=self.rx_delay_inc,

                i_IDATAIN=serdes_s_i_nodelay, o_DATAOUT=serdes_s_i_delayed
            ),
            Instance("ISERDESE2",
                p_DATA_WIDTH=8, p_DATA_RATE="DDR",
                p_SERDES_MODE="MASTER", p_INTERFACE_TYPE="NETWORKING",
                p_NUM_CE=1, p_IOBDELAY="IFD",

                i_DDLY=serdes_s_i_delayed,
                i_CE1=1,
                i_RST=ResetSignal("serdes"),
                i_CLK=ClockSignal("serdes_20x"), i_CLKB=~ClockSignal("serdes_20x"),
                i_CLKDIV=ClockSignal("serdes_5x"),
                i_BITSLIP=0,
                o_Q8=serdes_s_q[0], o_Q7=serdes_s_q[1],
                o_Q6=serdes_s_q[2], o_Q5=serdes_s_q[3],
                o_Q4=serdes_s_q[4], o_Q3=serdes_s_q[5],
                o_Q2=serdes_s_q[6], o_Q1=serdes_s_q[7]
            )
        ]
        self.comb += self.phase_detector.sdata.eq(~serdes_s_q)

        self.comb += [
            self.rx_gearbox.i.eq(serdes_m_q),
            self.rx_bitslip.value.eq(rx_bitslip_value),
            self.rx_bitslip.i.eq(self.rx_gearbox.o),
            self.decoders[0].input.eq(self.rx_bitslip.o[0:10]),
            self.decoders[1].input.eq(self.rx_bitslip.o[10:20]),
            self.decoders[2].input.eq(self.rx_bitslip.o[20:30]),
            self.decoders[3].input.eq(self.rx_bitslip.o[30:40]),
            rx_pattern.eq(self.rx_bitslip.o)
        ]


class UltrascaleSerdes(Module):
    def __init__(self, pll, pads, mode="master"):
        self.tx_pattern = Signal(40)
        self.tx_pattern_en = Signal()

        self.rx_pattern = Signal(40)

        self.rx_bitslip_value = Signal(6)
        self.rx_delay_rst = Signal()
        self.rx_delay_inc = Signal()
        self.rx_delay_ce = Signal()
        self.rx_delay_en_vtc = Signal()

        # # #

        self.submodules.encoder = ClockDomainsRenamer("serdes")(
            Encoder(4, True))
        self.decoders = [ClockDomainsRenamer("serdes")(
            Decoder(True)) for _ in range(4)]
        self.submodules += self.decoders

        # clocking
        # master mode:
        # - linerate/10 pll refclk provided externally
        # - linerate/10 clock generated on clk_pads
        # slave mode:
        # - linerate/10 pll refclk provided by clk_pads
        self.clock_domains.cd_serdes = ClockDomain()
        self.clock_domains.cd_serdes_5x = ClockDomain()
        self.clock_domains.cd_serdes_20x = ClockDomain(reset_less=True)
        self.comb += [
            self.cd_serdes.clk.eq(pll.serdes_clk),
            self.cd_serdes_5x.clk.eq(pll.serdes_5x_clk),
            self.cd_serdes_20x.clk.eq(pll.serdes_20x_clk)
        ]
        self.specials += AsyncResetSynchronizer(self.cd_serdes, ~pll.lock)
        self.comb += self.cd_serdes_5x.rst.eq(self.cd_serdes.rst)

        # control/status cdc
        tx_pattern = Signal(40)
        tx_pattern_en = Signal()
        rx_pattern = Signal(40)
        rx_bitslip_value = Signal(6)
        rx_delay_rst = Signal()
        rx_delay_inc = Signal()
        rx_delay_en_vtc = Signal()
        rx_delay_ce = Signal()
        self.specials += [
            MultiReg(self.tx_pattern, tx_pattern, "serdes"),
            MultiReg(self.tx_pattern_en, tx_pattern_en, "serdes"),
            MultiReg(rx_pattern, self.rx_pattern, "sys"),
            MultiReg(self.rx_bitslip_value, rx_bitslip_value, "serdes"),
            MultiReg(self.rx_delay_inc, rx_delay_inc, "serdes_5x"),
            MultiReg(self.rx_delay_en_vtc, rx_delay_en_vtc, "serdes_5x")
        ]
        self.submodules.do_rx_delay_rst = PulseSynchronizer("sys", "serdes_5x")
        self.comb += [
            rx_delay_rst.eq(self.do_rx_delay_rst.o),
            self.do_rx_delay_rst.i.eq(self.rx_delay_rst)
        ]
        self.submodules.do_rx_delay_ce = PulseSynchronizer("sys", "serdes_5x")
        self.comb += [
            rx_delay_ce.eq(self.do_rx_delay_ce.o),
            self.do_rx_delay_ce.i.eq(self.rx_delay_ce)
        ]

        # tx clock (linerate/10)
        if mode == "master":
            self.submodules.tx_clk_gearbox = Gearbox(40, "serdes", 8, "serdes_5x")
            self.comb += self.tx_clk_gearbox.i.eq((0b1111100000 << 30) |
                                                  (0b1111100000 << 20) |
                                                  (0b1111100000 << 10) |
                                                  (0b1111100000 <<  0))
            clk_o = Signal()
            self.specials += [
                Instance("OSERDESE3",
                    p_DATA_WIDTH=8, p_INIT=0,
                    p_IS_CLK_INVERTED=0, p_IS_CLKDIV_INVERTED=0, p_IS_RST_INVERTED=0,

                    o_OQ=clk_o,
                    i_RST=ResetSignal("serdes"),
                    i_CLK=ClockSignal("serdes_20x"), i_CLKDIV=ClockSignal("serdes_5x"),
                    i_D=self.tx_clk_gearbox.o
                ),
                Instance("OBUFDS",
                    i_I=clk_o,
                    o_O=pads.clk_p,
                    o_OB=pads.clk_n
                )
            ]

        # tx data
        self.submodules.tx_gearbox = Gearbox(40, "serdes", 8, "serdes_5x")
        self.sync.serdes += \
            If(tx_pattern_en,
                self.tx_gearbox.i.eq(tx_pattern)
            ).Else(
                self.tx_gearbox.i.eq(Cat(*[self.encoder.output[i] for i in range(4)]))
            )

        serdes_o = Signal()
        self.specials += [
            Instance("OSERDESE3",
                p_DATA_WIDTH=8, p_INIT=0,
                p_IS_CLK_INVERTED=0, p_IS_CLKDIV_INVERTED=0, p_IS_RST_INVERTED=0,

                o_OQ=serdes_o,
                i_RST=ResetSignal("serdes"),
                i_CLK=ClockSignal("serdes_20x"), i_CLKDIV=ClockSignal("serdes_5x"),
                i_D=self.tx_gearbox.o
            ),
            Instance("OBUFDS",
                i_I=serdes_o,
                o_O=pads.tx_p,
                o_OB=pads.tx_n
            )
        ]

        # rx clock
        use_bufr = True
        if mode == "slave":
            clk_i = Signal()
            clk_i_bufg = Signal()
            self.specials += [
                Instance("IBUFDS",
                    i_I=pads.clk_p,
                    i_IB=pads.clk_n,
                    o_O=clk_i
                )
            ]
            if use_bufr:
                clk_i_bufr = Signal()
                self.specials += [
                    Instance("BUFR", i_I=clk_i, o_O=clk_i_bufr),
                    Instance("BUFG", i_I=clk_i_bufr, o_O=clk_i_bufg),
                ]
            else:
                self.specials += Instance("BUFG", i_I=clk_i, o_O=clk_i_bufg),
            self.comb += pll.refclk.eq(clk_i_bufg)

        # rx data
        self.submodules.rx_gearbox = Gearbox(8, "serdes_5x", 40, "serdes")
        self.submodules.rx_bitslip = ClockDomainsRenamer("serdes")(BitSlip(40))

        self.submodules.phase_detector = ClockDomainsRenamer("serdes_5x")(PhaseDetector())

        # use 2 serdes for phase detection: 1 master / 1 slave
        serdes_m_i_nodelay = Signal()
        serdes_s_i_nodelay = Signal()
        self.specials += [
            Instance("IBUFDS_DIFF_OUT",
                i_I=pads.rx_p,
                i_IB=pads.rx_n,
                o_O=serdes_m_i_nodelay,
                o_OB=serdes_s_i_nodelay
            )
        ]

        serdes_m_i_delayed = Signal()
        serdes_m_q = Signal(8)
        self.specials += [
            Instance("IDELAYE3",
                p_CASCADE="NONE", p_UPDATE_MODE="ASYNC", p_REFCLK_FREQUENCY=200.0,
                p_IS_CLK_INVERTED=0, p_IS_RST_INVERTED=0,
                # Note: can't use TIME mode since not reloading DELAY_VALUE on rst...
                p_DELAY_FORMAT="COUNT", p_DELAY_SRC="IDATAIN",
                p_DELAY_TYPE="VARIABLE", p_DELAY_VALUE=50, # 1/4 bit period (ambient temp)

                i_CLK=ClockSignal("serdes_5x"),
                i_RST=rx_delay_rst, i_LOAD=0,
                i_INC=rx_delay_inc, i_EN_VTC=rx_delay_en_vtc,
                i_CE=rx_delay_ce,

                i_IDATAIN=serdes_m_i_nodelay, o_DATAOUT=serdes_m_i_delayed
            ),
            Instance("ISERDESE3",
                p_DATA_WIDTH=8,

                i_D=serdes_m_i_delayed,
                i_RST=ResetSignal("serdes"),
                i_FIFO_RD_CLK=0, i_FIFO_RD_EN=0,
                i_CLK=ClockSignal("serdes_20x"), i_CLK_B=~ClockSignal("serdes_20x"),
                i_CLKDIV=ClockSignal("serdes_5x"),
                o_Q=serdes_m_q
            )
        ]
        self.comb += self.phase_detector.mdata.eq(serdes_m_q)

        serdes_s_i_delayed = Signal()
        serdes_s_q = Signal(8)
        self.specials += [
            Instance("IDELAYE3",
                p_CASCADE="NONE", p_UPDATE_MODE="ASYNC", p_REFCLK_FREQUENCY=200.0,
                p_IS_CLK_INVERTED=0, p_IS_RST_INVERTED=0,
                # Note: can't use TIME mode since not reloading DELAY_VALUE on rst...
                p_DELAY_FORMAT="COUNT", p_DELAY_SRC="IDATAIN",
                p_DELAY_TYPE="VARIABLE", p_DELAY_VALUE=100, # 1/2 bit period (ambient temp)

                i_CLK=ClockSignal("serdes_5x"),
                i_RST=rx_delay_rst, i_LOAD=0,
                i_INC=rx_delay_inc, i_EN_VTC=rx_delay_en_vtc,
                i_CE=rx_delay_ce,

                i_IDATAIN=serdes_s_i_nodelay, o_DATAOUT=serdes_s_i_delayed
            ),
            Instance("ISERDESE3",
                p_DATA_WIDTH=8,

                i_D=serdes_s_i_delayed,
                i_RST=ResetSignal("serdes"),
                i_FIFO_RD_CLK=0, i_FIFO_RD_EN=0,
                i_CLK=ClockSignal("serdes_20x"), i_CLK_B=~ClockSignal("serdes_20x"),
                i_CLKDIV=ClockSignal("serdes_5x"),
                o_Q=serdes_s_q
            )
        ]
        self.comb += self.phase_detector.sdata.eq(~serdes_s_q)

        self.comb += [
            self.rx_gearbox.i.eq(serdes_m_q),
            self.rx_bitslip.value.eq(rx_bitslip_value),
            self.rx_bitslip.i.eq(self.rx_gearbox.o),
            self.decoders[0].input.eq(self.rx_bitslip.o[0:10]),
            self.decoders[1].input.eq(self.rx_bitslip.o[10:20]),
            self.decoders[2].input.eq(self.rx_bitslip.o[20:30]),
            self.decoders[3].input.eq(self.rx_bitslip.o[30:40]),
            rx_pattern.eq(self.rx_bitslip.o)
        ]


class MasterInit(Module):
    def __init__(self, serdes, sync_pattern, taps):
        self.reset = Signal()
        self.error = Signal()
        self.ready = Signal()

        # # #

        self.delay = delay = Signal(max=taps)
        self.delay_min = delay_min = Signal(max=taps)
        self.delay_min_found = delay_min_found = Signal()
        self.delay_max = delay_max = Signal(max=taps)
        self.delay_max_found = delay_max_found = Signal()
        self.bitslip = bitslip = Signal(max=40)

        timer = WaitTimer(1024)
        self.submodules += timer

        self.submodules.fsm = fsm = ResetInserter()(FSM(reset_state="IDLE"))
        self.comb += self.fsm.reset.eq(self.reset)

        fsm.act("IDLE",
            NextValue(delay, 0),
            NextValue(delay_min, 0),
            NextValue(delay_min_found, 0),
            NextValue(delay_max, 0),
            NextValue(delay_max_found, 0),
            serdes.rx_delay_rst.eq(1),
            NextValue(bitslip, 0),
            NextState("RESET_SLAVE"),
            serdes.tx_pattern_en.eq(1)
        )
        fsm.act("RESET_SLAVE",
            timer.wait.eq(1),
            If(timer.done,
                timer.wait.eq(0),
                NextState("SEND_PATTERN")
            ),
            serdes.tx_pattern_en.eq(1)
        )
        fsm.act("SEND_PATTERN",
            If(serdes.rx_pattern != 0,
                NextState("WAIT_STABLE")
            ),
            serdes.tx_pattern_en.eq(1),
            serdes.tx_pattern.eq(sync_pattern)
        )
        fsm.act("WAIT_STABLE",
            timer.wait.eq(1),
            If(timer.done,
                timer.wait.eq(0),
                NextState("CHECK_PATTERN")
            ),
            serdes.tx_pattern_en.eq(1),
            serdes.tx_pattern.eq(sync_pattern)
        )
        fsm.act("CHECK_PATTERN",
            If(~delay_min_found,
                If(serdes.rx_pattern == sync_pattern,
                    timer.wait.eq(1),
                    If(timer.done,
                        NextValue(delay_min, delay),
                        NextValue(delay_min_found, 1)
                    )
                ).Else(
                    NextState("INC_DELAY_BITSLIP")
                ),
            ).Else(
                If(serdes.rx_pattern != sync_pattern,
                    NextValue(delay_max, delay),
                    NextValue(delay_max_found, 1),
                    NextState("RESET_SAMPLING_WINDOW")
                ).Else(
                    NextState("INC_DELAY_BITSLIP")
                )
            ),
            serdes.tx_pattern_en.eq(1),
            serdes.tx_pattern.eq(sync_pattern)
        )
        self.comb += serdes.rx_bitslip_value.eq(bitslip)
        fsm.act("INC_DELAY_BITSLIP",
            NextState("WAIT_STABLE"),
            If(delay == (taps - 1),
                If(delay_min_found,
                    NextState("ERROR")
                ),
                If(bitslip == (40 - 1),
                    NextValue(bitslip, 0)
                ).Else(    
                    NextValue(bitslip, bitslip + 1)
                ),
                NextValue(delay, 0),
                serdes.rx_delay_rst.eq(1)
            ).Else(
                NextValue(delay, delay + 1),
                serdes.rx_delay_inc.eq(1),
                serdes.rx_delay_ce.eq(1)
            ),
            serdes.tx_pattern_en.eq(1),
            serdes.tx_pattern.eq(sync_pattern)
        )
        fsm.act("RESET_SAMPLING_WINDOW",
            NextValue(delay, 0),
            serdes.rx_delay_rst.eq(1),
            NextState("WAIT_SAMPLING_WINDOW"),
            serdes.tx_pattern_en.eq(1),
            serdes.tx_pattern.eq(sync_pattern)
        )
        fsm.act("CONFIGURE_SAMPLING_WINDOW",
            If(delay == (delay_min + (delay_max - delay_min)[1:]),
                NextState("READY")
            ).Else(
                NextValue(delay, delay + 1),
                serdes.rx_delay_inc.eq(1),
                serdes.rx_delay_ce.eq(1),
                NextState("WAIT_SAMPLING_WINDOW")
            ),
            serdes.tx_pattern_en.eq(1),
            serdes.tx_pattern.eq(sync_pattern)
        )
        fsm.act("WAIT_SAMPLING_WINDOW",
            timer.wait.eq(1),
            If(timer.done,
                timer.wait.eq(0),
                NextState("CONFIGURE_SAMPLING_WINDOW")
            ),
            serdes.tx_pattern_en.eq(1),
            serdes.tx_pattern.eq(sync_pattern)
        )
        fsm.act("READY",
            self.ready.eq(1)
        )
        fsm.act("ERROR",
            self.error.eq(1)
        )


class SlaveInit(Module, AutoCSR):
    def __init__(self, serdes, sync_pattern, taps):
        self.reset = Signal()
        self.ready = Signal()
        self.error = Signal()

        # # #

        self.delay = delay = Signal(max=taps)
        self.delay_min = delay_min = Signal(max=taps)
        self.delay_min_found = delay_min_found = Signal()
        self.delay_max = delay_max = Signal(max=taps)
        self.delay_max_found = delay_max_found = Signal()
        self.bitslip = bitslip = Signal(max=40)

        timer = WaitTimer(1024)
        self.submodules += timer

        self.comb += self.reset.eq(serdes.rx_pattern == 0)

        self.submodules.fsm = fsm = ResetInserter()(FSM(reset_state="IDLE"))
        fsm.act("IDLE",
            NextValue(delay, 0),
            NextValue(delay_min, 0),
            NextValue(delay_min_found, 0),
            NextValue(delay_max, 0),
            NextValue(delay_max_found, 0),
            serdes.rx_delay_rst.eq(1),
            NextValue(bitslip, 0),
            NextState("WAIT_STABLE"),
            serdes.tx_pattern_en.eq(1)
        )
        fsm.act("WAIT_STABLE",
            timer.wait.eq(1),
            If(timer.done,
                timer.wait.eq(0),
                NextState("CHECK_PATTERN")
            ),
            serdes.tx_pattern_en.eq(1)
        )
        fsm.act("CHECK_PATTERN",
            If(~delay_min_found,
                If(serdes.rx_pattern == sync_pattern,
                    timer.wait.eq(1),
                    If(timer.done,
                        timer.wait.eq(0),
                        NextValue(delay_min, delay),
                        NextValue(delay_min_found, 1)
                    )
                ).Else(
                    NextState("INC_DELAY_BITSLIP")
                ),
            ).Else(
                If(serdes.rx_pattern != sync_pattern,
                    NextValue(delay_max, delay),
                    NextValue(delay_max_found, 1),
                    NextState("RESET_SAMPLING_WINDOW")
                ).Else(
                    NextState("INC_DELAY_BITSLIP")
                )
            ),
            serdes.tx_pattern_en.eq(1)
        )
        self.comb += serdes.rx_bitslip_value.eq(bitslip)
        fsm.act("INC_DELAY_BITSLIP",
            NextState("WAIT_STABLE"),
            If(delay == (taps - 1),
                If(delay_min_found,
                    NextState("ERROR")
                ),
                If(bitslip == (40 - 1),
                    NextValue(bitslip, 0)
                ).Else(    
                    NextValue(bitslip, bitslip + 1)
                ),
                NextValue(delay, 0),
                serdes.rx_delay_rst.eq(1)
            ).Else(
                NextValue(delay, delay + 1),
                serdes.rx_delay_inc.eq(1),
                serdes.rx_delay_ce.eq(1)
            ),
            serdes.tx_pattern_en.eq(1)
        )
        fsm.act("RESET_SAMPLING_WINDOW",
            NextValue(delay, 0),
            serdes.rx_delay_rst.eq(1),
            NextState("WAIT_SAMPLING_WINDOW")
        )
        fsm.act("CONFIGURE_SAMPLING_WINDOW",
            If(delay == (delay_min + (delay_max - delay_min)[1:]),
                NextState("SEND_PATTERN")
            ).Else(
                NextValue(delay, delay + 1),
                serdes.rx_delay_inc.eq(1),
                serdes.rx_delay_ce.eq(1),
                NextState("WAIT_SAMPLING_WINDOW")
            )
        )
        fsm.act("WAIT_SAMPLING_WINDOW",
            timer.wait.eq(1),
            If(timer.done,
                timer.wait.eq(0),
                NextState("CONFIGURE_SAMPLING_WINDOW")
            )
        )
        fsm.act("SEND_PATTERN",
            timer.wait.eq(1),
            If(timer.done,
                If(serdes.rx_pattern != sync_pattern,
                    NextState("READY")
                )
            ),
            serdes.tx_pattern_en.eq(1),
            serdes.tx_pattern.eq(sync_pattern)
        )
        fsm.act("READY",
            self.ready.eq(1)
        )
        fsm.act("ERROR",
            self.error.eq(1)
        )


class Control(Module, AutoCSR):
    def __init__(self, init, mode="master"):
        if mode == "master":
            self.reset = CSR()
        self.ready = CSRStatus()
        self.error = CSRStatus()

        self.delay = CSRStatus(9)
        self.delay_min_found = CSRStatus()
        self.delay_min = CSRStatus(9)
        self.delay_max_found = CSRStatus()
        self.delay_max = CSRStatus(9)
        self.bitslip = CSRStatus(6)

        # # #

        if mode == "master":
            self.comb += init.reset.eq(self.reset.re)
        self.comb += [
            self.ready.status.eq(init.ready),
            self.error.status.eq(init.error),
            self.delay.status.eq(init.delay),
            self.delay_min_found.status.eq(init.delay_min_found),
            self.delay_min.status.eq(init.delay_min),
            self.delay_max_found.status.eq(init.delay_max_found),
            self.delay_max.status.eq(init.delay_max),
            self.bitslip.status.eq(init.bitslip)
        ]

# amc specific

class AMCMasterPLL(SerdesPLL):
    def __init__(self):
        SerdesPLL.__init__(self, 125e6, 1.25e9, vco_div=2)

class AMCMasterSerdes(UltrascaleSerdes):
    def __init__(self, pll, pads):
        UltrascaleSerdes.__init__(self, pll, pads, mode="master")

class AMCMasterInit(MasterInit):
    def __init__(self, serdes):
        MasterInit.__init__(self, serdes, sync_pattern=0x123456789a, taps=512)

class AMCMasterControl(Control):
    def __init__(self, init):
        Control.__init__(self, init, mode="master")

# rtm specific

class RTMSlavePLL(SerdesPLL):
    def __init__(self):
        SerdesPLL.__init__(self, 125e6, 1.25e9, vco_div=1)

class RTMSlaveSerdes(Series7Serdes):
    def __init__(self, pll, pads):
        Series7Serdes.__init__(self, pll, pads, mode="slave")

class RTMSlaveInit(SlaveInit):
    def __init__(self, serdes):
        SlaveInit.__init__(self, serdes, sync_pattern=0x123456789a, taps=32)

class RTMSlaveControl(Control):
    def __init__(self, init):
        Control.__init__(self, init, mode="slave")
