#!/usr/bin/env python3

import sys
import time

from litex.soc.tools.remote import RemoteClient

from litescope.software.driver.analyzer import LiteScopeAnalyzerDriver

wb = RemoteClient(port=1235, debug=False)
wb.open()

# # #

def analyzer():
    analyzer = LiteScopeAnalyzerDriver(wb.regs, "analyzer", debug=True)
    #analyzer.configure_trigger(cond={"rx_pattern0" : 0})
    analyzer.configure_trigger(cond={})
    analyzer.run(offset=32, length=64)
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
