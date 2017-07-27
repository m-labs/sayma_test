# config mapping
OFFLINE      = (1 << 0)
CS_POLARITY  = (1 << 3)
CLK_POLARITY = (1 << 4)
CLK_PHASE    = (1 << 5)
LSB_FIRST    = (1 << 6)
HALF_DUPLEX  = (1 << 7)
DIV_READ     = (1 << 16)
DIV_WRITE    = (1 << 24)

# xfer mapping
WRITE_LENGTH = (1 << 16)
READ_LENGTH  = (1 << 24)


class HMC830:
    def __init__(self, regs):
        self.regs = regs

    def configure(self):
        self.regs.hmc_spi_sel_out.write(0)
        config = 0*OFFLINE
        config |= 0*CS_POLARITY | 0*CLK_POLARITY | 0*CLK_PHASE
        config |= 0*LSB_FIRST | 0*HALF_DUPLEX
        config |= 8*DIV_READ | 8*DIV_WRITE
        self.regs.hmc_spi_config.write(config)

    def write(self, addr, data):
        self.configure()
        cmd = (0 << 6) | (addr & 0x3f)
        val = (cmd << 24) | (data & 0xffffff)
        self.regs.hmc_spi_xfer.write(0b01 | 32*WRITE_LENGTH)
        self.regs.hmc_spi_mosi_data.write(val << (32-31))
        self.regs.hmc_spi_start.write(1)
        while (self.regs.hmc_spi_pending.read() & 0x1):
            pass

    def read(self, addr):
        self.configure()
        cmd = (1 << 6) | (addr & 0x3f)
        val = (cmd << 24)
        self.regs.hmc_spi_xfer.write(0b01 | 7*WRITE_LENGTH | 25*READ_LENGTH)
        self.regs.hmc_spi_mosi_data.write(val << (32-31))
        self.regs.hmc_spi_start.write(1)
        while (self.regs.hmc_spi_pending.read() & 0x1):
            pass
        return self.regs.hmc_spi_miso_data.read() & 0xffffff

    def check_presence(self):
        errors = 0
        errors += self.read(0) != 0xa7975
        return errors == 0


class HMC7043:
    def __init__(self, regs):
        self.regs = regs

    def configure(self):
        self.regs.hmc_spi_sel_out.write(1)
        config = 0*OFFLINE
        config |= 0*CS_POLARITY | 0*CLK_POLARITY | 0*CLK_PHASE
        config |= 0*LSB_FIRST | 1*HALF_DUPLEX
        config |= 8*DIV_READ | 8*DIV_WRITE
        self.regs.hmc_spi_config.write(config)

    def write(self, addr, data):
        self.configure()
        cmd = (0 << 15) | (addr & 0x1fff)
        val = (cmd << 8) | (data)
        self.regs.hmc_spi_xfer.write(0b01 | 24*WRITE_LENGTH)
        self.regs.hmc_spi_mosi_data.write(val << (32-24))
        self.regs.hmc_spi_start.write(1)
        while (self.regs.hmc_spi_pending.read() & 0x1):
            pass

    def read(self, addr):
        self.configure()
        cmd = (1 << 15) | (addr & 0x1fff)
        val = (cmd << 8)
        self.regs.hmc_spi_xfer.write(0b01 | 16*WRITE_LENGTH | 8*READ_LENGTH)
        self.regs.hmc_spi_mosi_data.write(val << (32-24))
        self.regs.hmc_spi_start.write(1)
        while (self.regs.hmc_spi_pending.read() & 0x1):
            pass
        return self.regs.hmc_spi_miso_data.read() & 0xff

    def check_presence(self):
        errors = 0
        errors += self.read(0x78) != 0xf1
        errors += self.read(0x79) != 0x79
        errors += self.read(0x7a) != 0x04
        return errors == 0
