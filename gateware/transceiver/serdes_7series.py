from litex.gen import *
from litex.gen.genlib.resetsync import AsyncResetSynchronizer
from litex.gen.genlib.cdc import MultiReg, PulseSynchronizer, Gearbox
from litex.gen.genlib.misc import BitSlip

from litex.soc.interconnect.csr import *
from litex.soc.cores.code_8b10b import Encoder, Decoder

from transceiver.prbs import *


class SERDESPLL(Module):
    def __init__(self, refclk_freq, linerate):
        assert refclk_freq == 125e6
        assert linerate == 1.25e9
        self.lock = Signal()
        self.refclk = Signal()
        self.rtio_clk = Signal()
        self.serdes_clk = Signal()
        self.serdes_div_clk = Signal()

        # refclk: 125MHz
        # pll vco: 1250MHz
        # rtio: 62.5MHz
        # serdes = 625MHz
        # serdes_div = 156.25MHz
        self.linerate = linerate

        pll_locked = Signal()
        pll_fb = Signal()
        pll_rtio_clk = Signal()
        pll_serdes_clk = Signal()
        pll_serdes_div_clk = Signal()
        self.specials += [
            Instance("PLLE2_BASE",
                p_STARTUP_WAIT="FALSE", o_LOCKED=pll_locked,

                # VCO @ 1.25GHz
                p_REF_JITTER1=0.01, p_CLKIN1_PERIOD=8.0,
                p_CLKFBOUT_MULT=10, p_DIVCLK_DIVIDE=1,
                i_CLKIN1=self.refclk, i_CLKFBIN=pll_fb,
                o_CLKFBOUT=pll_fb,

                # 62.5MHz: rtio
                p_CLKOUT0_DIVIDE=20, p_CLKOUT0_PHASE=0.0,
                o_CLKOUT0=pll_rtio_clk,

                # 625MHz: serdes
                p_CLKOUT1_DIVIDE=2, p_CLKOUT1_PHASE=0.0,
                o_CLKOUT1=pll_serdes_clk,

                # 156.25MHz: serdes_div
                p_CLKOUT2_DIVIDE=8, p_CLKOUT2_PHASE=0.0,
                o_CLKOUT2=pll_serdes_div_clk
            ),
            Instance("BUFG", i_I=pll_rtio_clk, o_O=self.rtio_clk),
            Instance("BUFG", i_I=pll_serdes_clk, o_O=self.serdes_clk),
            Instance("BUFG", i_I=pll_serdes_div_clk, o_O=self.serdes_div_clk)
        ]
        self.comb += self.lock.eq(pll_locked)


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
        # and we will fall in these 2 following possible cases:
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
        self.sync.serdes_div += mdata_d.eq(self.mdata)
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
        self.sync.serdes_div += [
            If(reset_lateness,
                lateness.eq(2**(nbits - 1))
            ).Elif(~too_late & ~too_early,
                If(inc, lateness.eq(lateness - 1)),
                If(dec, lateness.eq(lateness + 1))
            )
        ]

        # control / status cdc
        self.specials += MultiReg(Cat(too_late, too_early), self.status.status)
        self.submodules.do_reset_lateness = PulseSynchronizer("sys", "serdes_div")
        self.comb += [
            reset_lateness.eq(self.do_reset_lateness.o),
            self.do_reset_lateness.i.eq(self.reset.re)
        ]


class SERDES(Module, AutoCSR):
    def __init__(self, pll, pads, mode="master"):
        self.tx_pattern = CSRStorage(20)
        self.tx_produce_square_wave = CSRStorage()
        self.tx_prbs_config = CSRStorage(2)

        self.rx_pattern = CSRStatus(20)
        self.rx_prbs_config = CSRStorage(2)
        self.rx_prbs_errors = CSRStatus(32)

        self.rx_bitslip_value = CSRStorage(5)
        self.rx_delay_rst = CSR()
        self.rx_delay_inc = CSRStorage()
        self.rx_delay_ce = CSR()

        # # #

        self.submodules.encoder = ClockDomainsRenamer("rtio")(
            Encoder(2, True))
        self.decoders = [ClockDomainsRenamer("rtio")(
            Decoder(True)) for _ in range(2)]
        self.submodules += self.decoders

        # clocking
        # master mode:
        # - linerate/10 pll refclk provided externally
        # - linerate/10 clock generated on clk_pads
        # slave mode:
        # - linerate/10 pll refclk provided by clk_pads
        self.clock_domains.cd_rtio = ClockDomain()
        self.clock_domains.cd_serdes = ClockDomain()
        self.clock_domains.cd_serdes_div = ClockDomain()
        self.comb += [
            self.cd_rtio.clk.eq(pll.rtio_clk),
            self.cd_serdes.clk.eq(pll.serdes_clk),
            self.cd_serdes_div.clk.eq(pll.serdes_div_clk)
        ]
        self.specials += [
            AsyncResetSynchronizer(self.cd_rtio, ~pll.lock),
            AsyncResetSynchronizer(self.cd_serdes, ~pll.lock),
            AsyncResetSynchronizer(self.cd_serdes_div, ~pll.lock)
        ]

        # control/status cdc
        tx_pattern = Signal(20)
        tx_produce_square_wave = Signal()
        tx_prbs_config = Signal(2)

        rx_pattern = Signal(20)
        rx_prbs_config = Signal(2)
        rx_prbs_errors = Signal(32)

        rx_bitslip_value = Signal(5)

        self.specials += [
            MultiReg(self.tx_pattern.storage, tx_pattern, "rtio"),
            MultiReg(self.tx_produce_square_wave.storage, tx_produce_square_wave, "rtio"),
            MultiReg(self.tx_prbs_config.storage, tx_prbs_config, "rtio"),
        ]

        self.specials += [
            MultiReg(rx_pattern, self.rx_pattern.status, "sys"),
            MultiReg(self.rx_prbs_config.storage, rx_prbs_config, "rtio"),
            MultiReg(rx_prbs_errors, self.rx_prbs_errors.status, "sys"), # FIXME
        ]

        self.specials += MultiReg(self.rx_bitslip_value.storage, rx_bitslip_value, "rtio"),

        # tx clock (linerate/10)
        if mode == "master":
            self.submodules.tx_clk_gearbox = Gearbox(20, "rtio", 8, "serdes_div")
            self.comb += self.tx_clk_gearbox.i.eq(0b11111000001111100000)

            clk_o = Signal()
            self.specials += [
                Instance("OSERDESE2",
                    p_DATA_WIDTH=8, p_TRISTATE_WIDTH=1,
                    p_DATA_RATE_OQ="DDR", p_DATA_RATE_TQ="BUF",
                    p_SERDES_MODE="MASTER",

                    o_OQ=clk_o,
                    i_OCE=1,
                    i_RST=ResetSignal("serdes_div"),
                    i_CLK=ClockSignal("serdes"), i_CLKDIV=ClockSignal("serdes_div"),
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

        # tx data and prbs
        self.submodules.tx_prbs = ClockDomainsRenamer("rtio")(PRBSTX(20, True))
        self.comb += self.tx_prbs.config.eq(tx_prbs_config)
        self.submodules.tx_gearbox = Gearbox(20, "rtio", 8, "serdes_div")
        self.sync.rtio += [
            self.tx_prbs.i.eq(Cat(*[self.encoder.output[i] for i in range(2)])),
            If(tx_pattern != 0,
                self.tx_gearbox.i.eq(tx_pattern)
            ).Elif(tx_produce_square_wave,
                # square wave @ linerate/20 for scope observation
                self.tx_gearbox.i.eq(0b11111111110000000000)
            ).Else(
                self.tx_gearbox.i.eq(self.tx_prbs.o)
            )
        ]

        serdes_o = Signal()
        self.specials += [
            Instance("OSERDESE2",
                p_DATA_WIDTH=8, p_TRISTATE_WIDTH=1,
                p_DATA_RATE_OQ="DDR", p_DATA_RATE_TQ="BUF",
                p_SERDES_MODE="MASTER",

                o_OQ=serdes_o,
                i_OCE=1,
                i_RST=ResetSignal("serdes_div"),
                i_CLK=ClockSignal("serdes"), i_CLKDIV=ClockSignal("serdes_div"),
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
        use_bufr = False
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

        # rx
        self.submodules.rx_gearbox = Gearbox(8, "serdes_div", 20, "rtio")
        self.submodules.rx_bitslip = ClockDomainsRenamer("rtio")(BitSlip(20))

        self.submodules.phase_detector = ClockDomainsRenamer("serdes_div")(
            PhaseDetector())

        # use 2 serdes for phase detection: 1 master/ 1 slave
        serdes_m_i_nodelay = Signal()
        serdes_s_i_nodelay = Signal()
        self.specials += [
            Instance("IBUFDS_DIFF_OUT",
                i_I=pads.rx_p,
                i_IB=pads.rx_n,
                o_O=serdes_m_i_nodelay,
                o_OB=serdes_s_i_nodelay,
            )
        ]

        serdes_m_i_delayed = Signal()
        serdes_m_q = Signal(8)
        serdes_m_idelay_value = int(1/(4*pll.linerate)/78e-12) # 1/4 bit period
        assert serdes_m_idelay_value < 32
        self.specials += [
            Instance("IDELAYE2",
                p_DELAY_SRC="IDATAIN", p_SIGNAL_PATTERN="DATA",
                p_CINVCTRL_SEL="FALSE", p_HIGH_PERFORMANCE_MODE="TRUE",
                p_REFCLK_FREQUENCY=200.0, p_PIPE_SEL="FALSE",
                p_IDELAY_TYPE="VARIABLE", p_IDELAY_VALUE=serdes_m_idelay_value,

                i_C=ClockSignal(),
                i_LD=self.rx_delay_rst.re,
                i_CE=self.rx_delay_ce.re,
                i_LDPIPEEN=0, i_INC=self.rx_delay_inc.storage,

                i_IDATAIN=serdes_m_i_nodelay, o_DATAOUT=serdes_m_i_delayed
            ),
            Instance("ISERDESE2",
                p_DATA_WIDTH=8, p_DATA_RATE="DDR",
                p_SERDES_MODE="MASTER", p_INTERFACE_TYPE="NETWORKING",
                p_NUM_CE=1, p_IOBDELAY="IFD",

                i_DDLY=serdes_m_i_delayed,
                i_CE1=1,
                i_RST=ResetSignal("serdes_div"),
                i_CLK=ClockSignal("serdes"), i_CLKB=~ClockSignal("serdes"),
                i_CLKDIV=ClockSignal("serdes_div"),
                i_BITSLIP=0,
                o_Q8=serdes_m_q[0], o_Q7=serdes_m_q[1],
                o_Q6=serdes_m_q[2], o_Q5=serdes_m_q[3],
                o_Q4=serdes_m_q[4], o_Q3=serdes_m_q[5],
                o_Q2=serdes_m_q[6], o_Q1=serdes_m_q[7]
            ),
        ]
        self.comb += self.phase_detector.mdata.eq(serdes_m_q)

        serdes_s_i_delayed = Signal()
        serdes_s_q = Signal(8)
        serdes_s_idelay_value = int(1/(2*pll.linerate)/78e-12) # 1/2 bit period
        assert serdes_s_idelay_value < 32
        self.specials += [
            Instance("IDELAYE2",
                p_DELAY_SRC="IDATAIN", p_SIGNAL_PATTERN="DATA",
                p_CINVCTRL_SEL="FALSE", p_HIGH_PERFORMANCE_MODE="TRUE",
                p_REFCLK_FREQUENCY=200.0, p_PIPE_SEL="FALSE",
                p_IDELAY_TYPE="VARIABLE", p_IDELAY_VALUE=serdes_s_idelay_value,

                i_C=ClockSignal(),
                i_LD=self.rx_delay_rst.re,
                i_CE=self.rx_delay_ce.re,
                i_LDPIPEEN=0, i_INC=self.rx_delay_inc.storage,

                i_IDATAIN=serdes_s_i_nodelay, o_DATAOUT=serdes_s_i_delayed
            ),
            Instance("ISERDESE2",
                p_DATA_WIDTH=8, p_DATA_RATE="DDR",
                p_SERDES_MODE="MASTER", p_INTERFACE_TYPE="NETWORKING",
                p_NUM_CE=1, p_IOBDELAY="IFD",

                i_DDLY=serdes_s_i_delayed,
                i_CE1=1,
                i_RST=ResetSignal("serdes_div"),
                i_CLK=ClockSignal("serdes"), i_CLKB=~ClockSignal("serdes"),
                i_CLKDIV=ClockSignal("serdes_div"),
                i_BITSLIP=0,
                o_Q8=serdes_s_q[0], o_Q7=serdes_s_q[1],
                o_Q6=serdes_s_q[2], o_Q5=serdes_s_q[3],
                o_Q4=serdes_s_q[4], o_Q3=serdes_s_q[5],
                o_Q2=serdes_s_q[6], o_Q1=serdes_s_q[7]
            ),
        ]
        self.comb += self.phase_detector.sdata.eq(~serdes_s_q)

        # rx data and prbs
        self.submodules.rx_prbs = ClockDomainsRenamer("rtio")(PRBSRX(20, True))
        self.comb += [
            self.rx_prbs.config.eq(rx_prbs_config),
            rx_prbs_errors.eq(self.rx_prbs.errors)
        ]
        self.comb += [
            self.rx_gearbox.i.eq(serdes_m_q),
            self.rx_bitslip.value.eq(rx_bitslip_value),
            self.rx_bitslip.i.eq(self.rx_gearbox.o),
            rx_pattern.eq(self.rx_gearbox.o),
            self.decoders[0].input.eq(self.rx_bitslip.o[:10]),
            self.decoders[1].input.eq(self.rx_bitslip.o[10:]),
            self.rx_prbs.i.eq(self.rx_bitslip.o)
        ]
