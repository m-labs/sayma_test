#!/usr/bin/env python3

import sys
import time

from litex.soc.tools.remote import RemoteClient

from litescope.software.driver.analyzer import LiteScopeAnalyzerDriver

wb = RemoteClient(port=1235, debug=False)
wb.open()

# # #

too_late = 0x1
too_early = 0x2

def amc_rtm_link_phase_detector(debug=False):
    # find slave delay
    print("slave delay:")
    wb.regs.slave_serdes_rx_delay_rst.write(1)
    slave_delay = None
    for i in range(32):
        wb.regs.slave_serdes_phase_detector_reset.write(1)
        status = wb.regs.slave_serdes_phase_detector_status.read() 
        if (status & too_early):
            print("-", end="")
        elif (status & too_late):
            print("+", end="")
        else:
            print(".", end="")
        sys.stdout.flush()
        wb.regs.slave_serdes_rx_delay_inc.write(1)
        wb.regs.slave_serdes_rx_delay_ce.write(1)
        if debug:
            print("s: {:d} / m: {:d}".format(
                wb.regs.slave_serdes_rx_delay_m_cntvalueout.read(),
                wb.regs.slave_serdes_rx_delay_s_cntvalueout.read()))
    print("")


def amc_rtm_link_calibration():
    # parameters
    bitslip_range = range(0, 20)
    delay_range = range(0, 32)

    # find slave delay
    wb.regs.slave_serdes_rx_delay_rst.write(1)
    wb.regs.slave_serdes_rx_delay_inc.write(1)
    last_status = 0
    slave_delay = None
    for i in delay_range:
        wb.regs.slave_serdes_phase_detector_reset.write(1)
        status = wb.regs.slave_serdes_phase_detector_status.read()
        if (last_status & too_early) and (status & too_late):
            slave_delay = i
            break
        wb.regs.slave_serdes_rx_delay_ce.write(1)
        last_status = status
    if slave_delay is not None:
        print("slave delay: {:d}".format(slave_delay))
    else:
        print("slave delay: not found")

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
        print("slave bitslip: not found")

def analyzer():
    analyzer = LiteScopeAnalyzerDriver(wb.regs, "analyzer", debug=True)
    analyzer.configure_trigger(cond={})  
    analyzer.run(offset=32, length=64)
    analyzer.wait_done()
    analyzer.upload()
    analyzer.save("dump.vcd")

if len(sys.argv) < 2:
    print("missing test (phase_detector, calibration, analyzer, square_wave)")
    wb.close()
    exit()
if sys.argv[1] == "phase_detector":
    amc_rtm_link_phase_detector()
elif sys.argv[1] == "calibration":
    amc_rtm_link_calibration()
elif sys.argv[1] == "analyzer":
    analyzer()
elif sys.argv[1] == "square_wave":
    enable = int(sys.argv[2])
    wb.regs.slave_serdes_tx_produce_square_wave.write(enable)
else:
    raise ValueError

# # #

wb.close()
