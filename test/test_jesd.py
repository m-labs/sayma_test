#!/usr/bin/env python3

import time

from litex.soc.tools.remote import RemoteClient

from libbase.ad9516 import AD9516
from libbase.ad9516_regs import *

from libbase.ad9154 import AD9154
from libbase.ad9154_regs import *

from litejesd204b.common import *

wb = RemoteClient()
wb.open()

# # #

ad9516_config = True

ad9154_config = True
ad9154_stpl_test = True
ad9154_monitor_test = False
ad9154_prbs_test = True

physical_lanes = 0xff

# # #

# configure ad9516 pll
if ad9516_config:
    ad9516 = AD9516(wb.regs)
    print("AD9516 configuration")
    print("AD9516 present: {:s}".format(str(ad9516.check_presence())))
    ad9516.reset()
    # 10Gbps linerate /1Ghz DACCLK / 1x interpolation
    ad9516.select_clk_as_source(bypass_vco_divider=True) # 500MHz
    ad9516.set_dacclk_divider(1)  # 1Ghz
    ad9516.set_refclk_divider(4)  # 250MHz / 10Gbps linerate
    ad9516.set_sysref_divider(64) # 15.625MHz
    ad9516.enable_dacclk()
    ad9516.enable_refclk()
    ad9516.enable_sysref()
    ad9516.commit()

# jesd settings
ps = JESD204BPhysicalSettings(l=8 if physical_lanes == 0xff else 4, m=4, n=16, np=16)
ts = JESD204BTransportSettings(f=2, s=2 if physical_lanes == 0xff else 1, k=16, cs=0)
jesd_settings = JESD204BSettings(ps, ts, did=0x5a, bid=0x5)



# configure ad9514
if ad9154_config:
    ad9154 = AD9154(wb.regs)
    print("AD9154 configuration")
    print("AD9154 present: {:s}".format(str(ad9154.check_presence())))
    ad9154.reset()
    ad9154.startup(jesd_settings, linerate=10e9, physical_lanes=physical_lanes)
    # show ad9514 status
    ad9154.print_status()

    # release/reset jesd core
    wb.regs.control_prbs_config.write(0)
    wb.regs.control_enable.write(0)
    wb.regs.control_enable.write(1)

    time.sleep(1)

    # show ad9514 status
    ad9154.print_status()

# short transport layer test
if ad9154_stpl_test:
    wb.regs.control_stpl_enable.write(1)
    status = ad9154.stpl_test(m=4, s=2 if physical_lanes == 0xff else 1)
    for i in range(4):
        print("converter {:d}: {:s}".format(
            i, {0: "pass", 1: "fail"}[status[i]]))
    wb.regs.control_stpl_enable.write(0)

# monitor test
if ad9154_monitor_test:
    wb.regs.control_restart_count_clear.write(1)
    while True:
        print("restarts: {:d}".format(wb.regs.control_restart_count.read()))
        time.sleep(1)

# prbs test
if ad9154_prbs_test:
    fpga_prbs_configs = {
        "prbs7" : 0b01,
        "prbs15": 0b10,
        "prbs31": 0b11
    }
    for prbs in ["prbs7", "prbs15", "prbs31"]:
        # configure prbs on fpga
        wb.regs.control_prbs_config.write(fpga_prbs_configs[prbs])
        # prbs test on ad9154
        status, errors = ad9154.prbs_test(prbs, 100)
        print("{:s} test status: {:02x}".format(prbs, status))
        print("-"*40)
        for i in range(8):
            print("-lane{:d}: {:d} errors".format(i, errors[i]))

# # #

wb.close()
