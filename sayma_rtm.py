#!/usr/bin/env python3
from litex.gen import *

from litex.build.generic_platform import *

from litex.soc.integration.soc_core import *
from litex.soc.integration.builder import *
from litex.soc.cores.uart import UARTWishboneBridge
from litex.soc.cores.spi import SPIMaster

from litex.build.xilinx import XilinxPlatform, VivadoProgrammer

# 10Gbps linerate / 4 lanes / 500Mhz DACCLK / 1x interpolation

# This design targets the sayma rtm and allow AD9154 configuraion over UART

_io = [
    ("clk50", 0, Pins("E15"), IOStandard("LVCMOS25")),
    ("serial", 0,
        Subsignal("tx", Pins("B17")),
        Subsignal("rx", Pins("C16")),
        IOStandard("LVCMOS25")
    ),
]

_rtm_dac1_io = [
    ("dac1_spi", 0,
        Subsignal("clk", Pins("T13")),
        Subsignal("cs_n", Pins("U14")),
        Subsignal("mosi", Pins("V17")),
        Subsignal("miso", Pins("R13")),
        IOStandard("LVCMOS25")
    ),
    ("dac1_txen", 0, Pins("V16"), IOStandard("LVCMOS25")),
    ("dac1_txen", 1, Pins("U16"), IOStandard("LVCMOS25")),
    ("dac1_rst_n", 0, Pins("U15"), IOStandard("LVCMOS25")),
]

class Platform(XilinxPlatform):
    default_clk_name = "clk50"
    default_clk_period = 20.0

    def __init__(self):
        XilinxPlatform.__init__(self, "xc7a15t-csg325-1", _io,
            toolchain="vivado")
        self.add_extension(_rtm_dac1_io)

    def create_programmer(self):
        return VivadoProgrammer()


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


class JESDTXConfigSoC(BaseSoC):
    csr_map = {
        "spi":     20
    }
    csr_map.update(BaseSoC.csr_map)
    def __init__(self, platform):
        BaseSoC.__init__(self, platform)

        # dac1 spi
        spi_pads = platform.request("dac1_spi")
        self.submodules.spi = SPIMaster(spi_pads)

        # dac1 control
        self.comb += [
            platform.request("dac1_txen", 0).eq(1),
            platform.request("dac1_txen", 1).eq(1),
            platform.request("dac1_rst_n").eq(1)
        ]


def main():
    platform = Platform()
    soc = JESDTXConfigSoC(platform)
    builder = Builder(soc, output_dir="build", csr_csv="test/csr.csv")
    vns = builder.build()


if __name__ == "__main__":
    main()
