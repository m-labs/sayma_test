#!/usr/bin/env python3

from litex.soc.tools.remote import RemoteClient

from libbase.hmc import *

from clocking_config import hmc830_config, hmc7043_config_5gbps, hmc7043_config_10gbps

wb_amc = RemoteClient(port=1234, csr_csv="../sayma_amc/csr.csv", debug=False)
wb_rtm = RemoteClient(port=1235, csr_csv="../sayma_rtm/csr.csv", debug=False)
wb_amc.open()
wb_rtm.open()

# # #

hmc830 = HMC830(wb_rtm.regs)
hmc7043 = HMC7043(wb_rtm.regs)
print("HMC830 present: {:s}".format(str(hmc830.check_presence())))
print("HMC7043 present: {:s}".format(str(hmc7043.check_presence())))

# configure hmc830
for addr, data in hmc830_config:
    hmc830.write(addr, data)

# configure hmc7043
for addr, data in hmc7043_config_5gbps:
    hmc7043.write(addr, data)

# # #

wb_amc.close()
wb_rtm.close()
