#!/usr/bin/env python3
from litex.build.xilinx import VivadoProgrammer

prog = VivadoProgrammer()
prog.load_bitstream(
    bitstream_file="build_sayma_rtm/gateware/top.bit",
    target="FIXME")