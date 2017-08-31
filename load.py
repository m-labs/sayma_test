#!/usr/bin/env python3

import sys

from litex.build.xilinx import VivadoProgrammer


def load_clkgen():
    prog = VivadoProgrammer()
    prog.load_bitstream(
        bitstream_file="build_clkgen/gateware/top.bit")


def load_sayma_amc():
    prog = VivadoProgrammer()
    prog.load_bitstream(
        
        bitstream_file="build_sayma_amc/gateware/top.bit",
        device=0)


def load_sayma_rtm():
    prog = VivadoProgrammer()
    prog.load_bitstream(
        bitstream_file="build_sayma_rtm/gateware/top.bit",
        device=1)


def main():
    if len(sys.argv) < 2:
        print("missing sayma board (clkgen, sayma_amc, sayma_rtm or sayma)")
        exit()
    if sys.argv[1] == "clkgen":
        load_clkgen()
    elif sys.argv[1] == "sayma_amc":
        load_sayma_amc()
    elif sys.argv[1] == "sayma_rtm":
        load_sayma_rtm()
    elif sys.argv[1] == "sayma":
        load_sayma_rtm()
        load_sayma_amc()

if __name__ == "__main__":
    main()
