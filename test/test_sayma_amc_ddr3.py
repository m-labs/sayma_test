#!/usr/bin/env python3

import time

from litex.soc.tools.remote import RemoteClient

from litescope.software.driver.analyzer import LiteScopeAnalyzerDriver

# DDR3 init and test for sayma ddr3 test design

dfii_control_sel     = 0x01
dfii_control_cke     = 0x02
dfii_control_odt     = 0x04
dfii_control_reset_n = 0x08

dfii_command_cs     = 0x01
dfii_command_we     = 0x02
dfii_command_cas    = 0x04
dfii_command_ras    = 0x08
dfii_command_wrdata = 0x10
dfii_command_rddata = 0x20

wb = RemoteClient(debug=False)
wb.open()

# # #

wb.regs.sdram_dfii_control.write(0)

# release reset
wb.regs.sdram_dfii_pi0_address.write(0x0)
wb.regs.sdram_dfii_pi0_baddress.write(0)
wb.regs.sdram_dfii_control.write(dfii_control_odt|dfii_control_reset_n)
time.sleep(0.1)

# bring cke high
wb.regs.sdram_dfii_pi0_address.write(0x0)
wb.regs.sdram_dfii_pi0_baddress.write(0)
wb.regs.sdram_dfii_control.write(dfii_control_cke|dfii_control_odt|dfii_control_reset_n)
time.sleep(0.1)

# load mode register 2
wb.regs.sdram_dfii_pi0_address.write(0x408)
wb.regs.sdram_dfii_pi0_baddress.write(2)
wb.regs.sdram_dfii_pi0_command.write(dfii_command_ras|dfii_command_cas|dfii_command_we|dfii_command_cs)
wb.regs.sdram_dfii_pi0_command_issue.write(1)

# load mode register 3
wb.regs.sdram_dfii_pi0_address.write(0x0)
wb.regs.sdram_dfii_pi0_baddress.write(3)
wb.regs.sdram_dfii_pi0_command.write(dfii_command_ras|dfii_command_cas|dfii_command_we|dfii_command_cs)
wb.regs.sdram_dfii_pi0_command_issue.write(1)

# load mode register 1
wb.regs.sdram_dfii_pi0_address.write(0x6);
wb.regs.sdram_dfii_pi0_baddress.write(1);
wb.regs.sdram_dfii_pi0_command.write(dfii_command_ras|dfii_command_cas|dfii_command_we|dfii_command_cs)
wb.regs.sdram_dfii_pi0_command_issue.write(1)

# load mode register 0, cl=7, bl=8
wb.regs.sdram_dfii_pi0_address.write(0x930);
wb.regs.sdram_dfii_pi0_baddress.write(0);
wb.regs.sdram_dfii_pi0_command.write(dfii_command_ras|dfii_command_cas|dfii_command_we|dfii_command_cs)
wb.regs.sdram_dfii_pi0_command_issue.write(1)
time.sleep(0.1)

# zq calibration
wb.regs.sdram_dfii_pi0_address.write(0x400);
wb.regs.sdram_dfii_pi0_baddress.write(0);
wb.regs.sdram_dfii_pi0_command.write(dfii_command_we|dfii_command_cs)
wb.regs.sdram_dfii_pi0_command_issue.write(1)
time.sleep(0.1)

# hardware control
wb.regs.sdram_dfii_control.write(dfii_control_sel)

def seed_to_data(seed, random=True):
    if random:
        return (1664525*seed + 1013904223) & 0xffffffff
    else:
        return seed

def write_pattern(length):
    for i in range(length):
        wb.write(wb.mems.main_ram.base + 4*i, seed_to_data(i))

def check_pattern(length, debug=False):
    errors = 0
    for i in range(length):
        error = 0
        if wb.read(wb.mems.main_ram.base + 4*i) != seed_to_data(i):
            error = 1
            if debug:
                print("{}: 0x{:08x}, 0x{:08x} KO".format(i, wb.read(wb.mems.main_ram.base + 4*i), seed_to_data(i)))
        else:
            if debug:
                print("{}: 0x{:08x}, 0x{:08x} OK".format(i, wb.read(wb.mems.main_ram.base + 4*i), seed_to_data(i)))
        errors += error
    return errors

#

KB = 1024
MB = 1024*KB
GB = 1024*MB

#

def write_test(base, length, blocking=True):
    wb.regs.generator_reset.write(1)
    wb.regs.generator_reset.write(0)
    wb.regs.generator_base.write(base) # FIXME in bytes
    wb.regs.generator_length.write((length*8)//128) # FIXME in bytes
    wb.regs.generator_start.write(1)
    if blocking:
        while(not wb.regs.generator_done.read()):
            pass
        ticks = wb.regs.generator_ticks.read()
        speed = wb.constants.config_clock_frequency*length/ticks
        return speed
    else:
        return None

def read_test(base, length, blocking=True):
    wb.regs.checker_reset.write(1)
    wb.regs.checker_reset.write(0)
    wb.regs.checker_base.write(base) # FIXME in bytes
    wb.regs.checker_length.write((length*8)//128) # FIXME in bytes
    start = time.time()
    wb.regs.checker_start.write(1)
    if blocking:
        while(not wb.regs.checker_done.read()):
            pass
        ticks = wb.regs.checker_ticks.read()
        speed = wb.constants.config_clock_frequency*length/ticks
        errors = wb.regs.checker_errors.read()
        return speed, errors
    else:
        return None, None

#

groups = {
    "dfi_phase0": 0,
    "dfi_phase1": 1,
    "dfi_phase2": 2,
    "dfi_phase3": 3
}

analyzer = LiteScopeAnalyzerDriver(wb.regs, "analyzer", debug=True)
analyzer.configure_group(groups["dfi_phase0"])
analyzer.configure_trigger(cond={})

# configure bitslip (check if working with analyzer)
bitslip = 0
for i in range(32//8):
    wb.regs.ddrphy_dly_sel.write(1<<i)
    wb.regs.ddrphy_rdly_dq_bitslip.write(bitslip)

write_test(0x00000000, 1024*MB, False)
#read_test(0x00000000, 1024*MB, False)

analyzer.run(offset=32, length=64)

analyzer.wait_done()
analyzer.upload()
analyzer.save("dump.vcd")


# # #

wb.close()
