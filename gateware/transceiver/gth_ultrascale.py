from litex.gen import *
from litex.gen.genlib.resetsync import AsyncResetSynchronizer

from litex.soc.cores.code_8b10b import Encoder, Decoder

from transceiver.gth_ultrascale_init import GTHInit
from transceiver.clock_aligner import BruteforceClockAligner

from transceiver.prbs import *


class GTHChannelPLL(Module):
    def __init__(self, refclk, refclk_freq, linerate):
        self.refclk = refclk
        self.reset = Signal()
        self.lock = Signal()
        self.config = self.compute_config(refclk_freq, linerate)

    @staticmethod
    def compute_config(refclk_freq, linerate):
        for n1 in 4, 5:
            for n2 in 1, 2, 3, 4, 5:
                for m in 1, 2:
                    vco_freq = refclk_freq*(n1*n2)/m
                    if 2.0e9 <= vco_freq <= 6.25e9:
                        for d in 1, 2, 4, 8, 16:
                            current_linerate = vco_freq*2/d
                            if current_linerate == linerate:
                                return {"n1": n1, "n2": n2, "m": m, "d": d,
                                        "vco_freq": vco_freq,
                                        "clkin": refclk_freq,
                                        "linerate": linerate}
        msg = "No config found for {:3.2f} MHz refclk / {:3.2f} Gbps linerate."
        raise ValueError(msg.format(refclk_freq/1e6, linerate/1e9))

    def __repr__(self):
        r = """
GTHChannelPLL
==============
  overview:
  ---------
       +--------------------------------------------------+
       |                                                  |
       |   +-----+  +---------------------------+ +-----+ |
       |   |     |  | Phase Frequency Detector  | |     | |
CLKIN +----> /M  +-->       Charge Pump         +-> VCO +---> CLKOUT
       |   |     |  |       Loop Filter         | |     | |
       |   +-----+  +---------------------------+ +--+--+ |
       |              ^                              |    |
       |              |    +-------+    +-------+    |    |
       |              +----+  /N2  <----+  /N1  <----+    |
       |                   +-------+    +-------+         |
       +--------------------------------------------------+
                            +-------+
                   CLKOUT +->  2/D  +-> LINERATE
                            +-------+
  config:
  -------
    CLKIN    = {clkin}MHz
    CLKOUT   = CLKIN x (N1 x N2) / M = {clkin}MHz x ({n1} x {n2}) / {m}
             = {vco_freq}GHz
    LINERATE = CLKOUT x 2 / D = {vco_freq}GHz x 2 / {d}
             = {linerate}GHz
""".format(clkin=self.config["clkin"]/1e6,
           n1=self.config["n1"],
           n2=self.config["n2"],
           m=self.config["m"],
           vco_freq=self.config["vco_freq"]/1e9,
           d=self.config["d"],
           linerate=self.config["linerate"]/1e9)
        return r


class GTH(Module):
    def __init__(self, cpll, tx_pads, rx_pads, sys_clk_freq,
                 clock_aligner=True, internal_loopback=False,
                 tx_polarity=0, rx_polarity=0):
        self.tx_produce_square_wave = Signal()

        # # #

        self.submodules.encoder = ClockDomainsRenamer("rtio")(
            Encoder(2, True))
        self.decoders = [ClockDomainsRenamer("rtio_rx")(
            Decoder(True)) for _ in range(2)]
        self.submodules += self.decoders

        self.rx_ready = Signal()

        # transceiver direct clock outputs
        # useful to specify clock constraints in a way palatable to Vivado
        self.txoutclk = Signal()
        self.rxoutclk = Signal()

        self.rtio_clk_freq = cpll.config["linerate"]/20

        # # #

        # TX generates RTIO clock, init must be in system domain
        tx_init = GTHInit(sys_clk_freq, False)
        # RX receives restart commands from RTIO domain
        rx_init = ClockDomainsRenamer("rtio")(
            GTHInit(self.rtio_clk_freq, True))
        self.submodules += tx_init, rx_init
        self.comb += [
            tx_init.plllock.eq(cpll.lock),
            rx_init.plllock.eq(cpll.lock),
            cpll.reset.eq(tx_init.pllreset)
        ]

        txdata = Signal(20)
        rxdata = Signal(20)
        rxphaligndone = Signal()
        self.specials += \
            Instance("GTHE3_CHANNEL",
                # Reset modes
                i_GTRESETSEL=0,
                i_RESETOVRD=0,

                # PMA Attributes
                p_PMA_RSV1=0xf000,
                p_RX_BIAS_CFG0=0x0AB4,
                p_RX_CM_TRIM=0b1010,
                p_RX_CLK25_DIV=5,
                p_TX_CLK25_DIV=5,

                # Power-Down Attributes
                p_PD_TRANS_TIME_FROM_P2=0x3c,
                p_PD_TRANS_TIME_NONE_P2=0x19,
                p_PD_TRANS_TIME_TO_P2=0x64,

                # CPLL
                p_CPLL_INIT_CFG0=0x2b2,
                p_CPLL_LOCK_CFG=0x1e8,
                p_CPLL_CFG0=0x67f8,
                p_CPLL_CFG1=0xa4ac,
                p_CPLL_CFG2=0x0007,
                p_CPLL_CFG3=0x0000,
                p_CPLL_FBDIV=cpll.config["n2"],
                p_CPLL_FBDIV_45=cpll.config["n1"],
                p_CPLL_REFCLK_DIV=cpll.config["m"],
                p_RXOUT_DIV=cpll.config["d"],
                p_TXOUT_DIV=cpll.config["d"],
                i_CPLLRESET=0,
                i_CPLLPD=cpll.reset,
                o_CPLLLOCK=cpll.lock,
                i_CPLLLOCKEN=1,
                i_CPLLREFCLKSEL=0b001,
                i_TSTIN=2**20-1,
                i_GTREFCLK0=cpll.refclk,

                # QPLL
                i_QPLL0CLK=0,
                i_QPLL0REFCLK=0,
                i_QPLL1CLK=0,
                i_QPLL1REFCLK=0,

                # TX clock
                p_TXBUF_EN="FALSE",
                p_TX_XCLK_SEL="TXUSR",
                o_TXOUTCLK=self.txoutclk,
                i_TXSYSCLKSEL=0b00,
                i_TXPLLCLKSEL=0b00,
                i_TXOUTCLKSEL=0b11,

                # TX Startup/Reset
                i_GTTXRESET=tx_init.gtXxreset,
                o_TXRESETDONE=tx_init.Xxresetdone,
                i_TXDLYSRESET=tx_init.Xxdlysreset,
                o_TXDLYSRESETDONE=tx_init.Xxdlysresetdone,
                o_TXPHALIGNDONE=tx_init.Xxphaligndone,
                i_TXUSERRDY=tx_init.Xxuserrdy,
                i_TXSYNCMODE=1,

                # TX data
                p_TX_DATA_WIDTH=20,
                p_TX_INT_DATAWIDTH=0,
                i_TXCTRL0=Cat(txdata[8], txdata[18]),
                i_TXCTRL1=Cat(txdata[9], txdata[19]),
                i_TXDATA=Cat(txdata[:8], txdata[10:18]),
                i_TXUSRCLK=ClockSignal("rtio"),
                i_TXUSRCLK2=ClockSignal("rtio"),

                # TX electrical
                i_TXPD=0b00,
                p_TX_CLKMUX_EN=1,
                i_TXBUFDIFFCTRL=0b000,
                i_TXDIFFCTRL=0b1100,

                # Internal Loopback
                i_LOOPBACK=0b010 if internal_loopback else 0b000,

                # RX Startup/Reset
                i_GTRXRESET=rx_init.gtXxreset,
                o_RXRESETDONE=rx_init.Xxresetdone,
                i_RXDLYSRESET=rx_init.Xxdlysreset,
                o_RXPHALIGNDONE=rxphaligndone,
                i_RXSYNCALLIN=rxphaligndone,
                i_RXUSERRDY=rx_init.Xxuserrdy,
                i_RXSYNCIN=0,
                i_RXSYNCMODE=1,
                o_RXSYNCDONE=rx_init.Xxsyncdone,

                # RX AFE
                i_RXDFEAGCCTRL=1,
                i_RXDFEXYDEN=1,
                i_RXLPMEN=1,
                i_RXOSINTCFG=0xd,
                i_RXOSINTEN=1,

                # RX clock
                i_RXRATE=0,
                i_RXDLYBYPASS=0,
                p_RXBUF_EN="FALSE",
                p_RX_XCLK_SEL="RXUSR",
                i_RXSYSCLKSEL=0b00,
                i_RXOUTCLKSEL=0b010,
                i_RXPLLCLKSEL=0b00,
                o_RXOUTCLK=self.rxoutclk,
                i_RXUSRCLK=ClockSignal("rtio_rx"),
                i_RXUSRCLK2=ClockSignal("rtio_rx"),

                # RX Clock Correction Attributes
                p_CLK_CORRECT_USE="FALSE",
                p_CLK_COR_SEQ_1_1=0b0100000000,
                p_CLK_COR_SEQ_2_1=0b0100000000,
                p_CLK_COR_SEQ_1_ENABLE=0b1111,
                p_CLK_COR_SEQ_2_ENABLE=0b1111,

                # RX data
                p_RX_DATA_WIDTH=20,
                p_RX_INT_DATAWIDTH=0,
                o_RXCTRL0=Cat(rxdata[8], rxdata[18]),
                o_RXCTRL1=Cat(rxdata[9], rxdata[19]),
                o_RXDATA=Cat(rxdata[:8], rxdata[10:18]),

                # RX electrical
                i_RXPD=0b00,
                p_RX_CLKMUX_EN=1,
                i_RXELECIDLEMODE=0b11,

                # Polarity
                i_TXPOLARITY=tx_polarity,
                i_RXPOLARITY=rx_polarity,

                # Pads
                i_GTHRXP=rx_pads.p,
                i_GTHRXN=rx_pads.n,
                o_GTHTXP=tx_pads.p,
                o_GTHTXN=tx_pads.n
            )

        # tx clocking
        tx_reset_deglitched = Signal()
        tx_reset_deglitched.attr.add("no_retiming")
        self.sync += tx_reset_deglitched.eq(~tx_init.done)
        self.clock_domains.cd_rtio = ClockDomain()
        tx_bufg_div = cpll.config["clkin"]/self.rtio_clk_freq
        assert tx_bufg_div == int(tx_bufg_div)
        self.specials += [
            Instance("BUFG_GT", i_I=self.txoutclk, o_O=self.cd_rtio.clk,
                i_DIV=int(tx_bufg_div)-1),
            AsyncResetSynchronizer(self.cd_rtio, tx_reset_deglitched)
        ]

        # rx clocking
        rx_reset_deglitched = Signal()
        rx_reset_deglitched.attr.add("no_retiming")
        self.sync.rtio += rx_reset_deglitched.eq(~rx_init.done)
        self.clock_domains.cd_rtio_rx = ClockDomain()
        self.specials += [
            Instance("BUFG_GT", i_I=self.rxoutclk, o_O=self.cd_rtio_rx.clk),
            AsyncResetSynchronizer(self.cd_rtio_rx, rx_reset_deglitched)
        ]

        # tx data and prbs
        self.submodules.tx_prbs = ClockDomainsRenamer("rtio")(PRBSTX(20, True))
        self.comb += [
            self.tx_prbs.i.eq(Cat(*[self.encoder.output[i] for i in range(2)])),
            If(self.tx_produce_square_wave,
                # square wave @ linerate/20 for scope observation
                txdata.eq(0b11111111110000000000)
            ).Else(
                txdata.eq(self.tx_prbs.o)
            )
        ]

        # rx data and prbs
        self.submodules.rx_prbs = ClockDomainsRenamer("rtio_rx")(PRBSRX(20, True))
        self.comb += [
            self.decoders[0].input.eq(rxdata[:10]),
            self.decoders[1].input.eq(rxdata[10:]),
            self.rx_prbs.i.eq(rxdata)
        ]

        # clock alignment
        if clock_aligner:
            clock_aligner = BruteforceClockAligner(0b0101111100, self.rtio_clk_freq)
            self.submodules += clock_aligner
            self.comb += [
                clock_aligner.rxdata.eq(rxdata),
                rx_init.restart.eq(clock_aligner.restart),
                self.rx_ready.eq(clock_aligner.ready)
            ]
        else:
            self.comb += self.rx_ready.eq(rx_init.done)

# TODO:
# - expose prbs?
# - do something specific for rx clocks?
class MultiGTH(Module):
    def __init__(self, cpll, tx_pads, rx_pads, sys_clk_freq, **kwargs):
        self.nlanes = nlanes = len(tx_pads.p)

        class EncoderExposer:
            def __init__(self):
                self.k = Signal()
                self.d = Signal(8)

        self.gths = [None for i in range(nlanes)]
        self.encoders = [EncoderExposer() for i in range(2*nlanes)]
        self.decoders = [None for i in range(2*nlanes)]
        self.rx_ready = Signal()

        # # #

        def get_pads(pads, i):
            class GTHPads:
                def __init__(self, p, n):
                    self.p = p
                    self.n = n
            return GTHPads(pads.p[i], pads.n[i])

        rx_ready = Signal(reset=1)
        for i in range(nlanes):
            gth = GTH(cpll, get_pads(tx_pads, i), get_pads(rx_pads, i), sys_clk_freq, **kwargs)
            self.gths[i] = gth
            setattr(self.submodules, "gth"+str(i), gth)
            for j in range(2):
                self.comb += [
                    gth.encoder.k[j].eq(self.encoders[2*i + j].k),
                    gth.encoder.d[j].eq(self.encoders[2*i + j].d)
                ]
                self.decoders[2*i + j] = gth.decoders[j]
            new_rx_ready = Signal()
            self.comb += new_rx_ready.eq(rx_ready & gth.rx_ready)
            rx_ready = new_rx_ready

        self.comb += self.rx_ready.eq(rx_ready)
