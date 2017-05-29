#!/usr/bin/env python3

import argparse

from litex.gen import *

from litex.build.generic_platform import *

from litex.soc.integration.soc_core import *
from litex.soc.integration.builder import *
from litex.soc.cores.uart import UARTWishboneBridge
from litex.soc.cores.spi import SPIMaster

from litex.boards.platforms import kcu105

from litejesd204b.common import *
from litejesd204b.phy.gth import GTHQuadPLL
from litejesd204b.phy import LiteJESD204BPhyTX
from litejesd204b.core import LiteJESD204BCoreTX
from litejesd204b.core import LiteJESD204BCoreTXControl

from litex.build.xilinx import XilinxPlatform, VivadoProgrammer

# 10Gbps linerate / 4 lanes / 500Mhz DACCLK / 1x interpolation

# This design targets the sayma amc and expect the rtm to:
# - generate a 250MHz GTH reference clock on REFCLK224
# - generate a 500MHz DACCLK to DAC1
# - generate a 15.625MHz SYSREF to DAC1
# - configure the DAC1 (AD9154)

# The design can then be controlled over UART to:
# - enable/disable JESD TX pattern generation (wb.regs.control_enable.write())
# - enable/disable JESD STPL test (wb.regs.control_stpl_enable.write())
# - enable/disable JESD PRBS test (wb.regs.control_prbs_config.write())

_io = [
    ("clk50", 0, Pins("AF9"), IOStandard("LVCMOS18")),
    ("serial", 0,
        Subsignal("tx", Pins("AK8")),
        Subsignal("rx", Pins("AL8")),
        IOStandard("LVCMOS18")
    ),
]

_rtm_dac1_io = [
    ("dac1_enable", 0, Pins("X")),
    ("dac1_ready", 0,  Pins("X")),
    ("dac1_prbs_config", 0, Pins("X X X X")),
    ("dac1_stpl_enable", 0, Pins("X")),

    ("dac1_refclk", 0,
        Subsignal("p", Pins("K6")),
        Subsignal("n", Pins("K5")),
    ),
    ("dac1_sysref", 0,
        Subsignal("p", Pins("B10")),
        Subsignal("n", Pins("A10")),
        IOStandard("LVDS")
    ),
    ("dac1_sync", 0,
        Subsignal("p", Pins("L8")),
        Subsignal("n", Pins("H9")),
        IOStandard("LVDS")
    ),
    ("dac1_jesd", 0,
        Subsignal("txp", Pins("B6 C4 D6 F6 G4 J4 L4 N4")),
        Subsignal("txn", Pins("B5 C3 D5 F5 G3 J3 L3 N3"))
    ),
]


# TODO: remove this when adding multi-lane support
def get_phy_pads(jesd_pads, n):
    class PHYPads:
        def __init__(self, txp, txn):
            self.txp = txp
            self.txn = txn
    return PHYPads(jesd_pads.txp[n], jesd_pads.txn[n])


class Platform(XilinxPlatform):
    default_clk_name = "clk50"
    default_clk_period = 20.0

    def __init__(self):
        XilinxPlatform.__init__(self, "xcku040-ffva1156-1-c", _io,
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


class JESDTXSoC(BaseSoC):
    csr_map = {
        "spi":     20,
        "control": 21,
        "analyzer": 22
    }
    csr_map.update(BaseSoC.csr_map)
    def __init__(self, platform, uart_control=False):
        BaseSoC.__init__(self, platform)

        # jesd
        ps = JESD204BPhysicalSettings(l=4, m=4, n=16, np=16)
        ts = JESD204BTransportSettings(f=2, s=1, k=16, cs=1)
        settings = JESD204BSettings(ps, ts, did=0x5a, bid=0x5)
        linerate = 10e9
        refclk_freq = 250e6

        self.clock_domains.cd_jesd = ClockDomain()
        refclk_pads = platform.request("dac1_refclk")

        self.refclk = Signal()
        refclk_to_bufg_gt = Signal()
        self.specials += [
            Instance("IBUFDS_GTE3", i_CEB=0,
                     p_REFCLK_HROW_CK_SEL=0b00,
                     i_I=refclk_pads.p, i_IB=refclk_pads.n,
                     o_O=self.refclk, o_ODIV2=refclk_to_bufg_gt),
            Instance("BUFG_GT", i_I=refclk_to_bufg_gt, o_O=self.cd_jesd.clk)
        ]
        platform.add_period_constraint(self.cd_jesd.clk, 1e9/refclk_freq)


        jesd_pads = platform.request("dac1_jesd")
        phys = []
        for i in range(len(jesd_pads.txp)):
            if i%4 == 0:
                qpll = GTHQuadPLL(self.refclk, refclk_freq, linerate)
                self.submodules += qpll
                print(qpll)

            phy = LiteJESD204BPhyTX(
                qpll, get_phy_pads(jesd_pads, i), self.clk_freq,
                transceiver="gth")
            #self.comb += phy.transmitter.produce_square_wave.eq(1)
            platform.add_period_constraint(phy.transmitter.cd_tx.clk, 40*1e9/linerate)
            platform.add_false_path_constraints(
                self.cd_jesd.clk,
                phy.transmitter.cd_tx.clk)
            phys.append(phy)
        to_jesd = ClockDomainsRenamer("jesd")
        self.submodules.core = to_jesd(LiteJESD204BCoreTX(phys, settings,
                                                      converter_data_width=32))
        if uart_control:
            self.submodules.control = to_jesd(LiteJESD204BCoreTXControl(self.core))
        else:
            self.comb += [
                self.core.enable.eq(platform.request("dac1_enable")),
                platform.request("dac1_ready").eq(self.core.ready),
                self.core.prbs_config.eq(platform.request("dac1_prbs_config")),
                self.core.stpl_enable.eq(platform.request("dac1_stpl_enable")),
            ]
        self.core.register_jsync(platform.request("dac1_sync"))

        # jesd pattern (ramp)
        data0 = Signal(16)
        data1 = Signal(16)
        data2 = Signal(16)
        data3 = Signal(16)
        self.sync.jesd += [
            data0.eq(data0 + 4096),   # freq = dacclk/32
            data1.eq(data1 + 8192),   # freq = dacclk/16
            data2.eq(data2 + 16384),  # freq = dacclk/8
            data3.eq(data3 + 32768)   # freq = dacclk/4
        ]
        self.comb += [
            self.core.sink.converter0.eq(Cat(data0, data0)),
            self.core.sink.converter1.eq(Cat(data1, data1)),
            self.core.sink.converter2.eq(Cat(data2, data2)),
            self.core.sink.converter3.eq(Cat(data3, data3))
        ]


def main():
    platform = Platform()
    soc = JESDTXSoC(platform)
    builder = Builder(soc, output_dir="build", csr_csv="test/csr.csv")
    vns = builder.build()


if __name__ == "__main__":
    main()
