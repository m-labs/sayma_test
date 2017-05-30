#!/usr/bin/env python3
import sys
sys.path.append("gateware") # FIXME

from litex.gen import *
from litex.soc.interconnect.csr import *

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
        Subsignal("tx", Pins("B17")),
        Subsignal("rx", Pins("C16")),
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
        Subsignal("clk_p", Pins("FIXME"), Misc("DIFF_TERM=TRUE")),
        Subsignal("clk_n", Pins("FIXME"), Misc("DIFF_TERM=TRUE")),
        Subsignal("tx_p", Pins("FIXME"), Misc("DIFF_TERM=TRUE")),
        Subsignal("tx_n", Pins("FIXME"), Misc("DIFF_TERM=TRUE")),
        Subsignal("rx_p", Pins("FIXME"), Misc("DIFF_TERM=TRUE")),
        Subsignal("rx_n", Pins("FIXME"), Misc("DIFF_TERM=TRUE")),
        IOStandard("LVDS_25"),
    ),
]


class Platform(XilinxPlatform):
    default_clk_name = "clk50"
    default_clk_period = 20.0

    def __init__(self):
        XilinxPlatform.__init__(self, "xc7a15t-csg325-1", _io,
            toolchain="vivado")


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
        self.submodules.crg = CRG(platform.request(platform.default_clk_name))

        # uart <--> wishbone
        self.add_cpu_or_bridge(UARTWishboneBridge(platform.request("serial"),
                                                  clk_freq, baudrate=115200))
        self.add_wb_master(self.cpu_or_bridge.wishbone)

        self.crg.cd_sys.clk.attr.add("keep")
        platform.add_period_constraint(self.crg.cd_sys.clk, 10.0)

        # slave

        slave_pll = SERDESPLL(125e6, 1.25e9)
        self.comb += slave_pll.refclk.eq(ClockSignal()) # FIXME (generate 125MHz clock)
        self.submodules += slave_pll

        slave_pads = platform.request("amc_rtm_link", 0)
        self.submodules.slave_serdes = slave_serdes = SERDES(
            slave_pll, slave_pads, mode="slave")

        slave_serdes.cd_rtio.clk.attr.add("keep")
        slave_serdes.cd_serdes.clk.attr.add("keep")
        slave_serdes.cd_serdes_div.clk.attr.add("keep")
        platform.add_period_constraint(slave_serdes.cd_rtio.clk, 16.0),
        platform.add_period_constraint(slave_serdes.cd_serdes.clk, 1.6),
        platform.add_period_constraint(slave_serdes.cd_serdes_div.clk, 6.4)
        self.platform.add_false_path_constraints(
            self.crg.cd_sys.clk,
            slave_serdes.cd_rtio.clk,
            slave_serdes.cd_serdes.clk,
            slave_serdes.cd_serdes_div.clk)

        counter = Signal(32)
        self.sync.rtio += counter.eq(counter + 1)
        self.comb += [
            slave_serdes.encoder.d[0].eq(counter),
            slave_serdes.encoder.d[1].eq(counter)
        ]

        slave_sys_counter = Signal(32)
        self.sync.sys += slave_sys_counter.eq(slave_sys_counter + 1)
        #self.comb += platform.request("user_led", 4).eq(slave_sys_counter[26]) # FIXME

        slave_rtio_counter = Signal(32)
        self.sync.rtio += slave_rtio_counter.eq(slave_rtio_counter + 1)
        #self.comb += platform.request("user_led", 5).eq(slave_rtio_counter[26]) # FIXME

        slave_serdes_div_counter = Signal(32)
        self.sync.serdes_div += slave_serdes_div_counter.eq(slave_serdes_div_counter + 1)
        #self.comb += platform.request("user_led", 6).eq(slave_serdes_div_counter[26]) # FIXME

        slave_serdes_counter = Signal(32)
        self.sync.serdes += slave_serdes_counter.eq(slave_serdes_counter + 1)
        #self.comb += platform.request("user_led", 7).eq(slave_serdes_counter[26]) # FIXME

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
        self.submodules.analyzer = LiteScopeAnalyzer(analyzer_signals, 512, cd="rtio")

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
