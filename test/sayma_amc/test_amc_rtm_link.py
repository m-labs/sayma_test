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
                print("{}: 0x{:08x}, 0x{:08x} KO".format(i, read_data, seed_to_data(i)))
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
    analyzer.configure_group(groups["serdes"])
    analyzer.configure_trigger(cond={"wishbone_access" : 1})  
    analyzer.run(offset=32, length=128)
    
    wb.write(0x20000000, 0x12345678)

    analyzer.wait_done()
    analyzer.upload()
    analyzer.save("dump.vcd")


if len(sys.argv) < 2:
    print("missing test (analyzer)")
    wb.close()
    exit()
if sys.argv[1] == "analyzer":
    analyzer()
elif sys.argv[1] == "wishbone":
    write_pattern(32)
    errors = check_pattern(32, debug=True)
    print("errors: {:d}".format(errors))
else:
    raise ValueError

# # #

wb.close()
