#!/usr/bin/env python3
import sys
sys.path.append("gateware") # FIXME

from migen import *
from migen.genlib.resetsync import AsyncResetSynchronizer
from migen.build.generic_platform import *
from migen.build.xilinx import XilinxPlatform

from misoc.cores.sdram_settings import MT41J256M16
from misoc.cores.sdram_phy import kusddrphy
from misoc.integration.soc_core import *
from misoc.integration.soc_sdram import *
from misoc.integration.builder import *
from misoc.interconnect.csr import *
from misoc.interconnect import stream

from drtio.gth_ultrascale import GTHChannelPLL, GTHQuadPLL, MultiGTH

from amc_rtm_link.kusphy import KUSSerdesPLL, KUSSerdes
from amc_rtm_link.phy import SerdesMasterInit, SerdesControl
from amc_rtm_link import packet
from amc_rtm_link import etherbone

from gateware import firmware

_io = [
    # clock
    ("clk50", 0, Pins("AF9"), IOStandard("LVCMOS18")),

    # leds
    ("user_led", 0, Pins("AG9"), IOStandard("LVCMOS18")),
    ("user_led", 1, Pins("AJ10"), IOStandard("LVCMOS18")),
    ("user_led", 2, Pins("AJ13"), IOStandard("LVCMOS18")),
    ("user_led", 3, Pins("AE13"), IOStandard("LVCMOS18")),

    # serial
    ("serial", 0,
        Subsignal("tx", Pins("AK8")),
        Subsignal("rx", Pins("AL8")),
        IOStandard("LVCMOS18")
    ),
    ("serial", 1,
        Subsignal("tx", Pins("M27")),
        Subsignal("rx", Pins("L27")),
        IOStandard("LVCMOS18")
    ),

    ("usr_uart_p", 1, Pins("H27"), IOStandard("LVCMOS18")),
    ("usr_uart_n", 1, Pins("G27"), IOStandard("LVCMOS18")),

    # sdram
    ("ddram_64", 0,
        Subsignal("a", Pins(
            "AE17 AL17 AG16 AG17 AD16 AH14 AD15 AK15",
            "AF14 AF15 AL18 AL15 AE18 AJ15 AG14"),
            IOStandard("SSTL15")),
        Subsignal("ba", Pins("AF17 AD19 AD18"), IOStandard("SSTL15")),
        Subsignal("ras_n", Pins("AH19"), IOStandard("SSTL15")),
        Subsignal("cas_n", Pins("AK18"), IOStandard("SSTL15")),
        Subsignal("we_n", Pins("AG19"), IOStandard("SSTL15")),
        Subsignal("cs_n", Pins("AF18"), IOStandard("SSTL15")),
        Subsignal("dm", Pins("AD21 AE25 AJ21 AM21 AH26 AN26 AJ29 AL32"),
            IOStandard("SSTL15"),
            Misc("DATA_RATE=DDR")),
        Subsignal("dq", Pins(
            "AE23 AG20 AF22 AF20 AE22 AD20 AG22 AE20",
            "AJ24 AG24 AJ23 AF23 AH23 AF24 AH22 AG25",
            "AL22 AL25 AM20 AK23 AK22 AL24 AL20 AL23",
            "AM24 AN23 AN24 AP23 AP25 AN22 AP24 AM22",
            "AH28 AK26 AK28 AM27 AJ28 AH27 AK27 AM26",
            "AL30 AP29 AM30 AN28 AL29 AP28 AM29 AN27",
            "AH31 AH32 AJ34 AK31 AJ31 AJ30 AH34 AK32",
            "AN33 AP33 AM34 AP31 AM32 AN31 AL34 AN32"),
            IOStandard("SSTL15_DCI"),
            Misc("ODT=RTT_40"),
            Misc("DATA_RATE=DDR")),
        Subsignal("dqs_p", Pins("AG21 AH24 AJ20 AP20 AL27 AN29 AH33 AN34"),
            IOStandard("DIFF_SSTL15"),
            Misc("DATA_RATE=DDR")),
        Subsignal("dqs_n", Pins("AH21 AJ25 AK20 AP21 AL28 AP30 AJ33 AP34"),
            IOStandard("DIFF_SSTL15"),
            Misc("DATA_RATE=DDR")),
        Subsignal("clk_p", Pins("AE16"), IOStandard("DIFF_SSTL15"), Misc("DATA_RATE=DDR")),
        Subsignal("clk_n", Pins("AE15"), IOStandard("DIFF_SSTL15"), Misc("DATA_RATE=DDR")),
        Subsignal("cke", Pins("AL19"), IOStandard("SSTL15")),
        Subsignal("odt", Pins("AJ18"), IOStandard("SSTL15")),
        Subsignal("reset_n", Pins("AJ14"), IOStandard("LVCMOS15")),
        Misc("SLEW=FAST"),
    ),

    ("ddram_32", 1,
        Subsignal("a", Pins(
            "E15 D15 J16 K18 H16 K17 K16 J15",
            "K15 D14 D18 G15 L18 G14 L15"),
            IOStandard("SSTL15")),
        Subsignal("ba", Pins("L19 H17 G16"), IOStandard("SSTL15")),
        Subsignal("ras_n", Pins("E18"), IOStandard("SSTL15")),
        Subsignal("cas_n", Pins("E16"), IOStandard("SSTL15")),
        Subsignal("we_n", Pins("D16"), IOStandard("SSTL15")),
        Subsignal("cs_n", Pins("G19"), IOStandard("SSTL15")),
        Subsignal("dm", Pins("F27 E26 D23 G24"),
            IOStandard("SSTL15"),
            Misc("DATA_RATE=DDR")),
        Subsignal("dq", Pins(
            "C28 B27 A27 C27 D28 E28 A28 D29",
            "D25 C26 E25 B25 C24 A25 D24 B26",
            "B20 D21 B22 E23 E22 D20 B21 A20",
            "F23 H21 F24 G21 F22 E21 G22 E20"),
            IOStandard("SSTL15_DCI"),
            Misc("ODT=RTT_40"),
            Misc("DATA_RATE=DDR")),
        Subsignal("dqs_p", Pins("B29 B24 C21 G20"),
            IOStandard("DIFF_SSTL15"),
            Misc("DATA_RATE=DDR")),
        Subsignal("dqs_n", Pins("A29 A24 C22 F20"),
            IOStandard("DIFF_SSTL15"),
            Misc("DATA_RATE=DDR")),
        Subsignal("clk_p", Pins("J19"), IOStandard("DIFF_SSTL15"), Misc("DATA_RATE=DDR")),
        Subsignal("clk_n", Pins("J18"), IOStandard("DIFF_SSTL15"), Misc("DATA_RATE=DDR")),
        Subsignal("cke", Pins("H18"), IOStandard("SSTL15")),
        Subsignal("odt", Pins("F19"), IOStandard("SSTL15")),
        Subsignal("reset_n", Pins("F14"), IOStandard("LVCMOS15")),
        Misc("SLEW=FAST"),
    ),

    # drtio
    ("drtio_tx", 0,
        Subsignal("p", Pins("AN4 AM6")),
        Subsignal("n", Pins("AN3 AM5"))
    ),
    ("drtio_rx", 0,
        Subsignal("p", Pins("AP2 AM2")),
        Subsignal("n", Pins("AP1 AM1"))
    ),
    ("drtio_tx_disable_n", 0, Pins("AP11 AM12"), IOStandard("LVCMOS18")),

    # rtm
    ("rtm_refclk125", 0,
        Subsignal("p", Pins("V6")),
        Subsignal("n", Pins("V5")),
    ),
    ("rtm_refclk156p25", 0,
        Subsignal("p", Pins("P6")),
        Subsignal("n", Pins("P5")),
    ),

    # amc_rtm_link
    ("amc_rtm_link", 0,
        Subsignal("clk_p", Pins("J8")), # rtm_fpga_usr_io_p
        Subsignal("clk_n", Pins("H8")), # rtm_fpga_usr_io_n
        Subsignal("tx_p", Pins("A13")), # rtm_fpga_lvds1_p
        Subsignal("tx_n", Pins("A12")), # rtm_fpga_lvds1_n
        Subsignal("rx_p", Pins("C12")), # rtm_fpga_lvds2_p
        Subsignal("rx_n", Pins("B12")), # rtm_fpga_lvds2_n
        IOStandard("LVDS")
    ),
]


class Platform(XilinxPlatform):
    default_clk_name = "clk50"
    default_clk_period = 20.0

    def __init__(self):
        XilinxPlatform.__init__(self, "xcku040-ffva1156-1-c", _io,
            toolchain="vivado")


class _CRG(Module):
    def __init__(self, platform):
        self.clock_domains.cd_sys = ClockDomain()
        self.clock_domains.cd_sys4x = ClockDomain(reset_less=True)
        self.clock_domains.cd_sys4x_dqs = ClockDomain(reset_less=True)
        self.clock_domains.cd_clk200 = ClockDomain()

        clk50 = platform.request("clk50")
        clk50_bufr = Signal()

        pll_locked = Signal()
        pll_fb = Signal()
        pll_sys = Signal()
        pll_sys4x = Signal()
        pll_sys4x_dqs = Signal()
        pll_clk200 = Signal()
        self.specials += [
            Instance("BUFR", i_I=clk50, o_O=clk50_bufr),
            Instance("PLLE2_BASE",
                     p_STARTUP_WAIT="FALSE", o_LOCKED=pll_locked,

                     # VCO @ 1GHz
                     p_REF_JITTER1=0.01, p_CLKIN1_PERIOD=20.0,
                     p_CLKFBOUT_MULT=20, p_DIVCLK_DIVIDE=1,
                     i_CLKIN1=clk50_bufr, i_CLKFBIN=pll_fb, o_CLKFBOUT=pll_fb,

                     # 125MHz
                     p_CLKOUT0_DIVIDE=8, p_CLKOUT0_PHASE=0.0, o_CLKOUT0=pll_sys,

                     # 500MHz
                     p_CLKOUT1_DIVIDE=2, p_CLKOUT1_PHASE=0.0, o_CLKOUT1=pll_sys4x,

                     # 500MHz dqs
                     p_CLKOUT2_DIVIDE=2, p_CLKOUT2_PHASE=90.0, o_CLKOUT2=pll_sys4x_dqs,

                     # 200MHz
                     p_CLKOUT3_DIVIDE=5, p_CLKOUT3_PHASE=0.0, o_CLKOUT3=pll_clk200
            ),
            Instance("BUFG", i_I=pll_sys, o_O=self.cd_sys.clk),
            Instance("BUFG", i_I=pll_sys4x, o_O=self.cd_sys4x.clk),
            Instance("BUFG", i_I=pll_sys4x_dqs, o_O=self.cd_sys4x_dqs.clk),
            Instance("BUFG", i_I=pll_clk200, o_O=self.cd_clk200.clk),
            AsyncResetSynchronizer(self.cd_sys, ~pll_locked),
            AsyncResetSynchronizer(self.cd_clk200, ~pll_locked),
        ]
        platform.add_platform_command("set_property CLOCK_DEDICATED_ROUTE BACKBONE [get_nets crg_clk50_bufr]")

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


class SDRAMTestSoC(SoCSDRAM):
    def __init__(self, platform, ddram="ddram_32"):
        clk_freq = int(125e6)
        SoCSDRAM.__init__(self, platform, clk_freq,
            integrated_rom_size=0x8000,
            integrated_sram_size=0x8000,
            ident="Sayma AMC SDRAM Test Design"
        )
        self.csr_devices += ["ddrphy"]

        self.submodules.crg = _CRG(platform)
        self.crg.cd_sys.clk.attr.add("keep")
        platform.add_period_constraint(self.crg.cd_sys.clk, 8.0)

        # sdram
        self.submodules.ddrphy = kusddrphy.KUSDDRPHY(platform.request(ddram))
        self.config["KUSDDRPHY"] = 1
        sdram_module = MT41J256M16(self.clk_freq, "1:4")
        self.register_sdram(self.ddrphy, "minicon",
                            sdram_module.geom_settings, sdram_module.timing_settings)


class DRTIOTestSoC(SoCCore):
    def __init__(self, platform, pll="cpll", dw=20):
        clk_freq = int(125e6)
        SoCCore.__init__(self, platform, clk_freq,
            integrated_rom_size=0x8000,
            integrated_sram_size=0x8000,
            ident="Sayma AMC DRTIO Test Design"
        )
        self.csr_devices += ["drtio_phy"]

        self.submodules.crg = _CRG(platform)
        self.crg.cd_sys.clk.attr.add("keep")
        platform.add_period_constraint(self.crg.cd_sys.clk, 8.0)

        refclk = Signal()
        refclk_pads = platform.request("rtm_refclk125")
        self.specials += [
            Instance("IBUFDS_GTE3",
                i_CEB=0,
                i_I=refclk_pads.p,
                i_IB=refclk_pads.n,
                o_O=refclk)
        ]

        if pll == "cpll":
            plls = [GTHChannelPLL(refclk, 125e6, 1.25e9) for i in range(2)]
            self.submodules += iter(plls)
            print(plls)
        elif pll == "qpll":
            qpll = GTHQuadPLL(refclk, 125e6, 1.25e9)
            plls = [qpll for i in range(2)]
            self.submodules += qpll
            print(qpll)

        self.submodules.drtio_phy = drtio_phy = MultiGTH(
            plls, 
            platform.request("drtio_tx"),
            platform.request("drtio_rx"),
            clk_freq,
            dw=dw)
        self.comb += platform.request("drtio_tx_disable_n").eq(0b11)

        counter = Signal(32)
        self.sync.gth0_tx += counter.eq(counter + 1)

        for i in range(drtio_phy.nlanes):
            self.comb += [
                drtio_phy.encoders[2*i + 0].k.eq(1),
                drtio_phy.encoders[2*i + 0].d.eq((5 << 5) | 28),
                drtio_phy.encoders[2*i + 1].k.eq(0),
            ]
            self.comb += drtio_phy.encoders[2*i + 1].d.eq(counter[26:])
            for j in range(2):
                self.comb += platform.request("user_led", 2*i + j).eq(drtio_phy.decoders[2*i + 1].d[j])

        for i in range(drtio_phy.nlanes):
            drtio_phy.gths[i].cd_tx.clk.attr.add("keep")
            drtio_phy.gths[i].cd_rx.clk.attr.add("keep")
            platform.add_period_constraint(drtio_phy.gths[i].cd_tx.clk, 1e9/drtio_phy.gths[i].tx_clk_freq)
            platform.add_period_constraint(drtio_phy.gths[i].cd_rx.clk, 1e9/drtio_phy.gths[i].rx_clk_freq)
            self.platform.add_false_path_constraints(
                self.crg.cd_sys.clk,
                drtio_phy.gths[i].cd_tx.clk,
                drtio_phy.gths[i].cd_rx.clk)


class AMCRTMLinkTestSoC(SoCCore):
    mem_map = {
        "amc_rtm_link": 0x20000000,  # (default shadow @0xa0000000)
    }
    mem_map.update(SoCCore.mem_map)

    def __init__(self, platform, with_analyzer=False):
        clk_freq = int(125e6)
        SoCCore.__init__(self, platform, clk_freq,
            integrated_rom_size=0x8000,
            integrated_sram_size=0x8000,
            integrated_main_ram_size=0x8000,
            ident="Sayma AMC / AMC <--> RTM Link Test Design"
        )
        self.csr_devices += ["amc_rtm_link_control"]

        self.submodules.crg = _CRG(platform)
        self.crg.cd_sys.clk.attr.add("keep")
        platform.add_period_constraint(self.crg.cd_sys.clk, 8.0)

        # amc <--> rtm usr_uart / aux_uart redirection
        aux_uart_pads = platform.request("serial", 1)
        self.comb += [
            aux_uart_pads.tx.eq(platform.request("usr_uart_p")),
            platform.request("usr_uart_n").eq(aux_uart_pads.rx)
        ]

        # amc rtm link
        amc_rtm_link_pll = KUSSerdesPLL(125e6, 1.25e9, vco_div=2)
        self.comb += amc_rtm_link_pll.refclk.eq(ClockSignal())
        self.submodules += amc_rtm_link_pll

        amc_rtm_link_pads = platform.request("amc_rtm_link")
        amc_rtm_link_serdes = KUSSerdes(amc_rtm_link_pll, amc_rtm_link_pads, mode="master")
        self.submodules.amc_rtm_link_serdes = amc_rtm_link_serdes
        amc_rtm_link_init = SerdesMasterInit(amc_rtm_link_serdes, taps=512)
        self.submodules.amc_rtm_link_init = amc_rtm_link_init
        self.submodules.amc_rtm_link_control = SerdesControl(amc_rtm_link_init, mode="master")

        amc_rtm_link_serdes.cd_serdes.clk.attr.add("keep")
        amc_rtm_link_serdes.cd_serdes_20x.clk.attr.add("keep")
        amc_rtm_link_serdes.cd_serdes_5x.clk.attr.add("keep")
        platform.add_period_constraint(amc_rtm_link_serdes.cd_serdes.clk, 32.0),
        platform.add_period_constraint(amc_rtm_link_serdes.cd_serdes_20x.clk, 1.6),
        platform.add_period_constraint(amc_rtm_link_serdes.cd_serdes_5x.clk, 6.4)
        self.platform.add_false_path_constraints(
            self.crg.cd_sys.clk,
            amc_rtm_link_serdes.cd_serdes.clk,
            amc_rtm_link_serdes.cd_serdes_5x.clk)


        # wishbone slave
        amc_rtm_link_depacketizer = packet.Depacketizer(clk_freq)
        amc_rtm_link_packetizer = packet.Packetizer()
        self.submodules += amc_rtm_link_depacketizer, amc_rtm_link_packetizer
        amc_rtm_link_etherbone = etherbone.Etherbone(mode="slave")
        self.submodules += amc_rtm_link_etherbone
        amc_rtm_link_tx_cdc = stream.AsyncFIFO([("data", 32)], 8)
        amc_rtm_link_tx_cdc = ClockDomainsRenamer({"write": "sys", "read": "serdes"})(amc_rtm_link_tx_cdc)
        self.submodules += amc_rtm_link_tx_cdc
        amc_rtm_link_rx_cdc = stream.AsyncFIFO([("data", 32)], 8)
        amc_rtm_link_rx_cdc = ClockDomainsRenamer({"write": "serdes", "read": "sys"})(amc_rtm_link_rx_cdc)
        self.submodules += amc_rtm_link_rx_cdc
        self.comb += [
            # core <--> etherbone
            amc_rtm_link_depacketizer.source.connect(amc_rtm_link_etherbone.sink),
            amc_rtm_link_etherbone.source.connect(amc_rtm_link_packetizer.sink),
            
            # core --> serdes
            amc_rtm_link_packetizer.source.connect(amc_rtm_link_tx_cdc.sink),
            If(amc_rtm_link_tx_cdc.source.stb & amc_rtm_link_init.ready,
                amc_rtm_link_serdes.tx_data.eq(amc_rtm_link_tx_cdc.source.data)
            ),
            amc_rtm_link_tx_cdc.source.ack.eq(amc_rtm_link_init.ready),

            # serdes --> core
            amc_rtm_link_rx_cdc.sink.stb.eq(amc_rtm_link_init.ready),
            amc_rtm_link_rx_cdc.sink.data.eq(amc_rtm_link_serdes.rx_data),
            amc_rtm_link_rx_cdc.source.connect(amc_rtm_link_depacketizer.sink),
        ]
        self.add_wb_slave(mem_decoder(self.mem_map["amc_rtm_link"]), amc_rtm_link_etherbone.wishbone.bus)


def main():
    platform = Platform()
    if len(sys.argv) < 2:
        print("missing target (ddram or drtio or amc_rtm_link)")
        exit()
    if sys.argv[1] == "ddram":
        dw = "32"
        if len(sys.argv) > 2:
            dw = sys.argv[2]
        soc = SDRAMTestSoC(platform, "ddram_" + dw)
    elif sys.argv[1] == "drtio":
        soc = DRTIOTestSoC(platform)
    elif sys.argv[1] == "amc_rtm_link":
        soc = AMCRTMLinkTestSoC(platform)
    builder = Builder(soc, output_dir="build_sayma_amc")
    vns = builder.build()


if __name__ == "__main__":
    main()
