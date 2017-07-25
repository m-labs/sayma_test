SAYMA_AMC_DIR=../build_sayma_amc/

include $(SAYMA_AMC_DIR)/software/include/generated/variables.mak
include $(MISOC_DIRECTORY)/software/common.mak

OBJECTS=isr.o main.o

all: firmware.bin

# pull in dependency info for *existing* .o files
-include $(OBJECTS:.o=.d)

%.bin: %.elf
	$(OBJCOPY) -O binary $< $@
	chmod -x $@

firmware.elf: $(OBJECTS)
	$(LD) $(LDFLAGS) \
		-T linker.ld \
		-N -o $@ \
		 $(SAYMA_AMC_DIR)/software/libbase/crt0-$(CPU).o \
		$(OBJECTS) \
		-L$(SAYMA_AMC_DIR)/software/libbase \
		-L$(SAYMA_AMC_DIR)/software/libcompiler-rt \
		-lbase-nofloat -lcompiler-rt
	chmod -x $@

main.o: main.c
	$(compile)

%.o: %.c
	$(compile)

%.o: %.S
	$(assemble)

clean:
	$(RM) $(OBJECTS) $(OBJECTS:.o=.d) firmware.elf firmware.bin .*~ *~

.PHONY: all main.o clean load
