#!/usr/bin/env python3
import sys

from litex.soc.tools.remote import RemoteClient

from litejesd204b.common import *

from libbase.ad9154 import *

wb_amc = RemoteClient(port=1234, csr_csv="../sayma_amc/csr.csv", debug=False)
wb_rtm = RemoteClient(port=1235, csr_csv="../sayma_rtm/csr.csv", debug=False)
wb_amc.open()
wb_rtm.open()

# # #

# jesd settings
ps = JESD204BPhysicalSettings(l=8, m=4, n=16, np=16)
ts = JESD204BTransportSettings(f=2, s=2, k=16, cs=0)
jesd_settings = JESD204BSettings(ps, ts, did=0x5a, bid=0x5)


# configure tx electrical settings
for i in range(8):
    produce_square_wave = getattr(wb_amc.regs, "dac0_core_phy{:d}_transmitter_produce_square_wave".format(i))
    txdiffctrl = getattr(wb_amc.regs, "dac0_core_phy{:d}_transmitter_txdiffcttrl".format(i))
    txmaincursor = getattr(wb_amc.regs, "dac0_core_phy{:d}_transmitter_txmaincursor".format(i))
    txprecursor = getattr(wb_amc.regs, "dac0_core_phy{:d}_transmitter_txprecursor".format(i))
    txpostcursor = getattr(wb_amc.regs, "dac0_core_phy{:d}_transmitter_txpostcursor".format(i))
    produce_square_wave.write(0) # 1 to generate clock on lane with frequency of linerate/40
    txdiffctrl.write(0b1111) # cf ug576
    txmaincursor.write(80) # cf ug576
    txprecursor.write(0b00000) # cf ug576
    txpostcursor.write(0b00000) # cf ug576

# reset dacs
wb_rtm.regs.dac_reset_out.write(0)
time.sleep(1)
wb_rtm.regs.dac_reset_out.write(1)

time.sleep(1)

# configure dac0
dac0 = AD9154(wb_rtm.regs, 0)
dac0.reset()
print("dac0 configuration")
print("dac0 present: {:s}".format(str(dac0.check_presence())))
dac0.startup(jesd_settings, linerate=10e9)
# show dac0 status
dac0.print_status()

# release/reset jesd core
wb_amc.regs.dac0_control_prbs_config.write(0)
wb_amc.regs.dac0_control_enable.write(0)
wb_amc.regs.dac0_control_enable.write(1)

time.sleep(1)

# show dac0 status
dac0.print_status()

# prbs test
if len(sys.argv) > 1:
    if sys.argv[1] == "prbs":
        fpga_prbs_configs = {
            "prbs7" : 0b01,
            "prbs15": 0b10,
            "prbs31": 0b11
        }
        for prbs in ["prbs7", "prbs15", "prbs31"]:
            # configure prbs on fpga
            wb_amc.regs.dac0_control_prbs_config.write(fpga_prbs_configs[prbs])
            # prbs test on ad9154
            status, errors = dac0.prbs_test(prbs, 100)
            print("{:s} test status: {:02x}".format(prbs, status))
            print("-"*40)
            for i in range(8):
                print("-lane{:d}: {:d} errors".format(i, errors[i]))

# # #

wb_amc.close()
wb_rtm.close()
