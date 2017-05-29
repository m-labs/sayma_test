#!/usr/bin/env python3

# first start litex_server:
#    litex_server --port <your_serial_port>
# then execute this script

from litex.soc.tools.remote import RemoteClient

wb = RemoteClient()
wb.open()


# # #

# jesd settings
ps = JESD204BPhysicalSettings(l=4, m=4, n=16, np=16)
ts = JESD204BTransportSettings(f=2, s=1, k=16, cs=1)
jesd_settings = JESD204BSettings(ps, ts, did=0x5a, bid=0x5)

# configure ad9514
print("AD9154 configuration")
print("AD9154 present: {:s}".format(str(ad9154.check_presence())))
ad9154 = AD9154(wb.regs)
ad9154.reset()
ad9154.startup(jesd_settings, linerate=10e9)
# show ad9514 status
ad9154.print_status()

# # #

wb.close()
