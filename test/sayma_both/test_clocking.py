#!/usr/bin/env python3
import sys
import runpy


from litex.soc.tools.remote import RemoteClient

from libbase.hmc import *


if len(sys.argv) < 2:
    print("missing config (2p5gbps, 5gbps or 10gbps)")
    exit()


# hmc830 config, 100MHz input, 1GHz output
# fvco = (refclk / r_divider) * n_divider
# fout = fvco/2 
hmc830_config = [
    (0x0, 0x20),
    (0x1, 0x2),
    (0x2, 0x2), # r_divider
    (0x5, 0x1628),
    (0x5, 0x60a0),
    (0x5, 0xe110),
    (0x5, 0x2818),
    (0x5, 0x0),
    (0x6, 0x303ca),
    (0x7, 0x14d),
    (0x8, 0xc1beff),
    (0x9, 0x153fff),
    (0xa, 0x2046),
    (0xb, 0x7c061),
    (0xf, 0x81),
    (0x3, 0x28), # n_divider
]

hmc7043_config = []

class HMC7043DUT:
    @staticmethod
    def write(address, value):
        hmc7043_config.append([address, value])

runpy.run_path("libbase/hmc7043_config_" + sys.argv[1] + ".py", {"dut": HMC7043DUT})

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
for addr, data in hmc7043_config:
    hmc7043.write(addr, data)

# # #

wb_amc.close()
wb_rtm.close()
