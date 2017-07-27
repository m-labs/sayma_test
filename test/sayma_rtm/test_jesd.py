#!/usr/bin/env python3

from litex.soc.tools.remote import RemoteClient

from litejesd204b.common import *

from litescope.software.driver.analyzer import LiteScopeAnalyzerDriver

from libbase.ad9154 import *
from libbase.hmc import *

from clocking import hmc830_config, hmc7043_config

wb = RemoteClient(port=1235, debug=False)
wb.open()


# # #

# configure clocks
hmc830 = HMC830(wb.regs)
hmc7043 = HMC7043(wb.regs)
print("HMC830 present: {:s}".format(str(hmc830.check_presence())))
print("HMC7043 present: {:s}".format(str(hmc7043.check_presence())))

# configure hmc830
for addr, data in hmc830_config:
    hmc830.write(addr, data)

# configure hmc7043
hmc7043.write(0, 1)
for addr, data in hmc7043_config:
    hmc7043.write(addr, data)

# jesd settings
ps = JESD204BPhysicalSettings(l=8, m=4, n=16, np=16)
ts = JESD204BTransportSettings(f=2, s=2, k=16, cs=0)
jesd_settings = JESD204BSettings(ps, ts, did=0x5a, bid=0x5)

# configure ad9514
ad9154 = AD9154(wb.regs)
print("AD9154 configuration")
print("AD9154 present: {:s}".format(str(ad9154.check_presence())))

ad9154.reset()
ad9154.startup(jesd_settings, linerate=10e9, physical_lanes=0xff)
# show ad9514 status
ad9154.print_status()

# release/reset jesd core
#wb.regs.control_prbs_config.write(0)
#wb.regs.control_enable.write(0)
#wb.regs.control_enable.write(1)

#time.sleep(1)

# show ad9514 status
#ad9154.print_status()

# # #

wb.close()
