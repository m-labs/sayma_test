from litex.gen import *
from litex.gen.genlib.resetsync import AsyncResetSynchronizer
from litex.gen.genlib.cdc import MultiReg, PulseSynchronizer, Gearbox
from litex.gen.genlib.misc import BitSlip, WaitTimer

from litex.soc.interconnect.csr import *
from litex.soc.cores.code_8b10b import Encoder, Decoder

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
        # pll vco: 625MHz
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

                # VCO @ 625MHz
                p_REF_JITTER1=0.01, p_CLKIN1_PERIOD=8.0,
                p_CLKFBOUT_MULT=5, p_DIVCLK_DIVIDE=1,
                i_CLKIN1=self.refclk, i_CLKFBIN=pll_fb,
                o_CLKFBOUT=pll_fb,

                # 62.5MHz: serdes
                p_CLKOUT0_DIVIDE=10, p_CLKOUT0_PHASE=0.0,
                o_CLKOUT0=pll_serdes_clk,

                # 625MHz: serdes_10x
                p_CLKOUT1_DIVIDE=1, p_CLKOUT1_PHASE=0.0,
                o_CLKOUT1=pll_serdes_10x_clk,

                # 156.25MHz: serdes_2p5x
                p_CLKOUT2_DIVIDE=4, p_CLKOUT2_PHASE=0.0,
                o_CLKOUT2=pll_serdes_2p5x_clk
            ),
            Instance("BUFG", i_I=pll_serdes_clk, o_O=self.serdes_clk),
            Instance("BUFG", i_I=pll_serdes_10x_clk, o_O=self.serdes_10x_clk),
            Instance("BUFG", i_I=pll_serdes_2p5x_clk, o_O=self.serdes_2p5x_clk)
        ]
        self.comb += self.lock.eq(pll_locked)


class SERDES(Module):
    def __init__(self, pll, pads, mode="master"):
        self.tx_pattern = Signal(20)
        self.tx_pattern_en = Signal()

        self.rx_pattern = Signal(20)

        self.rx_bitslip_value = Signal(5)
        self.rx_delay_rst = Signal()
        self.rx_delay_inc = Signal()
        self.rx_delay_ce = Signal()
        self.rx_delay_en_vtc = Signal()

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
        tx_pattern_en = Signal()

        rx_pattern = Signal(20)

        rx_bitslip_value = Signal(5)
        rx_delay_rst = Signal()
        rx_delay_inc = Signal()
        rx_delay_en_vtc = Signal()
        rx_delay_ce = Signal()

        self.specials += [
            MultiReg(self.tx_pattern, tx_pattern, "serdes"),
            MultiReg(self.tx_pattern_en, tx_pattern_en, "serdes")
        ]

        self.specials += [
            MultiReg(rx_pattern, self.rx_pattern, "sys"),
        ]

        self.specials += [
            MultiReg(self.rx_bitslip_value, rx_bitslip_value, "serdes"),
            MultiReg(self.rx_delay_inc, rx_delay_inc, "serdes_2p5x"),
            MultiReg(self.rx_delay_en_vtc, rx_delay_en_vtc, "serdes_2p5x")
        ]
        self.submodules.do_rx_delay_rst = PulseSynchronizer("sys", "serdes_2p5x")
        self.comb += [
            rx_delay_rst.eq(self.do_rx_delay_rst.o),
            self.do_rx_delay_rst.i.eq(self.rx_delay_rst)
        ]
        self.submodules.do_rx_delay_ce = PulseSynchronizer("sys", "serdes_2p5x")
        self.comb += [
            rx_delay_ce.eq(self.do_rx_delay_ce.o),
            self.do_rx_delay_ce.i.eq(self.rx_delay_ce)
        ]

        # tx clock (linerate/10)
        if mode == "master":
            self.submodules.tx_clk_gearbox = Gearbox(20, "serdes", 8, "serdes_2p5x")
            self.comb += self.tx_clk_gearbox.i.eq(0b11111000001111100000)

            clk_o = Signal()
            self.specials += [
                Instance("OSERDESE3",
                    p_DATA_WIDTH=8, p_INIT=0,
                    p_IS_CLK_INVERTED=0, p_IS_CLKDIV_INVERTED=0, p_IS_RST_INVERTED=0,

                    o_OQ=clk_o,
                    i_RST=ResetSignal("serdes_2p5x"),
                    i_CLK=ClockSignal("serdes_10x"), i_CLKDIV=ClockSignal("serdes_2p5x"),
                    i_D=self.tx_clk_gearbox.o
                ),
                Instance("OBUFDS",
                    i_I=clk_o,
                    o_O=pads.clk_p,
                    o_OB=pads.clk_n
                )
            ]

        # tx data
        self.submodules.tx_gearbox = Gearbox(20, "serdes", 8, "serdes_2p5x")
        self.sync.serdes += [
            If(tx_pattern_en,
                self.tx_gearbox.i.eq(tx_pattern)
            ).Else(
                self.tx_gearbox.i.eq(Cat(*[self.encoder.output[i] for i in range(2)]))
            )
        ]

        serdes_o = Signal()
        self.specials += [
            Instance("OSERDESE3",
                p_DATA_WIDTH=8, p_INIT=0,
                p_IS_CLK_INVERTED=0, p_IS_CLKDIV_INVERTED=0, p_IS_RST_INVERTED=0,

                o_OQ=serdes_o,
                i_RST=ResetSignal("serdes_2p5x"),
                i_CLK=ClockSignal("serdes_10x"), i_CLKDIV=ClockSignal("serdes_2p5x"),
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
        self.specials += [
            Instance("IDELAYE3",
                p_CASCADE="NONE", p_UPDATE_MODE="ASYNC", p_REFCLK_FREQUENCY=200.0,
                p_IS_CLK_INVERTED=0, p_IS_RST_INVERTED=0,
                # Note: can't use TIME mode since not reloading DELAY_VALUE on rst...
                p_DELAY_FORMAT="COUNT", p_DELAY_SRC="IDATAIN",
                p_DELAY_TYPE="VARIABLE", p_DELAY_VALUE=50, # 1/4 bit period (ambient temp)

                i_CLK=ClockSignal("serdes_2p5x"),
                i_RST=rx_delay_rst, i_LOAD=0,
                i_INC=rx_delay_inc, i_EN_VTC=rx_delay_en_vtc,
                i_CE=rx_delay_ce,

                i_IDATAIN=serdes_m_i_nodelay, o_DATAOUT=serdes_m_i_delayed
            ),
            Instance("ISERDESE3",
                p_DATA_WIDTH=8,

                i_D=serdes_m_i_delayed,
                i_RST=ResetSignal("serdes_2p5x"),
                i_FIFO_RD_CLK=0, i_FIFO_RD_EN=0,
                i_CLK=ClockSignal("serdes_10x"), i_CLK_B=~ClockSignal("serdes_10x"),
                i_CLKDIV=ClockSignal("serdes_2p5x"),
                o_Q=serdes_m_q
            ),
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

                i_CLK=ClockSignal("serdes_2p5x"),
                i_RST=rx_delay_rst, i_LOAD=0,
                i_INC=rx_delay_inc, i_EN_VTC=rx_delay_en_vtc,
                i_CE=rx_delay_ce,

                i_IDATAIN=serdes_s_i_nodelay, o_DATAOUT=serdes_s_i_delayed
            ),
            Instance("ISERDESE3",
                p_DATA_WIDTH=8,

                i_D=serdes_s_i_delayed,
                i_RST=ResetSignal("serdes_2p5x"),
                i_FIFO_RD_CLK=0, i_FIFO_RD_EN=0,
                i_CLK=ClockSignal("serdes_10x"), i_CLK_B=~ClockSignal("serdes_10x"),
                i_CLKDIV=ClockSignal("serdes_2p5x"),
                o_Q=serdes_s_q
            ),
        ]
        self.comb += self.phase_detector.sdata.eq(~serdes_s_q)

        # rx data
        self.comb += [
            self.rx_gearbox.i.eq(serdes_m_q),
            self.rx_bitslip.value.eq(rx_bitslip_value),
            self.rx_bitslip.i.eq(self.rx_gearbox.o),
            self.decoders[0].input.eq(self.rx_bitslip.o[:10]),
            self.decoders[1].input.eq(self.rx_bitslip.o[10:]),
            rx_pattern.eq(self.rx_bitslip.o),
        ]


# master <--> slave synchronization scheme
# 1)  master emits continous 0
# 2)  slave detects 20 zero bits and reset itself (20 zero bits is not possible with 8b10b)
# 3)  master emits sync_pattern
# 4)  slave emits continuous 0, synchronizes to sync_pattern
# 5)  slave emits sync_pattern
# 6)  master synchronize to sync_pattern
# 7)  master stop sending sync_pattern
# 9)  slave detects end of sync_pattern and stops emiting sync_pattern
# 10) link is ready
# 11) TODO: enable phase correction on both side using phase detector

class SERDESInitMaster(Module, AutoCSR):
    def __init__(self, serdes, sync_pattern=0x12345, ndelays=512, nbitslips=20):
        self.reset = CSRStorage()
        self.ready = Signal()
        self.debug = Signal(8)

        # # #

        self.delay = delay = Signal(max=ndelays)
        self.bitslip = bitslip = Signal(max=nbitslips)

        timer = WaitTimer(4096)
        self.submodules += timer

        self.submodules.fsm = fsm = ResetInserter()(FSM(reset_state="IDLE"))
        self.comb += self.fsm.reset.eq(self.reset.storage)

        fsm.act("IDLE",
            self.debug.eq(0),
            NextState("RESET_SLAVE"),
            serdes.tx_pattern_en.eq(1),
            serdes.tx_pattern.eq(0x00000)
        )
        fsm.act("RESET_SLAVE",
            self.debug.eq(1),
            timer.wait.eq(1),
            If(timer.done,
                timer.wait.eq(0),
                NextState("SEND_PATTERN")
            ),
            serdes.tx_pattern_en.eq(1),
            serdes.tx_pattern.eq(0x00000)
        )
        fsm.act("SEND_PATTERN",
            self.debug.eq(2),
            # detect when slave stop sending zeroes
            If(serdes.rx_pattern != 0,
                NextState("WAIT_STABILIZATION")
            ),
            serdes.tx_pattern_en.eq(1),
            serdes.tx_pattern.eq(sync_pattern)
        )
        fsm.act("WAIT_STABILIZATION",
            self.debug.eq(3),
            timer.wait.eq(1),
            If(timer.done,
                timer.wait.eq(0),
                NextState("CHECK_PATTERN")
            ),
            serdes.tx_pattern_en.eq(1),
            serdes.tx_pattern.eq(sync_pattern)
        )
        fsm.act("CHECK_PATTERN",
            self.debug.eq(4),
            If(serdes.rx_pattern == sync_pattern,
                timer.wait.eq(1),
                If(timer.done,
                    NextState("READY")
                )
            ).Else(
                NextState("UPDATE_PARAMS")
            ),
            serdes.tx_pattern_en.eq(1),
            serdes.tx_pattern.eq(sync_pattern),
        )
        self.comb += serdes.rx_bitslip_value.eq(bitslip)
        fsm.act("UPDATE_PARAMS",
            self.debug.eq(5),
            # if last delay tap, increment bitslip
            If(delay == (ndelays - 1),
                If(bitslip == (nbitslips - 1),
                    NextValue(bitslip, 0)
                ).Else(    
                    NextValue(bitslip, bitslip + 1)
                ),
                NextValue(delay, 0),
                serdes.rx_delay_rst.eq(1)
            # increment delay
            ).Else(
                NextValue(delay, delay + 1),
                serdes.rx_delay_inc.eq(1),
                serdes.rx_delay_ce.eq(1)
            ),
            NextState("WAIT_STABILIZATION"),
            serdes.tx_pattern_en.eq(1),
            serdes.tx_pattern.eq(sync_pattern)
        )
       
        fsm.act("READY",
            self.debug.eq(6),
            self.ready.eq(1)
        )
