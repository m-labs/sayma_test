#!/usr/bin/env python3
import sys
sys.path.append("gateware") # FIXME

from litex.gen import *

from litex.build.generic_platform import *

from litex.soc.integration.soc_core import *
from litex.soc.integration.builder import *
from litex.soc.cores.uart import UARTWishboneBridge
from litex.soc.cores.spi import SPIMaster

from litex.build.xilinx import XilinxPlatform


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
]


class Platform(XilinxPlatform):
    default_clk_name = "clk50"
    default_clk_period = 20.0

    def __init__(self):
        XilinxPlatform.__init__(self, "xc7a15t-csg325-1", _io,
            toolchain="vivado")


class BaseSoC(SoCCore):
    def __init__(self, platform):
        clk_freq = int(1e9/platform.default_clk_period)
        SoCCore.__init__(self, platform, clk_freq,
            cpu_type=None,
            csr_data_width=32,
            with_uart=False,
            ident="LiteJESD204B AD9154 Example Design",
            with_timer=False
        )
        self.submodules.crg = CRG(platform.request(platform.default_clk_name))

        # uart <--> wishbone
        self.add_cpu_or_bridge(UARTWishboneBridge(platform.request("serial"),
                                                  clk_freq, baudrate=115200))
        self.add_wb_master(self.cpu_or_bridge.wishbone)


class JESDTestSoC(BaseSoC):
    csr_map = {
        "spi":     20
    }
    csr_map.update(BaseSoC.csr_map)
    def __init__(self, platform, dac=0):
        BaseSoC.__init__(self, platform)

        # dac spi
        spi_pads = platform.request("dac_spi", dac)
        self.submodules.spi = SPIMaster(spi_pads)

        # dac control
        self.comb += [
            platform.request("dac_txen", dac).eq(1),
            platform.request("dac_rst_n", dac).eq(1)
        ]


def main():
    platform = Platform()
    soc = JESDTestSoC(platform)
    builder = Builder(soc, output_dir="build_sayma_rtm", csr_csv="test/csr.csv")
    vns = builder.build()


if __name__ == "__main__":
    main()
