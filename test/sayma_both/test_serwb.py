#!/usr/bin/env python3

import sys
import time

from litex.soc.tools.remote import RemoteClient

from litescope.software.driver.analyzer import LiteScopeAnalyzerDriver

wb_amc = RemoteClient(port=1234, csr_csv="../sayma_amc/csr.csv", debug=False)
wb_rtm = RemoteClient(port=1235, csr_csv="../sayma_rtm/csr.csv", debug=False)
wb_amc.open()
wb_rtm.open()

# # #

def seed_to_data(seed, random=True):
    if random:
        return (1664525*seed + 1013904223) & 0xffffffff
    else:
        return seed

def write_pattern(length):
    for i in range(length):
        wb_amc.write(0x20000000 + 4*i, seed_to_data(i))

def check_pattern(length, debug=False):
    errors = 0
    for i in range(length):
        error = 0
        read_data = wb_amc.read(0x20000000 + 4*i)
        if read_data != seed_to_data(i):
            error = 1
            if debug:
                print("{}: 0x{:08x}, 0x{:08x}   KO".format(i, read_data, seed_to_data(i)))
        else:
            if debug:
                print("{}: 0x{:08x}, 0x{:08x} OK".format(i, read_data, seed_to_data(i)))
        errors += error
    return errors


groups = {
    "init":             0,
    "serdes":           1,
    "etherbone_source": 2,
    "etherbone_sink":   3,
    "wishbone":         4
}

def analyzer():
    analyzer = LiteScopeAnalyzerDriver(wb_amc.regs, "analyzer", config_csv="../sayma_amc/analyzer.csv", debug=True)
    analyzer.configure_group(groups["wishbone"])
    analyzer.configure_trigger(cond={"wishbone_access" : 1})
    analyzer.run(offset=32, length=128)

    write_pattern(32)
    errors = check_pattern(32, debug=True)
    print("errors: {:d}".format(errors))

    analyzer.wait_done()
    analyzer.upload()
    analyzer.save("dump.vcd")


if len(sys.argv) < 2:
    print("missing test (init, wishbone, analyzer)")
    wb_amc.close()
    exit()

if sys.argv[1] == "init":
    wb_amc.regs.serwb_control_reset.write(1)
    timeout = 20
    while not (wb_amc.regs.serwb_control_ready.read() & 0x1 |
               wb_amc.regs.serwb_control_error.read() & 0x1 |
               timeout > 0):
        time.sleep(0.1)
        timeout -= 1
    time.sleep(2)
    print("AMC configuration")
    print("-----------------")
    print("delay_found: {:d}".format(wb_amc.regs.serwb_control_delay_found.read()))
    print("delay: {:d}".format(wb_amc.regs.serwb_control_delay.read()))
    print("bitslip: {:d}".format(wb_amc.regs.serwb_control_bitslip.read()))
    print("bitslip_found: {:d}".format(wb_amc.regs.serwb_control_bitslip_found.read()))
    print("ready: {:d}".format(wb_amc.regs.serwb_control_ready.read()))
    print("error: {:d}".format(wb_amc.regs.serwb_control_error.read()))
    print("")
    print("RTM configuration")
    print("-----------------")
    print("delay_found: {:d}".format(wb_rtm.regs.serwb_control_delay_found.read()))
    print("delay: {:d}".format(wb_rtm.regs.serwb_control_delay.read()))
    print("bitslip: {:d}".format(wb_rtm.regs.serwb_control_bitslip.read()))
    print("bitslip_found: {:d}".format(wb_rtm.regs.serwb_control_bitslip_found.read()))
    print("ready: {:d}".format(wb_rtm.regs.serwb_control_ready.read()))
    print("error: {:d}".format(wb_rtm.regs.serwb_control_error.read()))
elif sys.argv[1] == "wishbone":
    write_pattern(1024)
    errors = check_pattern(1024, debug=True)
    print("errors: {:d}".format(errors))

elif sys.argv[1] == "analyzer":
    analyzer()
else:
    raise ValueError

# # #

wb_amc.close()
wb_rtm.close()
