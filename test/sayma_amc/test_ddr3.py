#!/usr/bin/env python3

import sys
import time

from misoc.tools.remote import RemoteClient

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

wb = RemoteClient(port=1234, debug=False)
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
wb.regs.sdram_dfii_pi0_address.write(0x000)
wb.regs.sdram_dfii_pi0_baddress.write(3)
wb.regs.sdram_dfii_pi0_command.write(dfii_command_ras|dfii_command_cas|dfii_command_we|dfii_command_cs)
wb.regs.sdram_dfii_pi0_command_issue.write(1)

# load mode register 1
wb.regs.sdram_dfii_pi0_address.write(0x006);
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

#

KB = 1024
MB = 1024*KB
GB = 1024*MB

#

def write_test(base, length, blocking=True):
    wb.regs.generator_reset.write(1)
    wb.regs.generator_reset.write(0)
    wb.regs.generator_base.write(base)
    wb.regs.generator_length.write(length)
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
    wb.regs.checker_base.write(base)
    wb.regs.checker_length.write(length)
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

def seed_to_data(seed, random=False):
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

def bruteforce_delay_finder():
    bitslip_range = range(0, 8)
    delay_range = range(0, 512)
    nmodules = 2
    nwords = 64
    use_bist = True
    debug = False
    
    dqs_delay = 40
    for module in range(nmodules):
        wb.regs.ddrphy_dly_sel.write(1<<module)
        wb.regs.ddrphy_wdly_dqs_rst.write(1)
    for delay in range(dqs_delay):
        for module in range(nmodules):
            wb.regs.ddrphy_dly_sel.write(1<<module)
            wb.regs.ddrphy_wdly_dqs_inc.write(1)
    
    for bitslip in bitslip_range:
        print("bitslip {:d}: |".format(bitslip), end="")
        for module in range(nmodules):
            wb.regs.ddrphy_dly_sel.write(1<<module)          
            wb.regs.ddrphy_rdly_dq_rst.write(1)
            for i in range(bitslip):
                wb.regs.ddrphy_rdly_dq_bitslip.write(1)
        for delay in delay_range:
            for module in range(nmodules):
                wb.regs.ddrphy_dly_sel.write(1<<module)
                wb.regs.ddrphy_rdly_dq_inc.write(1)
            if use_bist:
                write_test(0x00000000, 1*MB)
                speed, errors = read_test(0x00000000, 1*MB)
            else:
                write_pattern(nwords)
                errors = check_pattern(nwords, debug)
            if errors:
                print("..|", end="")
            else:
                print("{:02d}|".format(delay), end="")
            sys.stdout.flush()
        print("")

#

def bist(test_base, test_length, test_increment):
    bitslip = 0
    dqs_odelay = 40
    dq_idelay = 280
    nmodules = 2

    # reset delays
    for module in range(nmodules):
        wb.regs.ddrphy_dly_sel.write(1<<module)
        wb.regs.ddrphy_wdly_dqs_rst.write(1)
        wb.regs.ddrphy_rdly_dq_rst.write(1)

    # configure dqs delay
    for delay in range(dqs_odelay):
        for module in range(nmodules):
            wb.regs.ddrphy_dly_sel.write(1<<module)
            wb.regs.ddrphy_wdly_dqs_inc.write(1)

    # configure dq idelay
    for delay in range(dq_idelay):
        for module in range(nmodules):
            wb.regs.ddrphy_dly_sel.write(1<<module)
            wb.regs.ddrphy_rdly_dq_inc.write(1)

    # configure bitslip
    for module in range(nmodules):
        wb.regs.ddrphy_dly_sel.write(1<<module)
        for i in range(bitslip):
            wb.regs.ddrphy_rdly_dq_bitslip.write(1)


    # verify we are able to detect errors
    print("write base error check...", end="")
    write_speed = write_test(test_base + 128, test_length)
    read_speed, read_errors = read_test(test_base, test_length)
    print("ok") if read_errors else print("ko")
    
    print("write length error check...", end="")
    write_speed = write_test(test_base, test_length - 128)
    read_speed, read_errors = read_test(test_base, test_length)
    print("ok") if read_errors else print("ko")
    
    print("read base error check...", end="")
    write_speed = write_test(test_base, test_length)
    read_speed, read_errors = read_test(test_base + 128, test_length)
    print("ok") if read_errors else print("ko")
    
    print("read length error check...", end="")
    write_speed = write_test(test_base, test_length)
    read_speed, read_errors = read_test(test_base, test_length + 128)
    print("ok") if read_errors else print("ko")
    
    #
    
    tested_errors = 0
    tested_length = 0
    
    i = 0
    while True:
        if i%10 == 0:
            print("WR_SPEED(Gbps) RD_SPEED(Gbps) TESTED(MB)      ERRORS")
        base = test_base + test_increment*i
        length = test_length
        write_speed = write_test(base, length)
        read_speed, read_errors = read_test(base, length)
        tested_errors = tested_errors + read_errors
        tested_length = tested_length + test_length
        print("{:14.2f} {:14.2f} {:9d} {:12d}".format(
            8*write_speed/GB,
            8*read_speed/GB,
            tested_length//MB,
            tested_errors))
        i += 1

#

def analyzer():
    groups = {
        "dfi_phase0": 0,
        "dfi_phase1": 1,
        "dfi_phase2": 2,
        "dfi_phase3": 3
    }
    
    analyzer = LiteScopeAnalyzerDriver(wb.regs, "analyzer", debug=True)
    analyzer.configure_group(groups["dfi_phase0"])
    analyzer.configure_trigger(cond={})
    
    write_test(0x00000000, 1024*MB, False)
    read_test(0x00000000, 1024*MB, False)
    
    analyzer.run(offset=32, length=64)
    
    analyzer.wait_done()
    analyzer.upload()
    analyzer.save("dump.vcd")

if len(sys.argv) < 2:
    print("missing test (delay or bist or analyzer)")
    wb.close()
    exit()
if sys.argv[1] == "delay":
    bruteforce_delay_finder()
elif sys.argv[1] == "bist":
    bist(0x00000000, 128*MB, 0)
elif sys.argv[1] == "analyzer":
    analyzer()
else:
    raise ValueError

# # #

wb.close()
