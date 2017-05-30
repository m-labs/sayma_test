from litex.gen import *
from litex.gen.genlib.resetsync import AsyncResetSynchronizer
from litex.gen.genlib.cdc import MultiReg, PulseSynchronizer, Gearbox
from litex.gen.genlib.misc import BitSlip

from litex.soc.interconnect.csr import *
from litex.soc.cores.code_8b10b import Encoder, Decoder

from transceiver.prbs import *
from transceiver.phase_detector import PhaseDetector


class SERDESPLL(Module):
    def __init__(self, refclk_freq, linerate):
        assert refclk_freq == 125e6
        assert linerate == 1.25e9
        self.lock = Signal()
        self.refclk = Signal()
        self.serdes_clk = Signal()
        self.serdes_10x_clk = Signal()
        self.serdes_2p5x_clk = Signal()

        # refclk: 125MHz
        # pll vco: 1250MHz
        # serdes: 62.5MHz
        # serdes_10x = 625MHz
        # serdes_2p5x = 156.25MHz
        self.linerate = linerate

        pll_locked = Signal()
        pll_fb = Signal()
        pll_serdes_clk = Signal()
        pll_serdes_10x_clk = Signal()
        pll_serdes_2p5x_clk = Signal()
        self.specials += [
            Instance("PLLE2_BASE",
                p_STARTUP_WAIT="FALSE", o_LOCKED=pll_locked,

                # VCO @ 1.25GHz
                p_REF_JITTER1=0.01, p_CLKIN1_PERIOD=8.0,
                p_CLKFBOUT_MULT=10, p_DIVCLK_DIVIDE=1,
                i_CLKIN1=self.refclk, i_CLKFBIN=pll_fb,
                o_CLKFBOUT=pll_fb,

                # 62.5MHz: serdes
                p_CLKOUT0_DIVIDE=20, p_CLKOUT0_PHASE=0.0,
                o_CLKOUT0=pll_serdes_clk,

                # 625MHz: serdes_10x
                p_CLKOUT1_DIVIDE=2, p_CLKOUT1_PHASE=0.0,
                o_CLKOUT1=pll_serdes_10x_clk,

                # 156.25MHz: serdes_2p5x
                p_CLKOUT2_DIVIDE=8, p_CLKOUT2_PHASE=0.0,
                o_CLKOUT2=pll_serdes_2p5x_clk
            ),
            Instance("BUFG", i_I=pll_serdes_clk, o_O=self.serdes_clk),
            Instance("BUFG", i_I=pll_serdes_10x_clk, o_O=self.serdes_10x_clk),
            Instance("BUFG", i_I=pll_serdes_2p5x_clk, o_O=self.serdes_2p5x_clk)
        ]
        self.comb += self.lock.eq(pll_locked)


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

        self.submodules.encoder = ClockDomainsRenamer("serdes")(
            Encoder(2, True))
        self.decoders = [ClockDomainsRenamer("serdes")(
            Decoder(True)) for _ in range(2)]
        self.submodules += self.decoders

        # clocking
        # master mode:
        # - linerate/10 pll refclk provided externally
        # - linerate/10 clock generated on clk_pads
        # slave mode:
        # - linerate/10 pll refclk provided by clk_pads
        self.clock_domains.cd_serdes = ClockDomain()
        self.clock_domains.cd_serdes_10x = ClockDomain()
        self.clock_domains.cd_serdes_2p5x = ClockDomain()
        self.comb += [
            self.cd_serdes.clk.eq(pll.serdes_clk),
            self.cd_serdes_10x.clk.eq(pll.serdes_10x_clk),
            self.cd_serdes_2p5x.clk.eq(pll.serdes_2p5x_clk)
        ]
        self.specials += [
            AsyncResetSynchronizer(self.cd_serdes, ~pll.lock),
            AsyncResetSynchronizer(self.cd_serdes_10x, ~pll.lock),
            AsyncResetSynchronizer(self.cd_serdes_2p5x, ~pll.lock)
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
            MultiReg(self.tx_pattern.storage, tx_pattern, "serdes"),
            MultiReg(self.tx_produce_square_wave.storage, tx_produce_square_wave, "serdes"),
            MultiReg(self.tx_prbs_config.storage, tx_prbs_config, "serdes"),
        ]

        self.specials += [
            MultiReg(rx_pattern, self.rx_pattern.status, "sys"),
            MultiReg(self.rx_prbs_config.storage, rx_prbs_config, "serdes"),
            MultiReg(rx_prbs_errors, self.rx_prbs_errors.status, "sys"), # FIXME
        ]

        self.specials += MultiReg(self.rx_bitslip_value.storage, rx_bitslip_value, "serdes"),

        # tx clock (linerate/10)
        if mode == "master":
            self.submodules.tx_clk_gearbox = Gearbox(20, "serdes", 8, "serdes_2p5x")
            self.comb += self.tx_clk_gearbox.i.eq(0b11111000001111100000)

            clk_o = Signal()
            self.specials += [
                Instance("OSERDESE2",
                    p_DATA_WIDTH=8, p_TRISTATE_WIDTH=1,
                    p_DATA_RATE_OQ="DDR", p_DATA_RATE_TQ="BUF",
                    p_SERDES_MODE="MASTER",

                    o_OQ=clk_o,
                    i_OCE=1,
                    i_RST=ResetSignal("serdes_2p5x"),
                    i_CLK=ClockSignal("serdes_10x"), i_CLKDIV=ClockSignal("serdes_2p5x"),
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
        self.submodules.tx_prbs = ClockDomainsRenamer("serdes")(PRBSTX(20, True))
        self.comb += self.tx_prbs.config.eq(tx_prbs_config)
        self.submodules.tx_gearbox = Gearbox(20, "serdes", 8, "serdes_2p5x")
        self.sync.serdes += [
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
                i_RST=ResetSignal("serdes_2p5x"),
                i_CLK=ClockSignal("serdes_10x"), i_CLKDIV=ClockSignal("serdes_2p5x"),
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
        self.submodules.rx_gearbox = Gearbox(8, "serdes_2p5x", 20, "serdes")
        self.submodules.rx_bitslip = ClockDomainsRenamer("serdes")(BitSlip(20))

        self.submodules.phase_detector = ClockDomainsRenamer("serdes_2p5x")(
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
                i_RST=ResetSignal("serdes_2p5x"),
                i_CLK=ClockSignal("serdes_10x"), i_CLKB=~ClockSignal("serdes_10x"),
                i_CLKDIV=ClockSignal("serdes_2p5x"),
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
                i_RST=ResetSignal("serdes_2p5x"),
                i_CLK=ClockSignal("serdes_10x"), i_CLKB=~ClockSignal("serdes_10x"),
                i_CLKDIV=ClockSignal("serdes_2p5x"),
                i_BITSLIP=0,
                o_Q8=serdes_s_q[0], o_Q7=serdes_s_q[1],
                o_Q6=serdes_s_q[2], o_Q5=serdes_s_q[3],
                o_Q4=serdes_s_q[4], o_Q3=serdes_s_q[5],
                o_Q2=serdes_s_q[6], o_Q1=serdes_s_q[7]
            ),
        ]
        self.comb += self.phase_detector.sdata.eq(~serdes_s_q)

        # rx data and prbs
        self.submodules.rx_prbs = ClockDomainsRenamer("serdes")(PRBSRX(20, True))
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
