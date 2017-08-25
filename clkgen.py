#!/usr/bin/env python3
import sys

from litex.gen import *
from litex.boards.platforms import kc705

from litex.gen.genlib.io import CRG

from litex.soc.integration.soc_core import *
from litex.soc.integration.builder import *
from litex.soc.cores.uart import UARTWishboneBridge


class ClkGenSoC(SoCCore):
    def __init__(self, platform):
        clk_freq = int(200e9)
        SoCCore.__init__(self, platform, clk_freq,
            cpu_type=None,
            csr_data_width=32,
            with_uart=False,
            ident="KC705 100MHz Clock Generator",
            with_timer=False
        )
        self.submodules.crg = CRG(platform.request("clk200"))
        self.add_cpu_or_bridge(UARTWishboneBridge(platform.request("serial"),
                                                  clk_freq, baudrate=115200))
        self.add_wb_master(self.cpu_or_bridge.wishbone)

        pll_locked = Signal()
        pll_fb = Signal()
        pll_out = Signal()
        self.specials += [
            Instance("PLLE2_BASE",
                     p_STARTUP_WAIT="FALSE", o_LOCKED=pll_locked,

                     # VCO @ 1GHz
                     p_REF_JITTER1=0.01, p_CLKIN1_PERIOD=5.0,
                     p_CLKFBOUT_MULT=5, p_DIVCLK_DIVIDE=1,
                     i_CLKIN1=ClockSignal(), i_CLKFBIN=pll_fb, o_CLKFBOUT=pll_fb,

                     # 1GHz
                     p_CLKOUT2_DIVIDE=1, p_CLKOUT2_PHASE=0.0,
                     o_CLKOUT2=pll_out
            )
        ]

        user_sma_clock_pads = platform.request("user_sma_clock")
        self.specials += [
            Instance("OBUFDS",
                i_I=pll_out,
                o_O=user_sma_clock_pads.p,
                o_OB=user_sma_clock_pads.n
            )
        ]


def main():
    soc = ClkGenSoC(kc705.Platform())
    builder = Builder(soc, output_dir="build_clkgen")
    builder.build()


if __name__ == "__main__":
    main()
