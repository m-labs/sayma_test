#!/usr/bin/env python3

from misoc.tools.remote import RemoteClient

wb = RemoteClient(port=1234, debug=False)
wb.open()


# # #

# after ad9154 configuration with rtm, release/reset jesd core:
wb.regs.control_prbs_config.write(0)
wb.regs.control_enable.write(0)
time.sleep(0.1)
wb.regs.control_enable.write(1)

# to activate stpl test:
wb.regs.control_stpl_enable.write(1)

# to activate prbs test:
fpga_prbs_error_injection = 0
fpga_prbs_configs = {
    "prbs7" : 0b001,
    "prbs15": 0b010,
    "prbs31": 0b100
}
 wb.regs.control_prbs_config.write(
    fpga_prbs_configs["prbs7"])

# # #

wb.close()
