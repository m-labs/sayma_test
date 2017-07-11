#!/usr/bin/env python3

import sys

from litex.soc.tools.remote import RemoteClient

from litescope.software.driver.analyzer import LiteScopeAnalyzerDriver

wb = RemoteClient(debug=False)
wb.open()

# # #

def analyzer():
    groups = {
        "master": 0,
        "slave":  1,
    }
    
    analyzer = LiteScopeAnalyzerDriver(wb.regs, "analyzer", debug=True)
    analyzer.configure_group(groups["master"])
    analyzer.configure_trigger(cond={})  
    analyzer.run(offset=32, length=256)
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
