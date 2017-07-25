#!/usr/bin/env python3

import sys
import time

from litex.soc.tools.remote import RemoteClient

from litescope.software.driver.analyzer import LiteScopeAnalyzerDriver

wb = RemoteClient(port=1234, debug=False)
wb.open()

# # #

def seed_to_data(seed, random=True):
    if random:
        return (1664525*seed + 1013904223) & 0xffffffff
    else:
        return seed

def write_pattern(length):
    for i in range(length):
        wb.write(0x20000000 + 4*i, seed_to_data(i))

def check_pattern(length, debug=False):
    errors = 0
    for i in range(length):
        error = 0
        read_data = wb.read(0x20000000 + 4*i)
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
    analyzer = LiteScopeAnalyzerDriver(wb.regs, "analyzer", debug=True)
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
    wb.close()
    exit()

if sys.argv[1] == "init":
    wb.regs.amc_rtm_link_control_reset.write(1)
    while not (wb.regs.amc_rtm_link_control_ready.read() & 0x1):
        time.sleep(0.1)
    print("delay_min_found: {:d}".format(wb.regs.amc_rtm_link_control_delay_min_found.read()))
    print("delay_min: {:d}".format(wb.regs.amc_rtm_link_control_delay_min.read()))
    print("delay_max_found: {:d}".format(wb.regs.amc_rtm_link_control_delay_max_found.read()))
    print("delay_max: {:d}".format(wb.regs.amc_rtm_link_control_delay_max.read()))
    print("delay: {:d}".format(wb.regs.amc_rtm_link_control_delay.read()))
    print("bitslip: {:d}".format(wb.regs.amc_rtm_link_control_bitslip.read()))
    print("ready: {:d}".format(wb.regs.amc_rtm_link_control_ready.read()))
elif sys.argv[1] == "wishbone":
    write_pattern(1024)
    errors = check_pattern(1024, debug=False)
    print("errors: {:d}".format(errors))

elif sys.argv[1] == "analyzer":
    analyzer()
else:
    raise ValueError

# # #

wb.close()
