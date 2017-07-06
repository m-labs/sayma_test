#!/usr/bin/env python3

import time

from litex.soc.tools.remote import RemoteClient


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


# configure bitslip and delay
# TODO

#

KB = 1024
MB = 1024*KB
GB = 1024*MB

#

def write_test(base, length):
    wb.regs.generator_reset.write(1)
    wb.regs.generator_reset.write(0)
    wb.regs.generator_base.write(base) # FIXME in bytes
    wb.regs.generator_length.write((length*8)//128) # FIXME in bytes
    wb.regs.generator_start.write(1)
    while(not wb.regs.generator_done.read()):
        pass
    ticks = wb.regs.generator_ticks.read()
    speed = wb.constants.config_clock_frequency*length/ticks
    return speed

def read_test(base, length):
    wb.regs.checker_reset.write(1)
    wb.regs.checker_reset.write(0)
    wb.regs.checker_base.write(base) # FIXME in bytes
    wb.regs.checker_length.write((length*8)//128) # FIXME in bytes
    start = time.time()
    wb.regs.checker_start.write(1)
    while(not wb.regs.checker_done.read()):
        pass
    ticks = wb.regs.checker_ticks.read()
    speed = wb.constants.config_clock_frequency*length/ticks
    errors = wb.regs.checker_errors.read()
    return speed, errors

#

test_base = 0x00000000
test_increment = 128
test_length = 128*MB

#

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

# # #

wb.close()
