#!/usr/bin/env python3

import sys
import time

from litex.soc.tools.remote import RemoteClient

from litescope.software.driver.analyzer import LiteScopeAnalyzerDriver

wb = RemoteClient(debug=False)
wb.open()

# # #

too_late = 0x1
too_early = 0x2

def amc_rtm_link_config():
    # enable square wave
    wb.regs.master_serdes_tx_produce_square_wave.write(1)
    wb.regs.slave_serdes_tx_produce_square_wave.write(1)

    # parameters
    bitslip_range = range(0, 20)
    delay_range = range(0, 512)

    # find slave delay
    wb.regs.slave_serdes_rx_delay_rst.write(1)
    wb.regs.slave_serdes_rx_delay_inc.write(1)
    last_status = 0
    slave_delay = None
    for i in delay_range:
        wb.regs.slave_serdes_phase_detector_reset.write(1)
        status = wb.regs.slave_serdes_phase_detector_status.read()
        if (last_status & too_late) and (status & too_early):
            slave_delay = i
            break
        wb.regs.slave_serdes_rx_delay_ce.write(1)
        last_status = status
    if slave_delay is not None:
        print("slave delay: {:d}".format(slave_delay))
    else:
        print("unable to find slave delay")
        exit()

    # find slave bitslip
    slave_bitslip = None
    for i in bitslip_range:
        wb.regs.slave_serdes_rx_bitslip_value.write(i)
        if wb.regs.slave_serdes_rx_pattern.read() == 0x003ff:
            slave_bitslip = i
            break
    if slave_bitslip is not None:
        print("slave bitslip: {:d}".format(slave_bitslip))
    else:
        print("unable to find slave bitslip")
        exit()

    # find master delay
    wb.regs.master_serdes_rx_delay_rst.write(1)
    wb.regs.master_serdes_rx_delay_inc.write(1)
    last_status = 0
    master_delay = None
    for i in delay_range:
        wb.regs.master_serdes_phase_detector_reset.write(1)
        status = wb.regs.master_serdes_phase_detector_status.read()
        if (last_status & too_late) and (status & too_early):
            master_delay = i
            break
        wb.regs.master_serdes_rx_delay_ce.write(1)
        last_status = status
    if master_delay is not None:
        print("master delay: {:d}".format(master_delay))
    else:
        print("unable to find master delay")
        exit()

    # find master bitslip
    master_bitslip = None
    for i in bitslip_range:
        wb.regs.master_serdes_rx_bitslip_value.write(i)
        if wb.regs.master_serdes_rx_pattern.read() == 0x003ff:
            master_bitslip = i
            break
    if master_bitslip is not None:
        print("master bitslip: {:d}".format(master_bitslip))
    else:
        print("unable to find master delay")
        exit()
  
    # disable square wave
    wb.regs.master_serdes_tx_produce_square_wave.write(0)
    wb.regs.slave_serdes_tx_produce_square_wave.write(0)

def analyzer():
    groups = {
        "master": 0,
        "slave":  1,
    }

    # disable square wave
    wb.regs.master_serdes_tx_produce_square_wave.write(1)
    wb.regs.slave_serdes_tx_produce_square_wave.write(1)
   
    analyzer = LiteScopeAnalyzerDriver(wb.regs, "analyzer", debug=True)
    analyzer.configure_group(groups["master"])
    analyzer.configure_trigger(cond={})  
    analyzer.run(offset=32, length=64)
    analyzer.wait_done()
    analyzer.upload()
    analyzer.save("dump.vcd")

if len(sys.argv) < 2:
    print("missing test (config or analyzer)")
    wb.close()
    exit()
if sys.argv[1] == "config":
    amc_rtm_link_config()
elif sys.argv[1] == "analyzer":
    analyzer()
else:
    raise ValueError

# # #

wb.close()
