#!/usr/bin/env python3

from litex.soc.tools.remote import RemoteClient

wb_amc = RemoteClient(port=1234, csr_csv="../sayma_amc/csr.csv", debug=False)
wb_rtm = RemoteClient(port=1235, csr_csv="../sayma_rtm/csr.csv", debug=False)
wb_amc.open()
wb_rtm.open()

# # #

# get amc identifier
fpga_id = ""
for i in range(256):
    c = chr(wb_amc.read(wb_amc.bases.identifier_mem + 4*i) & 0xff)
    fpga_id += c
    if c == "\0":
        break
print("AMC fpga_id:" + fpga_id)


# get rtm identifier
fpga_id = ""
for i in range(256):
    c = chr(wb_rtm.read(wb_rtm.bases.identifier_mem + 4*i) & 0xff)
    fpga_id += c
    if c == "\0":
        break
print("RTM fpga_id:" + fpga_id)

# # #

wb_amc.close()
wb_rtm.close()
