import sys
import re

hmc7043_config = []

f = open(sys.argv[1])
for l in f:
	m = re.search("dut.write\(0x([0-9a-fA-F]+), 0x([0-9a-fA-F]+)\)", l, re.I)
	if m is not None:
		hmc7043_config.append((m.group(1), m.group(2)))

print("hm7043_config = [")
for a, v in hmc7043_config:
	print("    (0x{:s}, 0x{:s}),".format(a.lower(), v.lower()))
print("]")
