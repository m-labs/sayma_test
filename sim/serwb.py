#!/usr/bin/env python3

import os
import sys
sys.path.append("../")

from litex.gen import *
from litex.build.generic_platform import *
from litex.build.xilinx import XilinxPlatform

from litex.gen.genlib.io import CRG

from gateware.transceiver.serwb import *


_io = [
    ("clk125", 0, Pins("X")),
    ("amc_serdes", 0,
        Subsignal("clk_p", Pins("X")),
        Subsignal("clk_n", Pins("X")),
        Subsignal("tx_p", Pins("X")),
        Subsignal("tx_n", Pins("X")),
        Subsignal("rx_p", Pins("X")),
        Subsignal("rx_n", Pins("X")),
    ),
    ("rtm_serdes", 0,
        Subsignal("clk_p", Pins("X")),
        Subsignal("clk_n", Pins("X")),
        Subsignal("tx_p", Pins("X")),
        Subsignal("tx_n", Pins("X")),
        Subsignal("rx_p", Pins("X")),
        Subsignal("rx_n", Pins("X")),
    )
]


class Platform(XilinxPlatform):
    def __init__(self):
        XilinxPlatform.__init__(self, "", _io)


class AMCRTMLinkSim(Module):
    def __init__(self, platform):
        clk_freq = 125e6
        self.submodules.crg = CRG(platform.request("clk125"))

        # amc
        amc_pll = SerdesPLL(125e6, 1e9)
        self.submodules += amc_pll
        self.comb += amc_pll.refclk.eq(ClockSignal())
        self.submodules.amc_serdes = AMCMasterSerdes(amc_pll, platform.request("amc_serdes"))
        self.comb += self.amc_serdes.tx_data.eq(0x5a)
        self.submodules.amc_serdes_init = AMCMasterSerdesInit(self.amc_serdes)

        # rtm
        rtm_pll = SerdesPLL(125e6, 1e9)
        self.submodules += rtm_pll
        self.submodules.rtm_serdes = RTMSlaveSerdes(rtm_pll, platform.request("rtm_serdes"))
        self.comb += self.rtm_serdes.tx_data.eq(0x5a)
        self.submodules.rtm_serdes_init = RTMSlaveSerdesInit(self.rtm_serdes)        


def generate_top():
    platform = Platform()
    soc = AMCRTMLinkSim(platform)
    platform.build(soc, build_dir="./", run=False)

def generate_top_tb():
    f = open("top_tb.v", "w")
    f.write("""
`timescale 1ns/1ps

module top_tb();

reg clk125;
initial clk125 = 1'b1;
always #4 clk125 = ~clk125;

wire serdes_clk_p;
wire serdes_clk_n;
wire serdes_tx_p;
wire serdes_tx_n;
wire serdes_rx_p;
wire serdes_rx_n;

top dut (
    .clk125(clk125),
    .amc_serdes_clk_p(serdes_clk_p),
    .amc_serdes_clk_n(serdes_clk_n),
    .amc_serdes_tx_p(serdes_tx_p),
    .amc_serdes_tx_n(serdes_tx_n),
    .amc_serdes_rx_p(serdes_rx_p),
    .amc_serdes_rx_n(serdes_rx_n),
    .rtm_serdes_clk_p(serdes_clk_p),
    .rtm_serdes_clk_n(serdes_clk_n),
    .rtm_serdes_tx_p(serdes_rx_p),
    .rtm_serdes_tx_n(serdes_rx_n),
    .rtm_serdes_rx_p(serdes_tx_p),
    .rtm_serdes_rx_n(serdes_tx_n)
);

endmodule""")
    f.close()

def run_sim():
    os.system("rm -rf xsim.dir")
    os.system("call xvlog glbl.v")
    os.system("call xvlog top.v")
    os.system("call xvlog top_tb.v")
    os.system("call xelab -debug typical top_tb glbl -s top_tb_sim -L unisims_ver -L unimacro_ver -L SIMPRIM_VER -L secureip -L $xsimdir/xil_defaultlib -timescale 1ns/1ps")
    os.system("call xsim top_tb_sim -gui")

def main():
    generate_top()
    generate_top_tb()
    run_sim()

if __name__ == "__main__":
    main()
