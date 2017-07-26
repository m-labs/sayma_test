#!/usr/bin/env python3
import sys
sys.path.append("gateware") # FIXME

from litex.gen import *
from litex.soc.interconnect.csr import *
from litex.gen.genlib.resetsync import AsyncResetSynchronizer

from litex.build.generic_platform import *
from litex.build.xilinx import XilinxPlatform

from litex.soc.integration.soc_core import *
from litex.soc.integration.soc_sdram import *
from litex.soc.integration.builder import *
from litex.soc.cores.uart import UARTWishboneBridge
from litex.soc.interconnect import stream

from litedram.modules import MT41J256M16
from litedram.phy import kusddrphy
from litedram.frontend.bist import LiteDRAMBISTGenerator
from litedram.frontend.bist import LiteDRAMBISTChecker

from litejesd204b.common import *
from litejesd204b.phy.gth import GTHQuadPLL
from litejesd204b.phy import LiteJESD204BPhyTX
from litejesd204b.core import LiteJESD204BCoreTX
from litejesd204b.core import LiteJESD204BCoreTXControl

from drtio.gth_ultrascale import GTHChannelPLL, GTHQuadPLL, MultiGTH

from amc_rtm_link.kusphy import KUSSerdesPLL, KUSSerdes
from amc_rtm_link.phy import SerdesMasterInit, SerdesControl
from amc_rtm_link import packet
from amc_rtm_link import etherbone

from gateware import firmware

from litescope import LiteScopeAnalyzer


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

    # dac
    ("dac_refclk", 0,
        Subsignal("p", Pins("K6")),
        Subsignal("n", Pins("K5")),
    ),
    ("dac_sysref", 0,
        Subsignal("p", Pins("B10")),
        Subsignal("n", Pins("A10")),
        IOStandard("LVDS")
    ),
    ("dac_sync", 0,
        Subsignal("p", Pins("L8")),
        Subsignal("n", Pins("K8")),
        IOStandard("LVDS")
    ),
    ("dac_jesd", 0,
        Subsignal("txp", Pins("B6 C4 D6 F6 G4 J4 L4 N4")),
        Subsignal("txn", Pins("B5 C3 D5 F5 G3 J3 L3 N3"))
    ),

    ("dac_refclk", 1,
        Subsignal("p", Pins("K6")),
        Subsignal("n", Pins("K5")),
    ),
    ("dac_sysref", 1,
        Subsignal("p", Pins("B10")),
        Subsignal("n", Pins("A10")),
        IOStandard("LVDS")
    ),
    ("dac_sync", 1,
        Subsignal("p", Pins("J9")),
        Subsignal("n", Pins("H9")),
        IOStandard("LVDS")
    ),
    ("dac_jesd", 1,
        Subsignal("txp", Pins("R4 U4 W4 AA4 AC4 AE4 AG4 AH6")),
        Subsignal("txn", Pins("R3 U3 W3 AA3 AC3 AE3 AG3 AH5"))
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
    csr_map = {
        "ddrphy":    20,
        "generator": 21,
        "checker":   22,
        "analyzer":  30
    }
    csr_map.update(SoCSDRAM.csr_map)

    mem_map = {
        "firmware_ram": 0x20000000,
    }
    mem_map.update(SoCSDRAM.mem_map)

    def __init__(self, platform, ddram="ddram_32", with_cpu=False):
        clk_freq = int(125e6)
        SoCSDRAM.__init__(self, platform, clk_freq,
            cpu_type="lm32" if with_cpu else None,
            integrated_rom_size=0x8000 if with_cpu else 0,
            integrated_sram_size=0x8000 if with_cpu else 0,
            csr_data_width=8 if with_cpu else 32,
            l2_size=128,
            with_uart=with_cpu, uart_stub=False,
            ident="Sayma AMC SDRAM Test Design",
            with_timer=with_cpu
        )
        self.submodules.crg = _CRG(platform)
        if not with_cpu:
            self.add_cpu_or_bridge(UARTWishboneBridge(platform.request("serial"),
                                                      clk_freq, baudrate=115200))
            self.add_wb_master(self.cpu_or_bridge.wishbone)

        self.crg.cd_sys.clk.attr.add("keep")
        platform.add_period_constraint(self.crg.cd_sys.clk, 8.0)

        # firmware
        firmware_ram_size = 0x10000
        firmware_filename = "firmware/firmware.bin"
        self.submodules.firmware_ram = firmware.FirmwareROM(firmware_ram_size, firmware_filename)
        self.register_mem("firmware_ram", self.mem_map["firmware_ram"], self.firmware_ram.bus, firmware_ram_size)
        self.add_constant("ROM_BOOT_ADDRESS", self.mem_map["firmware_ram"])

        # sdram
        self.submodules.ddrphy = kusddrphy.KUSDDRPHY(platform.request(ddram))
        sdram_module = MT41J256M16(self.clk_freq, "1:4")
        self.register_sdram(self.ddrphy,
                            sdram_module.geom_settings,
                            sdram_module.timing_settings)

        # sdram bist
        if not with_cpu:
            generator_user_port = self.sdram.crossbar.get_port(mode="write")
            self.submodules.generator = LiteDRAMBISTGenerator(
                generator_user_port, random=True)
            checker_user_port = self.sdram.crossbar.get_port(mode="read")
            self.submodules.checker = LiteDRAMBISTChecker(
                checker_user_port, random=True)

        # leds
        led_counter = Signal(32)
        self.sync += led_counter.eq(led_counter + 1)
        self.comb += [
            platform.request("user_led", 0).eq(led_counter[26]),
            platform.request("user_led", 1).eq(led_counter[27]),
            platform.request("user_led", 2).eq(led_counter[28]),
            platform.request("user_led", 3).eq(led_counter[29])
        ]

        # analyzer
        if not with_cpu:
            dfi_phase_groups = []
            for i in range(4):
                dfi_phase_group = [
                    self.ddrphy.dfi.phases[i].address,
                    self.ddrphy.dfi.phases[i].bank,
                    self.ddrphy.dfi.phases[i].ras_n,
                    self.ddrphy.dfi.phases[i].cas_n,
                    self.ddrphy.dfi.phases[i].we_n,
                    self.ddrphy.dfi.phases[i].cs_n,
                    self.ddrphy.dfi.phases[i].cke,
                    self.ddrphy.dfi.phases[i].odt,
                    self.ddrphy.dfi.phases[i].reset_n,
                    self.ddrphy.dfi.phases[i].wrdata_en,
                    self.ddrphy.dfi.phases[i].wrdata_mask,
                    self.ddrphy.dfi.phases[i].wrdata,
                    self.ddrphy.dfi.phases[i].rddata,
                    self.ddrphy.dfi.phases[i].rddata_valid
                ]
                dfi_phase_groups.append(dfi_phase_group)
            analyzer_signals = {
                0 : dfi_phase_groups[0],
                1 : dfi_phase_groups[1],
                2 : dfi_phase_groups[2],
                3 : dfi_phase_groups[3]
            }
            if not with_cpu:
                self.submodules.analyzer = LiteScopeAnalyzer(analyzer_signals, 64)

    def do_exit(self, vns):
        if hasattr(self, "analyzer"):
            self.analyzer.export_csv(vns, "test/sayma_amc/analyzer.csv")


def get_phy_pads(jesd_pads, n):
    class PHYPads:
        def __init__(self, txp, txn):
            self.txp = txp
            self.txn = txn
    return PHYPads(jesd_pads.txp[n], jesd_pads.txn[n])


class JESDTestSoC(SoCCore):
    csr_map = {
        "control": 20
    }
    csr_map.update(SoCCore.csr_map)

    def __init__(self, platform, dac=0):
        clk_freq = int(125e6)
        SoCCore.__init__(self, platform, clk_freq,
            cpu_type=None,
            csr_data_width=32,
            with_uart=False,
            ident="Sayma AMC JESD Test Design",
            with_timer=False
        )
        self.submodules.crg = _CRG(platform)

        # uart <--> wishbone
        self.add_cpu_or_bridge(UARTWishboneBridge(platform.request("serial"),
                                                  clk_freq, baudrate=115200))
        self.add_wb_master(self.cpu_or_bridge.wishbone)

        self.crg.cd_sys.clk.attr.add("keep")
        platform.add_period_constraint(self.crg.cd_sys.clk, 8.0)

        # jesd
        ps = JESD204BPhysicalSettings(l=8, m=4, n=16, np=16)
        ts = JESD204BTransportSettings(f=2, s=2, k=16, cs=0)
        settings = JESD204BSettings(ps, ts, did=0x5a, bid=0x5)
        linerate = 10e9
        refclk_freq = 250e6

        self.clock_domains.cd_jesd = ClockDomain()
        refclk_pads = platform.request("dac_refclk", dac)

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

        jesd_pads = platform.request("dac_jesd", dac)
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
                self.crg.cd_sys.clk,
                self.cd_jesd.clk,
                phy.transmitter.cd_tx.clk)
            phys.append(phy)
        to_jesd = ClockDomainsRenamer("jesd")
        self.submodules.core = to_jesd(LiteJESD204BCoreTX(phys, settings,
                                                      converter_data_width=64))
        self.submodules.control = to_jesd(LiteJESD204BCoreTXControl(self.core))
        self.core.register_jsync(platform.request("dac_sync", dac))

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

    def do_exit(self, vns):
        pass


class DRTIOTestSoC(SoCCore):
    csr_map = {
        "drtio_phy": 20
    }
    csr_map.update(SoCCore.csr_map)

    def __init__(self, platform, pll="cpll", dw=20):
        clk_freq = int(125e6)
        SoCCore.__init__(self, platform, clk_freq,
            cpu_type=None,
            csr_data_width=32,
            with_uart=False,
            ident="Sayma AMC DRTIO Test Design",
            with_timer=False
        )
        self.submodules.crg = _CRG(platform)
        self.add_cpu_or_bridge(UARTWishboneBridge(platform.request("serial"),
                                                  clk_freq, baudrate=115200))
        self.add_wb_master(self.cpu_or_bridge.wishbone)

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

    def do_exit(self, vns):
        pass


class AMCRTMLinkTestSoC(SoCCore):
    csr_map = {
        "amc_rtm_link_control": 20,
        "analyzer":             30
    }
    csr_map.update(SoCCore.csr_map)

    mem_map = {
        "amc_rtm_link": 0x20000000,  # (default shadow @0xa0000000)
    }
    mem_map.update(SoCCore.mem_map)

    def __init__(self, platform, with_analyzer=False):
        clk_freq = int(125e6)
        SoCCore.__init__(self, platform, clk_freq,
            cpu_type=None,
            csr_data_width=32,
            with_uart=False,
            ident="Sayma AMC / AMC <--> RTM Link Test Design",
            with_timer=False
        )
        self.submodules.crg = _CRG(platform)

        # uart <--> wishbone
        self.add_cpu_or_bridge(UARTWishboneBridge(platform.request("serial"),
                                                  clk_freq, baudrate=115200))
        self.add_wb_master(self.cpu_or_bridge.wishbone)

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
        amc_rtm_link_init = SerdesMasterInit(amc_rtm_link_serdes, sync_pattern=0x123456789a, taps=512)
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
            If(amc_rtm_link_tx_cdc.source.valid & amc_rtm_link_init.ready,
                amc_rtm_link_serdes.encoder.d[0].eq(amc_rtm_link_tx_cdc.source.data[0:8]),
                amc_rtm_link_serdes.encoder.d[1].eq(amc_rtm_link_tx_cdc.source.data[8:16]),
                amc_rtm_link_serdes.encoder.d[2].eq(amc_rtm_link_tx_cdc.source.data[16:24]),
                amc_rtm_link_serdes.encoder.d[3].eq(amc_rtm_link_tx_cdc.source.data[24:32])
            ),
            amc_rtm_link_tx_cdc.source.ready.eq(amc_rtm_link_init.ready),

            # serdes --> core
            amc_rtm_link_rx_cdc.sink.valid.eq(amc_rtm_link_init.ready),
            amc_rtm_link_rx_cdc.sink.data[0:8].eq(amc_rtm_link_serdes.decoders[0].d),
            amc_rtm_link_rx_cdc.sink.data[8:16].eq(amc_rtm_link_serdes.decoders[1].d),
            amc_rtm_link_rx_cdc.sink.data[16:24].eq(amc_rtm_link_serdes.decoders[2].d),
            amc_rtm_link_rx_cdc.sink.data[24:32].eq(amc_rtm_link_serdes.decoders[3].d),
            amc_rtm_link_rx_cdc.source.connect(amc_rtm_link_depacketizer.sink),
        ]
        self.add_wb_slave(mem_decoder(self.mem_map["amc_rtm_link"]), amc_rtm_link_etherbone.wishbone.bus)

        # analyzer
        if with_analyzer:
            wishbone_access = Signal()
            self.comb += wishbone_access.eq(amc_rtm_link_etherbone.wishbone.bus.stb &
                                            amc_rtm_link_etherbone.wishbone.bus.cyc)
            init_group = [
                wishbone_access,
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
            self.analyzer.export_csv(vns, "test/sayma_amc/analyzer.csv")


def main():
    platform = Platform()
    compile_gateware = True
    if len(sys.argv) < 2:
        print("missing target (ddram or jesd or drtio or amc_rtm_link)")
        exit()
    if sys.argv[1] == "ddram":
        dw = "32"
        with_cpu = False
        if len(sys.argv) > 2:
            dw = sys.argv[2]
        if len(sys.argv) > 3:
            with_cpu = bool(sys.argv[3])
            #compile_gateware = False
        soc = SDRAMTestSoC(platform, "ddram_" + dw, with_cpu)
    elif sys.argv[1] == "jesd":
        soc = JESDTestSoC(platform)
    elif sys.argv[1] == "drtio":
        soc = DRTIOTestSoC(platform)
    elif sys.argv[1] == "amc_rtm_link":
        soc = AMCRTMLinkTestSoC(platform)
    builder = Builder(soc, output_dir="build_sayma_amc", csr_csv="test/sayma_amc/csr.csv",
        compile_gateware=compile_gateware)
    vns = builder.build()
    soc.do_exit(vns)


if __name__ == "__main__":
    main()
