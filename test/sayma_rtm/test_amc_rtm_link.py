#!/usr/bin/env python3

import sys
import time

from litex.soc.tools.remote import RemoteClient

from litescope.software.driver.analyzer import LiteScopeAnalyzerDriver

wb = RemoteClient(port=1235, debug=False)
wb.open()

# # #

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
    analyzer.configure_trigger(cond={"wishbone_access": 1})
    analyzer.run(offset=32, length=128)
    analyzer.wait_done()
    analyzer.upload()
    analyzer.save("dump.vcd")

if len(sys.argv) < 2:
    print("missing test (analyzer)")
    wb.close()
    exit()
if sys.argv[1] == "analyzer":
    analyzer()
else:
    raise ValueError

# # #

wb.close()
