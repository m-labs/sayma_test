#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <irq.h>
#include <uart.h>
#include <console.h>

#include <generated/csr.h>

static char *readstr(void)
{
	char c[2];
	static char s[64];
	static int ptr = 0;

	if(readchar_nonblock()) {
		c[0] = readchar();
		c[1] = 0;
		switch(c[0]) {
			case 0x7f:
			case 0x08:
				if(ptr > 0) {
					ptr--;
					putsnonl("\x08 \x08");
				}
				break;
			case 0x07:
				break;
			case '\r':
			case '\n':
				s[ptr] = 0x00;
				putsnonl("\n");
				ptr = 0;
				return s;
			default:
				if(ptr >= (sizeof(s) - 1))
					break;
				putsnonl(c);
				s[ptr] = c[0];
				ptr++;
				break;
		}
	}

	return NULL;
}

static char *get_token(char **str)
{
	char *c, *d;

	c = (char *)strchr(*str, ' ');
	if(c == NULL) {
		d = *str;
		*str = *str+strlen(*str);
		return d;
	}
	*c = 0;
	d = *str;
	*str = c+1;
	return d;
}

static void prompt(void)
{
	printf("RUNTIME>");
}

static void help(void)
{
	puts("Available commands:");
	puts("help              - this command");
	puts("reboot            - reboot CPU");
	puts("amc_rtm_link_init - (re)initialize AMC/RTM link");
	puts("amc_rtm_link_test - test AMC/RTM link");
	puts("amc_rtm_link_dump - dump AMC/RTM memorylink");
}

static void reboot(void)
{
	asm("call r0");
}

static void busy_wait(unsigned int ds)
{
	timer0_en_write(0);
	timer0_reload_write(0);
	timer0_load_write(CONFIG_CLOCK_FREQUENCY/10*ds);
	timer0_en_write(1);
	timer0_update_value_write(1);
	while(timer0_value_read()) {
		timer0_update_value_write(1);
	}
}

static void amc_rtm_link_init(void)
{
	int timeout = 10;

	amc_rtm_link_control_reset_write(1);
	while (((amc_rtm_link_control_ready_read() & 0x1) == 0) &
		   ((amc_rtm_link_control_error_read() & 0x1) == 0) &
		   (timeout > 0)) {
		busy_wait(1);
	    timeout--;
	}

	printf("delay_found: %d\n"
		   "delay: %d\n"
		   "bitslip_found: %d\n"
		   "bitslip: %d\n"
		   "ready: %d\n"
		   "error: %d\n",
		    amc_rtm_link_control_delay_found_read(),
		    amc_rtm_link_control_delay_read(),
		    amc_rtm_link_control_bitslip_found_read(),
		    amc_rtm_link_control_bitslip_read(),
		    amc_rtm_link_control_ready_read(),
		    amc_rtm_link_control_error_read());
}

#define AMC_RTM_LINK_RAM_BASE 0x20000000
#define AMC_RTM_LINK_RAM_SIZE 0x00002000

static unsigned int seed_to_data_32(unsigned int seed, int random)
{
	if (random)
		return 1664525*seed + 1013904223;
	else
		return seed + 1;
}

static void amc_rtm_link_test(void)
{
	volatile unsigned int *array = (unsigned int *)AMC_RTM_LINK_RAM_BASE;
	int i, errors;
	unsigned int seed_32;

	errors = 0;
	seed_32 = 0;

	for(i=0;i<AMC_RTM_LINK_RAM_SIZE/4;i++) {
		seed_32 = seed_to_data_32(seed_32, 1);
		array[i] = seed_32;
	}

	seed_32 = 0;
	flush_cpu_dcache();
	for(i=0;i<AMC_RTM_LINK_RAM_SIZE/4;i++) {
		seed_32 = seed_to_data_32(seed_32, 1);
		if(array[i] != seed_32)
			errors++;
	}

	printf("errors: %d/%d\n", errors, AMC_RTM_LINK_RAM_SIZE/4);
}

#define NUMBER_OF_BYTES_ON_A_LINE 16
static void dump_bytes(unsigned int *ptr, int count, unsigned addr)
{
	char *data = (char *)ptr;
	int line_bytes = 0, i = 0;

	putsnonl("Memory dump:");
	while(count > 0){
		line_bytes =
			(count > NUMBER_OF_BYTES_ON_A_LINE)?
				NUMBER_OF_BYTES_ON_A_LINE : count;

		printf("\n0x%08x  ", addr);
		for(i=0;i<line_bytes;i++)
			printf("%02x ", *(unsigned char *)(data+i));

		for(;i<NUMBER_OF_BYTES_ON_A_LINE;i++)
			printf("   ");

		printf(" ");

		for(i=0;i<line_bytes;i++) {
			if((*(data+i) < 0x20) || (*(data+i) > 0x7e))
				printf(".");
			else
				printf("%c", *(data+i));
		}

		for(;i<NUMBER_OF_BYTES_ON_A_LINE;i++)
			printf(" ");

		data += (char)line_bytes;
		count -= line_bytes;
		addr += line_bytes;
	}
	printf("\n");
}

static void amc_rtm_link_dump(void)
{
	dump_bytes(AMC_RTM_LINK_RAM_BASE, 8192, (unsigned)AMC_RTM_LINK_RAM_BASE);
}

static void console_service(void)
{
	char *str;
	char *token;

	str = readstr();
	if(str == NULL) return;
	token = get_token(&str);
	if(strcmp(token, "help") == 0)
		help();
	else if(strcmp(token, "reboot") == 0)
		reboot();
	else if(strcmp(token, "amc_rtm_link_init") == 0)
		amc_rtm_link_init();
	else if(strcmp(token, "amc_rtm_link_test") == 0)
		amc_rtm_link_test();
	else if(strcmp(token, "amc_rtm_link_dump") == 0)
		amc_rtm_link_dump();	
	prompt();
}

int main(void)
{
	irq_setmask(0);
	irq_setie(1);
	uart_init();

	puts("\nSayma AMC CPU testing software built "__DATE__" "__TIME__);
	prompt();

	while(1) {
		console_service();
	}

	return 0;
}


