#!/usr/bin/env python3
import sys
sys.path.append("gateware") # FIXME

from migen import *
from migen.genlib.resetsync import AsyncResetSynchronizer

from migen.build.generic_platform import *
from migen.build.xilinx import XilinxPlatform

from misoc.integration.soc_core import *
from misoc.integration.builder import *
from misoc.interconnect.csr import *
from misoc.interconnect import stream
from misoc.interconnect import wishbone

from amc_rtm_link.phy import RTMSlavePLL, RTMSlaveSerdes, RTMSlaveInit, RTMSlaveControl
from amc_rtm_link import packet
from amc_rtm_link import etherbone


_io = [
    # clock
    ("clk50", 0, Pins("E15"), IOStandard("LVCMOS25")),

    # serial
    ("serial", 0,
        Subsignal("tx", Pins("C16")),
        Subsignal("rx", Pins("B17")),
        IOStandard("LVCMOS25")
    ),

    # amc_rtm_link
    ("amc_rtm_link", 0,
        Subsignal("clk_p", Pins("R18")), # rtm_fpga_usr_io_p
        Subsignal("clk_n", Pins("T18")), # rtm_fpga_usr_io_n
        Subsignal("tx_p", Pins("T17")), # rtm_fpga_lvds2_p
        Subsignal("tx_n", Pins("U17")), # rtm_fpga_lvds2_n
        Subsignal("rx_p", Pins("R16")), # rtm_fpga_lvds1_p
        Subsignal("rx_n", Pins("R17")), # rtm_fpga_lvds1_n
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
        self.reset = Signal()

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
            AsyncResetSynchronizer(self.cd_sys, ~pll_locked | self.reset),
            AsyncResetSynchronizer(self.cd_clk200, ~pll_locked | self.reset)
        ]

        reset_counter = Signal(4, reset=15)
        ic_reset = Signal(reset=1)
        self.sync.clk200 += \
            If(reset_counter != 0,
                reset_counter.eq(reset_counter - 1)
            ).Else(
                ic_reset.eq(0)
            )
        self.specials += Instance("IDELAYCTRL", i_REFCLK=ClockSignal("clk200"), i_RST=ic_reset)


class AMCRTMLinkTestSoC(SoCCore):
    mem_map = {
        "amc_rtm_link": 0x20000000,  # (default shadow @0xa0000000)
    }
    mem_map.update(SoCCore.mem_map)

    def __init__(self, platform):
        clk_freq = int(125e6)
        SoCCore.__init__(self, platform, clk_freq,
            integrated_rom_size=0x8000,
            integrated_sram_size=0x8000,
            ident="Sayma RTM / AMC <--> RTM Link Test Design"
        )
        self.csr_devices += ["amc_rtm_link_control"]

        self.submodules.crg = _CRG(platform)
        self.crg.cd_sys.clk.attr.add("keep")
        platform.add_period_constraint(self.crg.cd_sys.clk, 8.0)

        # amc rtm link
        amc_rtm_link_pll = RTMSlavePLL()
        self.submodules += amc_rtm_link_pll

        amc_rtm_link_pads = platform.request("amc_rtm_link")
        amc_rtm_link_serdes = RTMSlaveSerdes(amc_rtm_link_pll, amc_rtm_link_pads)
        self.submodules.amc_rtm_link_serdes = amc_rtm_link_serdes
        amc_rtm_link_init = RTMSlaveInit(amc_rtm_link_serdes)
        self.submodules.amc_rtm_link_init = amc_rtm_link_init
        self.submodules.amc_rtm_link_control = RTMSlaveControl(amc_rtm_link_init)
        self.comb += self.crg.reset.eq(amc_rtm_link_init.reset)

        amc_rtm_link_serdes.cd_serdes.clk.attr.add("keep")
        amc_rtm_link_serdes.cd_serdes_20x.clk.attr.add("keep")
        amc_rtm_link_serdes.cd_serdes_5x.clk.attr.add("keep")
        platform.add_period_constraint(amc_rtm_link_serdes.cd_serdes.clk, 32.0),
        platform.add_period_constraint(amc_rtm_link_serdes.cd_serdes_20x.clk, 1.6),
        platform.add_period_constraint(amc_rtm_link_serdes.cd_serdes_5x.clk, 6.4)
        self.platform.add_false_path_constraints(
            self.crg.cd_sys.clk,
            amc_rtm_link_serdes.cd_serdes.clk)

        # wishbone master
        amc_rtm_link_core = packet.Core(clk_freq)
        amc_rtm_link_port = amc_rtm_link_core.crossbar.get_port(0x01)
        amc_rtm_link_etherbone = etherbone.Etherbone(mode="master")
        self.submodules += amc_rtm_link_core, amc_rtm_link_etherbone
        amc_rtm_link_tx_cdc = stream.AsyncFIFO([("data", 32)], 8)
        amc_rtm_link_tx_cdc = ClockDomainsRenamer({"write": "sys", "read": "serdes"})(amc_rtm_link_tx_cdc)
        self.submodules += amc_rtm_link_tx_cdc
        amc_rtm_link_rx_cdc = stream.AsyncFIFO([("data", 32)], 8)
        amc_rtm_link_rx_cdc = ClockDomainsRenamer({"write": "serdes", "read": "sys"})(amc_rtm_link_rx_cdc)
        self.submodules += amc_rtm_link_rx_cdc
        self.comb += [
            # core <--> etherbone
            amc_rtm_link_port.source.connect(amc_rtm_link_etherbone.sink),
            amc_rtm_link_etherbone.source.connect(amc_rtm_link_port.sink),
            
            # core --> serdes
            amc_rtm_link_core.source.connect(amc_rtm_link_tx_cdc.sink),
            If(amc_rtm_link_tx_cdc.source.stb & amc_rtm_link_init.ready,
                amc_rtm_link_serdes.encoder.d[0].eq(amc_rtm_link_tx_cdc.source.data[0:8]),
                amc_rtm_link_serdes.encoder.d[1].eq(amc_rtm_link_tx_cdc.source.data[8:16]),
                amc_rtm_link_serdes.encoder.d[2].eq(amc_rtm_link_tx_cdc.source.data[16:24]),
                amc_rtm_link_serdes.encoder.d[3].eq(amc_rtm_link_tx_cdc.source.data[24:32])
            ),
            amc_rtm_link_tx_cdc.source.ack.eq(amc_rtm_link_init.ready),

            # serdes --> core
            amc_rtm_link_rx_cdc.sink.stb.eq(amc_rtm_link_init.ready),
            amc_rtm_link_rx_cdc.sink.data[0:8].eq(amc_rtm_link_serdes.decoders[0].d),
            amc_rtm_link_rx_cdc.sink.data[8:16].eq(amc_rtm_link_serdes.decoders[1].d),
            amc_rtm_link_rx_cdc.sink.data[16:24].eq(amc_rtm_link_serdes.decoders[2].d),
            amc_rtm_link_rx_cdc.sink.data[24:32].eq(amc_rtm_link_serdes.decoders[3].d),
            amc_rtm_link_rx_cdc.source.connect(amc_rtm_link_core.sink),
        ]
        self.add_wb_master(amc_rtm_link_etherbone.wishbone.bus)

        # wishbone test memory
        self.submodules.amc_rtm_link_sram = wishbone.SRAM(8192)
        self.register_mem("amc_rtm_link_sram", self.mem_map["amc_rtm_link"], self.amc_rtm_link_sram.bus, 8192)


def main():
    platform = Platform()
    if len(sys.argv) < 2:
        print("missing target (amc_rtm_link)")
        exit()
    if sys.argv[1] == "amc_rtm_link":
        soc = AMCRTMLinkTestSoC(platform)
    builder = Builder(soc, output_dir="build_sayma_rtm")
    vns = builder.build()


if __name__ == "__main__":
    main()
