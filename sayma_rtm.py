#!/usr/bin/env python3
import sys
sys.path.append("gateware") # FIXME

from litex.gen import *
from litex.soc.interconnect.csr import *
from litex.gen.genlib.resetsync import AsyncResetSynchronizer

from litex.build.generic_platform import *
from litex.build.xilinx import XilinxPlatform

from litex.soc.integration.soc_core import *
from litex.soc.integration.builder import *
from litex.soc.cores.uart import UARTWishboneBridge
from litex.soc.cores.spi import SPIMaster

from transceiver.serdes_7series import SERDESPLL, SERDES

from litescope import LiteScopeAnalyzer


_io = [
    # clock
    ("clk50", 0, Pins("E15"), IOStandard("LVCMOS25")),

    # serial
    ("serial", 0,
        Subsignal("tx", Pins("C16")),
        Subsignal("rx", Pins("B17")),
        IOStandard("LVCMOS25")
    ),

    # dac
    ("dac_spi", 0,
        Subsignal("clk", Pins("T13")),
        Subsignal("cs_n", Pins("U14")),
        Subsignal("mosi", Pins("V17")),
        Subsignal("miso", Pins("R13")),
        IOStandard("LVCMOS25")
    ),
    ("dac_txen", 0, Pins("V16"), IOStandard("LVCMOS25")),
    ("dac_txen", 1, Pins("U16"), IOStandard("LVCMOS25")),
    ("dac_rst_n", 0, Pins("U15"), IOStandard("LVCMOS25")),

    # amc_rtm_link
    ("amc_rtm_link", 0,
        Subsignal("clk_p", Pins("R18")), # rtm_fpga_usr_io_p
        Subsignal("clk_n", Pins("T18")), # rtm_fpga_usr_io_n
        Subsignal("tx_p", Pins("R16")), # rtm_fpga_lvds1_p
        Subsignal("tx_n", Pins("R17")), # rtm_fpga_lvds1_n
        Subsignal("rx_p", Pins("T17")), # rtm_fpga_lvds2_p
        Subsignal("rx_n", Pins("U17")), # rtm_fpga_lvds2_n
        IOStandard("LVDS_25")
    ),
]


class Platform(XilinxPlatform):
    default_clk_name = "clk50"
    default_clk_period = 20.0

    def __init__(self):
        XilinxPlatform.__init__(self, "xc7a15t-csg325-1", _io,
            toolchain="vivado")


class _CRG(Module):
    def __init__(self, platform):
        self.clock_domains.cd_sys = ClockDomain()
        self.clock_domains.cd_clk200 = ClockDomain()

        clk50 = platform.request("clk50")

        pll_locked = Signal()
        pll_fb = Signal()
        pll_sys = Signal()
        pll_clk200 = Signal()
        self.specials += [
            Instance("PLLE2_BASE",
                     p_STARTUP_WAIT="FALSE", o_LOCKED=pll_locked,

                     # VCO @ 1GHz
                     p_REF_JITTER1=0.01, p_CLKIN1_PERIOD=20.0,
                     p_CLKFBOUT_MULT=20, p_DIVCLK_DIVIDE=1,
                     i_CLKIN1=clk50, i_CLKFBIN=pll_fb, o_CLKFBOUT=pll_fb,

                     # 125MHz
                     p_CLKOUT0_DIVIDE=8, p_CLKOUT0_PHASE=0.0, o_CLKOUT0=pll_sys,

                     # 200MHz
                     p_CLKOUT3_DIVIDE=5, p_CLKOUT3_PHASE=0.0, o_CLKOUT3=pll_clk200
            ),
            Instance("BUFG", i_I=pll_sys, o_O=self.cd_sys.clk),
            Instance("BUFG", i_I=pll_clk200, o_O=self.cd_clk200.clk),
            AsyncResetSynchronizer(self.cd_sys, ~pll_locked),
            AsyncResetSynchronizer(self.cd_clk200, ~pll_locked),
        ]

        reset_counter = Signal(4, reset=15)
        ic_reset = Signal(reset=1)
        self.sync.clk200 += \
            If(reset_counter != 0,
                reset_counter.eq(reset_counter - 1)
            ).Else(
                ic_reset.eq(0)
            )
        self.specials += Instance("IDELAYCTRL", p_SIM_DEVICE="ULTRASCALE",
            i_REFCLK=ClockSignal("clk200"), i_RST=ic_reset)


class JESDTestSoC(SoCCore):
    csr_map = {
        "spi":     20
    }
    csr_map.update(SoCCore.csr_map)
    def __init__(self, platform, dac=0):
        clk_freq = int(1e9/platform.default_clk_period)
        SoCCore.__init__(self, platform, clk_freq,
            cpu_type=None,
            csr_data_width=32,
            with_uart=False,
            ident="Sayma AMC JESD Test Design",
            with_timer=False
        )
        self.submodules.crg = CRG(platform.request(platform.default_clk_name))

        # uart <--> wishbone
        self.add_cpu_or_bridge(UARTWishboneBridge(platform.request("serial"),
                                                  clk_freq, baudrate=115200))
        self.add_wb_master(self.cpu_or_bridge.wishbone)

        # dac spi
        spi_pads = platform.request("dac_spi", dac)
        self.submodules.spi = SPIMaster(spi_pads)

        # dac control
        self.comb += [
            platform.request("dac_txen", dac).eq(1),
            platform.request("dac_rst_n", dac).eq(1)
        ]


class AMCRTMLinkTestSoC(SoCCore):
    csr_map = {
        "slave_serdes": 21,
        "analyzer": 22
    }
    csr_map.update(SoCCore.csr_map)
    def __init__(self, platform, dac=0):
        clk_freq = int(1e9/platform.default_clk_period)
        SoCCore.__init__(self, platform, clk_freq,
            cpu_type=None,
            csr_data_width=32,
            with_uart=False,
            ident="Sayma AMC RTM Link Test Design",
            with_timer=False
        )
        self.submodules.crg = _CRG(platform)

        # uart <--> wishbone
        self.add_cpu_or_bridge(UARTWishboneBridge(platform.request("serial"),
                                                  clk_freq, baudrate=115200))
        self.add_wb_master(self.cpu_or_bridge.wishbone)

        self.crg.cd_sys.clk.attr.add("keep")
        platform.add_period_constraint(self.crg.cd_sys.clk, 10.0)

        # slave
        slave_pll = SERDESPLL(125e6, 1.25e9)
        self.submodules += slave_pll

        slave_pads = platform.request("amc_rtm_link")
        self.submodules.slave_serdes = slave_serdes = SERDES(
            slave_pll, slave_pads, mode="slave")

        slave_serdes.cd_serdes.clk.attr.add("keep")
        slave_serdes.cd_serdes_10x.clk.attr.add("keep")
        slave_serdes.cd_serdes_2p5x.clk.attr.add("keep")
        platform.add_period_constraint(slave_serdes.cd_serdes.clk, 16.0),
        platform.add_period_constraint(slave_serdes.cd_serdes_10x.clk, 1.6),
        platform.add_period_constraint(slave_serdes.cd_serdes_2p5x.clk, 6.4)
        self.platform.add_false_path_constraints(
            self.crg.cd_sys.clk,
            slave_serdes.cd_serdes.clk,
            slave_serdes.cd_serdes_10x.clk,
            slave_serdes.cd_serdes_2p5x.clk)

        counter = Signal(32)
        self.sync.serdes += counter.eq(counter + 1)
        self.comb += [
            slave_serdes.encoder.d[0].eq(counter),
            slave_serdes.encoder.d[1].eq(counter)
        ]

        analyzer_signals = [
            slave_serdes.encoder.k[0],
            slave_serdes.encoder.d[0],
            slave_serdes.encoder.output[0],
            slave_serdes.encoder.k[1],
            slave_serdes.encoder.d[1],
            slave_serdes.encoder.output[1],

            slave_serdes.decoders[0].input,
            slave_serdes.decoders[0].d,
            slave_serdes.decoders[0].k,
            slave_serdes.decoders[1].input,
            slave_serdes.decoders[1].d,
            slave_serdes.decoders[1].k,
        ]
        self.submodules.analyzer = LiteScopeAnalyzer(analyzer_signals, 512, cd="serdes")

    def do_exit(self, vns):
        if hasattr(self, "analyzer"):
            self.analyzer.export_csv(vns, "test/analyzer.csv")


def main():
    platform = Platform()
    if len(sys.argv) < 2:
        print("missing target (jesd or amc_rtm_link)")
        exit()
    if sys.argv[1] == "jesd":
        soc = JESDTestSoC(platform)
    elif sys.argv[1] == "amc_rtm_link":
        soc = AMCRTMLinkTestSoC(platform)
    builder = Builder(soc, output_dir="build_sayma_rtm", csr_csv="test/csr.csv")
    vns = builder.build()


if __name__ == "__main__":
    main()
