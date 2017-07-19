#!/usr/bin/env python3

import sys
import time

from litex.soc.tools.remote import RemoteClient

from litescope.software.driver.analyzer import LiteScopeAnalyzerDriver

wb = RemoteClient(port=1234, debug=False)
wb.open()

# # #

tx_ready = 0x1
rx_ready = 0x2

def drtio_init():
    wb.regs.drtio_phy_gth0_restart.write(1)
    wb.regs.drtio_phy_gth1_restart.write(1)
    while (((wb.regs.drtio_phy_gth0_ready.read() & rx_ready) == 0) or
           ((wb.regs.drtio_phy_gth1_ready.read() & rx_ready) == 0)):
        wb.regs.drtio_phy_gth0_restart.write(1)
        wb.regs.drtio_phy_gth1_restart.write(1)
        time.sleep(1)


if len(sys.argv) < 2:
    print("missing test (init)")
    wb.close()
    exit()
if sys.argv[1] == "init":
   drtio_init()
else:
    raise ValueError

# # #

wb.close()
