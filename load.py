#!/usr/bin/env python3

import sys

from litex.build.xilinx import VivadoProgrammer


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
        print("missing sayma board (amc or rtm)")
        exit()
    if sys.argv[1] == "amc":
        load_sayma_amc()
    elif sys.argv[1] == "rtm":
        load_sayma_rtm()


if __name__ == "__main__":
    main()
