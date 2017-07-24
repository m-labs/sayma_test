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
from litex.soc.interconnect import stream
from litex.soc.interconnect import wishbone

from amc_rtm_link.phy import RTMSlavePLL, RTMSlaveSerdes, RTMSlaveInit
from amc_rtm_link import packet
from amc_rtm_link import etherbone

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
        Subsignal("rx_p", Pins("R16")), # rtm_fpga_lvds1_p
        Subsignal("rx_n", Pins("R17")), # rtm_fpga_lvds1_n
        Subsignal("tx_p", Pins("T17")), # rtm_fpga_lvds2_p
        Subsignal("tx_n", Pins("U17")), # rtm_fpga_lvds2_n
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
        self.specials += Instance("IDELAYCTRL", i_REFCLK=ClockSignal("clk200"), i_RST=ic_reset)


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
        "amc_rtm_link_init": 20,
        "analyzer":          30
    }
    csr_map.update(SoCCore.csr_map)

    mem_map = {
        "amc_rtm_link_sram": 0x20000000,  # (default shadow @0xa0000000)
    }
    mem_map.update(SoCCore.mem_map)

    def __init__(self, platform):
        clk_freq = int(125e6)
        SoCCore.__init__(self, platform, clk_freq,
            cpu_type=None,
            csr_data_width=32,
            with_uart=False,
            ident="Sayma RTM / AMC <--> RTM Link Test Design",
            with_timer=False
        )
        self.submodules.crg = _CRG(platform)

        # uart <--> wishbone
        self.add_cpu_or_bridge(UARTWishboneBridge(platform.request("serial"),
                                                  clk_freq, baudrate=115200))
        self.add_wb_master(self.cpu_or_bridge.wishbone)

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

        amc_rtm_link_serdes.cd_serdes.clk.attr.add("keep")
        amc_rtm_link_serdes.cd_serdes_20x.clk.attr.add("keep")
        amc_rtm_link_serdes.cd_serdes_5x.clk.attr.add("keep")
        platform.add_period_constraint(amc_rtm_link_serdes.cd_serdes.clk, 32.0),
        platform.add_period_constraint(amc_rtm_link_serdes.cd_serdes_20x.clk, 1.6),
        platform.add_period_constraint(amc_rtm_link_serdes.cd_serdes_5x.clk, 6.4)
        self.platform.add_false_path_constraints(
            self.crg.cd_sys.clk,
            amc_rtm_link_serdes.cd_serdes.clk,
            amc_rtm_link_serdes.cd_serdes_20x.clk,
            amc_rtm_link_serdes.cd_serdes_5x.clk)


        # wishbone master
        amc_rtm_link_core = packet.Core(clk_freq)
        amc_rtm_link_port = amc_rtm_link_core.crossbar.get_port(0x01)
        amc_rtm_link_etherbone = etherbone.Etherbone(mode="master")
        self.submodules += amc_rtm_link_core, amc_rtm_link_etherbone
        amc_rtm_link_m2s_cdc = stream.AsyncFIFO([("data", 32)], 4)
        amc_rtm_link_m2s_cdc = ClockDomainsRenamer({"write": "sys", "read": "serdes"})(amc_rtm_link_m2s_cdc)
        self.submodules += amc_rtm_link_m2s_cdc
        amc_rtm_link_s2m_cdc = stream.AsyncFIFO([("data", 32)], 4)
        amc_rtm_link_s2m_cdc = ClockDomainsRenamer({"write": "serdes", "read": "sys"})(amc_rtm_link_s2m_cdc)
        self.submodules += amc_rtm_link_s2m_cdc
        self.comb += [
            # core <--> etherbone
            amc_rtm_link_port.source.connect(amc_rtm_link_etherbone.sink),
            amc_rtm_link_etherbone.source.connect(amc_rtm_link_port.sink),
            
            # core --> serdes
            amc_rtm_link_core.source.connect(amc_rtm_link_m2s_cdc.sink),
            If(amc_rtm_link_m2s_cdc.source.valid & amc_rtm_link_init.ready,
                amc_rtm_link_serdes.encoder.d[0].eq(amc_rtm_link_m2s_cdc.source.data[0:8]),
                amc_rtm_link_serdes.encoder.d[1].eq(amc_rtm_link_m2s_cdc.source.data[8:16]),
                amc_rtm_link_serdes.encoder.d[2].eq(amc_rtm_link_m2s_cdc.source.data[16:24]),
                amc_rtm_link_serdes.encoder.d[3].eq(amc_rtm_link_m2s_cdc.source.data[24:32]),
            ),
            amc_rtm_link_m2s_cdc.source.ready.eq(amc_rtm_link_init.ready),

            # serdes --> core
            amc_rtm_link_s2m_cdc.sink.valid.eq(amc_rtm_link_init.ready),
            amc_rtm_link_s2m_cdc.sink.data[0:8].eq(amc_rtm_link_serdes.decoders[0].d),
            amc_rtm_link_s2m_cdc.sink.data[8:16].eq(amc_rtm_link_serdes.decoders[1].d),
            amc_rtm_link_s2m_cdc.sink.data[16:24].eq(amc_rtm_link_serdes.decoders[2].d),
            amc_rtm_link_s2m_cdc.sink.data[24:32].eq(amc_rtm_link_serdes.decoders[3].d),
            amc_rtm_link_s2m_cdc.source.connect(amc_rtm_link_core.sink),
        ]
        self.add_wb_master(amc_rtm_link_etherbone.wishbone.bus)

        # wishbone test memory
        self.submodules.amc_rtm_link_sram = wishbone.SRAM(8192)
        self.register_mem("amc_rtm_link_sram", self.mem_map["amc_rtm_link_sram"], self.amc_rtm_link_sram.bus, 8192)


        # analyzer
        wishbone_access = Signal()
        self.comb += wishbone_access.eq((amc_rtm_link_serdes.decoders[0].d == 0xa5) |
                                        (amc_rtm_link_serdes.decoders[1].d == 0x5a))
        init_group = [
            amc_rtm_link_init.debug,
            amc_rtm_link_init.ready,
            amc_rtm_link_init.delay,
            amc_rtm_link_init.bitslip,
            amc_rtm_link_init.delay_min,
            amc_rtm_link_init.delay_min_found,
            amc_rtm_link_init.delay_max,
            amc_rtm_link_init.delay_max_found
        ]
        serdes_group = [
            wishbone_access,
            amc_rtm_link_serdes.encoder.k[0],
            amc_rtm_link_serdes.encoder.d[0],
            amc_rtm_link_serdes.encoder.k[1],
            amc_rtm_link_serdes.encoder.d[1],
            amc_rtm_link_serdes.encoder.k[2],
            amc_rtm_link_serdes.encoder.d[2],
            amc_rtm_link_serdes.encoder.k[3],
            amc_rtm_link_serdes.encoder.d[3],

            amc_rtm_link_serdes.decoders[0].d,
            amc_rtm_link_serdes.decoders[0].k,
            amc_rtm_link_serdes.decoders[1].d,
            amc_rtm_link_serdes.decoders[1].k,
            amc_rtm_link_serdes.decoders[2].d,
            amc_rtm_link_serdes.decoders[2].k,
            amc_rtm_link_serdes.decoders[3].d,
            amc_rtm_link_serdes.decoders[3].k,
        ]
        etherbone_source_group = [
            wishbone_access,
            amc_rtm_link_etherbone.wishbone.source
        ]
        etherbone_sink_group = [
            wishbone_access,
            amc_rtm_link_etherbone.wishbone.sink
        ]
        wishbone_group = [
            wishbone_access,
            amc_rtm_link_etherbone.wishbone.bus
        ]
        analyzer_signals = {
            0 : init_group,
            1 : serdes_group,
            2 : etherbone_source_group,
            3 : etherbone_sink_group,
            4 : wishbone_group
        }
        self.submodules.analyzer = LiteScopeAnalyzer(analyzer_signals, 128, cd="sys")

    def do_exit(self, vns):
        if hasattr(self, "analyzer"):
            self.analyzer.export_csv(vns, "test/sayma_rtm/analyzer.csv")


def main():
    platform = Platform()
    compile_gateware = True
    if len(sys.argv) < 2:
        print("missing target (jesd or amc_rtm_link)")
        exit()
    if sys.argv[1] == "jesd":
        soc = JESDTestSoC(platform)
    elif sys.argv[1] == "amc_rtm_link":
        soc = AMCRTMLinkTestSoC(platform)
    builder = Builder(soc, output_dir="build_sayma_rtm", csr_csv="test/sayma_rtm/csr.csv",
        compile_gateware=compile_gateware)
    vns = builder.build()
    soc.do_exit(vns)


if __name__ == "__main__":
    main()
