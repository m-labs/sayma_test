import time

from litejesd204b.transport import seed_to_data

from libbase.ad9154_regs import *

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

class AD9154SPI:
    def __init__(self, regs):
        self.regs = regs

    def configure(self):
        config = 0*OFFLINE
        config |= 0*CS_POLARITY | 0*CLK_POLARITY | 0*CLK_PHASE
        config |= 0*LSB_FIRST | 0*HALF_DUPLEX
        config |= 8*DIV_READ | 8*DIV_WRITE
        self.regs.spi_config.write(config)

    def write(self, addr, byte):
        self.configure()
        cmd = (0 << 15) | (addr & 0x7ff)
        val = (cmd << 8) | (byte & 0xff)
        self.regs.spi_xfer.write(0b01 | 24*WRITE_LENGTH)
        self.regs.spi_mosi_data.write(val << (32-24))
        self.regs.spi_start.write(1)
        while (self.regs.spi_pending.read() & 0x1):
            pass

    def read(self, addr):
        self.configure()
        cmd = (1 << 15) | (addr & 0x7ff)
        val = (cmd << 8)
        self.regs.spi_xfer.write(0b01 | 16*WRITE_LENGTH | 8*READ_LENGTH)
        self.regs.spi_mosi_data.write(val << (32-24))
        self.regs.spi_start.write(1)
        while (self.regs.spi_pending.read() & 0x1):
            pass
        return self.regs.spi_miso_data.read() & 0xff

class AD9154(AD9154SPI):
    def __init__(self, regs):
        AD9154SPI.__init__(self, regs)

    def check_presence(self):
        errors = 0
        errors += self.read(AD9154_CHIPTYPE) != 0x4
        errors += self.read(AD9154_PRODIDL) != 0x54
        errors += self.read(AD9154_PRODIDH) != 0x91
        return errors == 0

    def reset(self):
        self.write(AD9154_SPI_INTFCONFA,
            AD9154_SOFTRESET_SET(1) |
            AD9154_LSBFIRST_SET(0) |
            AD9154_ADDRINC_SET(0) |
            AD9154_SDOACTIVE_SET(1))
        self.write(AD9154_SPI_INTFCONFA,
            AD9154_LSBFIRST_SET(0) |
            AD9154_ADDRINC_SET(0) |
            AD9154_SDOACTIVE_SET(1))

    def startup(self, jesd_settings, linerate, physical_lanes=0xf0):
        # follow device startup guide (p25 of ad9154 datasheet)

        logical_lanes = {
            0xf0 : 0x0f,
            0x0f : 0x0f,
            0xff : 0xff
        }[physical_lanes]

        # see ad9154 fmc schematic...
        polarity_lanes = {
            0xf0 : 0x00,
            0x0f : 0x0f,
            0xff : 0x0f
        }[physical_lanes]

        # step 1: start up the dac

        # power-up and dac initialization setttings (table 15)
        self.write(AD9154_PWRCNTRL0, # enable the 4 dacs
            AD9154_PD_DAC0_SET(0) | AD9154_PD_DAC1_SET(0) |
            AD9154_PD_DAC2_SET(0) | AD9154_PD_DAC3_SET(0) |
            AD9154_PD_BG_SET(0))
        self.write(AD9154_CLKCFG0,
            AD9154_REF_CLKDIV_EN_SET(0) | AD9154_RF_SYNC_EN_SET(1) |
            AD9154_DUTY_EN_SET(1) | AD9154_PD_CLK_REC_SET(0) |
            AD9154_PD_SERDES_PCLK_SET(0) | AD9154_PD_CLK_DIG_SET(0) |
            AD9154_PD_CLK23_SET(0) | AD9154_PD_CLK01_SET(0))
        self.write(AD9154_SYSREF_ACTRL0, # jesd204b subclass 1
            AD9154_HYS_CNTRL1_SET(0) | AD9154_SYSREF_RISE_SET(0) |
            AD9154_HYS_ON_SET(0) | AD9154_PD_SYSREF_BUFFER_SET(0))

        self.write(AD9154_IRQEN_STATUSMODE0,
            AD9154_IRQEN_SMODE_LANEFIFOERR_SET(1) |
            AD9154_IRQEN_SMODE_SERPLLLOCK_SET(1) |
            AD9154_IRQEN_SMODE_SERPLLLOST_SET(1) |
            AD9154_IRQEN_SMODE_DACPLLLOCK_SET(1) |
            AD9154_IRQEN_SMODE_DACPLLLOST_SET(1))

        # required device configurations (table 16)
        self.write(AD9154_DEVICE_CONFIG_REG_0,  0x8b)  # magic
        self.write(AD9154_DEVICE_CONFIG_REG_1,  0x01)  # magic
        self.write(AD9154_DEVICE_CONFIG_REG_2, 0x01)   # magic

        self.write(AD9154_SPI_PAGEINDX, 0x3) # A and B dual

        # do not use dac pll for now (table 17)

        # step 2: digital datapath

        self.write(AD9154_INTERP_MODE, 0x00) # 1x
        self.write(AD9154_DATA_FORMAT, AD9154_BINARY_FORMAT_SET(0)) # s16
        self.write(AD9154_DATAPATH_CTRL,
                AD9154_I_TO_Q_SET(0) | AD9154_SEL_SIDEBAND_SET(0) |
                AD9154_MODULATION_TYPE_SET(0) | AD9154_PHASE_ADJ_ENABLE_SET(0) |
                AD9154_DIG_GAIN_ENABLE_SET(1) | AD9154_INVSINC_ENABLE_SET(0))
        self.write(AD9154_IDAC_DIG_GAIN0, 0x00)
        self.write(AD9154_IDAC_DIG_GAIN1, 0x8)
        self.write(AD9154_QDAC_DIG_GAIN0, 0x00)
        self.write(AD9154_QDAC_DIG_GAIN1, 0x8)
        self.write(AD9154_DC_OFFSET_CTRL, 0)
        self.write(AD9154_IPATH_DC_OFFSET_1PART0, 0x00)
        self.write(AD9154_IPATH_DC_OFFSET_1PART1, 0x00)
        self.write(AD9154_IPATH_DC_OFFSET_2PART, 0x00)
        self.write(AD9154_QPATH_DC_OFFSET_1PART0, 0x00)
        self.write(AD9154_QPATH_DC_OFFSET_1PART1, 0x00)
        self.write(AD9154_QPATH_DC_OFFSET_2PART, 0x00)
        self.write(AD9154_PHASE_ADJ0, 0)
        self.write(AD9154_PHASE_ADJ1, 0)
        self.write(AD9154_GROUP_DLY, AD9154_COARSE_GROUP_DELAY_SET(0x8) |
                AD9154_GROUP_DELAY_RESERVED_SET(0x8))
        self.write(AD9154_GROUPDELAY_COMP_BYP,
                AD9154_GROUPCOMP_BYPQ_SET(1) |
                AD9154_GROUPCOMP_BYPI_SET(1))
        self.write(AD9154_GROUPDELAY_COMP_I, 0)
        self.write(AD9154_GROUPDELAY_COMP_Q, 0)
        self.write(AD9154_PDP_AVG_TIME, AD9154_PDP_ENABLE_SET(0))

        # step 3: transport layer

        # ad9154 mode 2:
        # M=4 converters
        # L=4 lanes
        # S=1 samples/converter and /frame
        # F=2 octets/lane and /frame
        # K=16 frames/multiframe (or 32)
        # HD=0 high density
        # N=16 bits/converter
        # NB=16 bits/sample
        # 1x interpolation
        # pclock=125MHz/250MHz
        # fclock=250MHz/500MHz
        # fdata=250MHz/500MHz
        # fline=5GHz/10GHz

        # transport layer settings (table 20)
        chksum = jesd_settings.get_configuration_checksum()

        self.write(AD9154_MASTER_PD, 0x00)
        self.write(AD9154_PHY_PD, ~physical_lanes) # power down physical lanes
        self.write(AD9154_GENERAL_JRX_CTRL_0,
            AD9154_LINK_EN_SET(0) | AD9154_LINK_PAGE_SET(0) |
            AD9154_LINK_MODE_SET(0) | AD9154_CHECKSUM_MODE_SET(0))
        self.write(AD9154_ILS_DID, jesd_settings.did)
        self.write(AD9154_ILS_BID, jesd_settings.bid)
        self.write(AD9154_ILS_LID0, 0x00)
        self.write(AD9154_ILS_SCR_L,
            AD9154_L_1_SET(jesd_settings.phy.l-1) |
            AD9154_SCR_SET(1))
        self.write(AD9154_ILS_F, jesd_settings.transport.f-1)
        self.write(AD9154_ILS_K, jesd_settings.transport.k-1)
        self.write(AD9154_ILS_M, jesd_settings.phy.m-1)
        self.write(AD9154_ILS_CS_N,
            AD9154_N_1_SET(jesd_settings.phy.n-1) |
            AD9154_CS_SET(0))
        self.write(AD9154_ILS_NP,
            AD9154_NP_1_SET(jesd_settings.phy.np-1) |
            AD9154_SUBCLASSV_SET(1))
        self.write(AD9154_ILS_S,
            AD9154_S_1_SET(jesd_settings.transport.s-1) |
            AD9154_JESDV_SET(1))
        self.write(AD9154_ILS_HD_CF,
            AD9154_HD_SET(0) | AD9154_CF_SET(0))
        self.write(AD9154_ILS_CHECKSUM, chksum)
        self.write(AD9154_LANEDESKEW, logical_lanes) # deskew logical lanes
        self.write(AD9154_CTRLREG1, jesd_settings.transport.f)
        self.write(AD9154_LANEENABLE, logical_lanes) # enable logical lanes

        # step 4: physical layer

        # device configurations and physical layer settings (table 21)
        self.write(AD9154_TERM_BLK1_CTRLREG0, 0x01)
        self.write(AD9154_TERM_BLK2_CTRLREG0, 0x01)
        self.write(AD9154_SERDES_SPI_REG, 0x01)
        self.write(AD9154_CDR_OPERATING_MODE_REG_0,
            AD9154_CDR_OVERSAMP_SET(0) |
            AD9154_CDR_RESERVED_SET(2) |
            AD9154_ENHALFRATE_SET(linerate > 5.65e9))
        self.write(AD9154_CDR_RESET, 0)
        self.write(AD9154_CDR_RESET, 1)
        self.write(AD9154_REF_CLK_DIVIDER_LDO,
            AD9154_SPI_CDR_OVERSAMP_SET(linerate < 5.65e9) |
            AD9154_SPI_LDO_BYPASS_FILT_SET(1) |
            AD9154_SPI_LDO_REF_SEL_SET(0))
        self.write(AD9154_LDO_FILTER_1, 0x62) # magic
        self.write(AD9154_LDO_FILTER_2, 0xc9) # magic
        self.write(AD9154_LDO_FILTER_3, 0x0e) # magic
        self.write(AD9154_CP_CURRENT_SPI,
            AD9154_SPI_CP_CURRENT_SET(0x12) |
            AD9154_SPI_SERDES_LOGEN_POWER_MODE_SET(0))
        self.write(AD9154_VCO_LDO, 0x7b) # magic
        self.write(AD9154_PLL_RD_REG,
            AD9154_SPI_SERDES_LOGEN_PD_CORE_SET(0) |
            AD9154_SPI_SERDES_LDO_PD_SET(0) | AD9154_SPI_SYN_PD_SET(0) |
            AD9154_SPI_VCO_PD_ALC_SET(0) | AD9154_SPI_VCO_PD_PTAT_SET(0) |
            AD9154_SPI_VCO_PD_SET(0))
        self.write(AD9154_ALC_VARACTOR,
            AD9154_SPI_VCO_VARACTOR_SET(0x9) |
            AD9154_SPI_INIT_ALC_VALUE_SET(0x8))
        self.write(AD9154_VCO_OUTPUT,
            AD9154_SPI_VCO_OUTPUT_LEVEL_SET(0xc) |
            AD9154_SPI_VCO_OUTPUT_RESERVED_SET(0x4))
        self.write(AD9154_CP_CONFIG,
            AD9154_SPI_CP_TEST_SET(0) |
            AD9154_SPI_CP_CAL_EN_SET(1) |
            AD9154_SPI_CP_FORCE_CALBITS_SET(0) |
            AD9154_SPI_CP_OFFSET_OFF_SET(0) |
            AD9154_SPI_CP_ENABLE_MACHINE_SET(1) |
            AD9154_SPI_CP_DITHER_MODE_SET(0) |
            AD9154_SPI_CP_HALF_VCO_CAL_CLK_SET(0))
        self.write(AD9154_VCO_BIAS_1,
            AD9154_SPI_VCO_BIAS_REF_SET(0x3) |
            AD9154_SPI_VCO_BIAS_TCF_SET(0x3))
        self.write(AD9154_VCO_BIAS_2,
            AD9154_SPI_PRESCALE_BIAS_SET(0x1) |
            AD9154_SPI_LAST_ALC_EN_SET(1) |
            AD9154_SPI_PRESCALE_BYPASS_R_SET(0x1) |
            AD9154_SPI_VCO_COMP_BYPASS_BIASR_SET(0) |
            AD9154_SPI_VCO_BYPASS_DAC_R_SET(0))
        self.write(AD9154_VCO_PD_OVERRIDES,
            AD9154_SPI_VCO_PD_OVERRIDE_VCO_BUF_SET(0) |
            AD9154_SPI_VCO_PD_OVERRIDE_CAL_TCF_SET(1) |
            AD9154_SPI_VCO_PD_OVERRIDE_VAR_REF_TCF_SET(0) |
            AD9154_SPI_VCO_PD_OVERRIDE_VAR_REF_SET(0))
        self.write(AD9154_VCO_CAL,
            AD9154_SPI_FB_CLOCK_ADV_SET(0x2) |
            AD9154_SPI_VCO_CAL_COUNT_SET(0x3) |
            AD9154_SPI_VCO_CAL_ALC_WAIT_SET(0) |
            AD9154_SPI_VCO_CAL_EN_SET(1))
        self.write(AD9154_CP_LEVEL_DETECT,
            AD9154_SPI_CP_LEVEL_THRESHOLD_HIGH_SET(0x2) |
            AD9154_SPI_CP_LEVEL_THRESHOLD_LOW_SET(0x5) |
            AD9154_SPI_CP_LEVEL_DET_PD_SET(0))
        self.write(AD9154_VCO_VARACTOR_CTRL_0,
            AD9154_SPI_VCO_VARACTOR_OFFSET_SET(0xe) |
            AD9154_SPI_VCO_VARACTOR_REF_TCF_SET(0x7))
        self.write(AD9154_VCO_VARACTOR_CTRL_1,
            AD9154_SPI_VCO_VARACTOR_REF_SET(0x6))
        self.write(AD9154_SERDESPLL_ENABLE_CNTRL,
            AD9154_ENABLE_SERDESPLL_SET(1) |
            AD9154_RECAL_SERDESPLL_SET(0))
        self.write(AD9154_EQ_BIAS_REG,
            AD9154_EQ_BIAS_RESERVED_SET(0x22) |
            AD9154_EQ_POWER_MODE_SET(1))

        # step 5: data link layer (does not guarantee deterministic latency)
        self.write(AD9154_GENERAL_JRX_CTRL_1, 0x01) # subclass 1
        self.write(AD9154_LMFC_DELAY_0, 0x00)
        self.write(AD9154_LMFC_DELAY_1, 0x00)
        self.write(AD9154_LMFC_VAR_0, 0x0a) # receive buffer delay
        self.write(AD9154_LMFC_VAR_1, 0x0a)
        self.write(AD9154_SYNC_CONTROL, AD9154_SYNCMODE_SET(1))
        self.write(AD9154_SYNC_CONTROL,
            AD9154_SYNCMODE_SET(1) |
            AD9154_SYNCENABLE_SET(1))
        self.write(AD9154_SYNC_CONTROL,
            AD9154_SYNCMODE_SET(1) | AD9154_SYNCENABLE_SET(1) |
            AD9154_SYNCARM_SET(1))

        if physical_lanes == 0xff:
            self.write(AD9154_XBAR_LN_0_1,
                AD9154_LOGICAL_LANE0_SRC_SET(7) |
                AD9154_LOGICAL_LANE1_SRC_SET(6))
            self.write(AD9154_XBAR_LN_2_3,
                AD9154_LOGICAL_LANE2_SRC_SET(5) |
                AD9154_LOGICAL_LANE3_SRC_SET(4))
            self.write(AD9154_XBAR_LN_4_5,
                AD9154_LOGICAL_LANE4_SRC_SET(3) |
                AD9154_LOGICAL_LANE5_SRC_SET(2))
            self.write(AD9154_XBAR_LN_6_7,
                AD9154_LOGICAL_LANE6_SRC_SET(1) |
                AD9154_LOGICAL_LANE7_SRC_SET(0))
        elif physical_lanes == 0xf0:
            self.write(AD9154_XBAR_LN_0_1,
                AD9154_LOGICAL_LANE0_SRC_SET(7) |
                AD9154_LOGICAL_LANE1_SRC_SET(6))
            self.write(AD9154_XBAR_LN_2_3,
                AD9154_LOGICAL_LANE2_SRC_SET(5) |
                AD9154_LOGICAL_LANE3_SRC_SET(4))
            self.write(AD9154_XBAR_LN_4_5,
                AD9154_LOGICAL_LANE4_SRC_SET(0) |
                AD9154_LOGICAL_LANE5_SRC_SET(0))
            self.write(AD9154_XBAR_LN_6_7,
                AD9154_LOGICAL_LANE6_SRC_SET(0) |
                AD9154_LOGICAL_LANE7_SRC_SET(0))
        elif physical_lanes == 0x0f:
            self.write(AD9154_XBAR_LN_0_1,
                AD9154_LOGICAL_LANE0_SRC_SET(3) |
                AD9154_LOGICAL_LANE1_SRC_SET(2))
            self.write(AD9154_XBAR_LN_2_3,
                AD9154_LOGICAL_LANE2_SRC_SET(1) |
                AD9154_LOGICAL_LANE3_SRC_SET(0))
            self.write(AD9154_XBAR_LN_4_5,
                AD9154_LOGICAL_LANE4_SRC_SET(0) |
                AD9154_LOGICAL_LANE5_SRC_SET(0))
            self.write(AD9154_XBAR_LN_6_7,
                AD9154_LOGICAL_LANE6_SRC_SET(0) |
                AD9154_LOGICAL_LANE7_SRC_SET(0))
        self.write(AD9154_JESD_BIT_INVERSE_CTRL, polarity_lanes)
        self.write(AD9154_GENERAL_JRX_CTRL_0,
            AD9154_LINK_EN_SET(1) | AD9154_LINK_PAGE_SET(0) |
            AD9154_LINK_MODE_SET(0) | AD9154_CHECKSUM_MODE_SET(0))

    def prbs_test(self, mode, threshold):
        prbs_modes = {
            "prbs7" : 0b00,
            "prbs15": 0b01,
            "prbs31": 0b10,
        }
        prbs = prbs_modes[mode]

        # follow phy prbs testing (p58 of ad9154 datasheet)

        # step 1: start sending prbs patter from the transmitter

        # step 2: select prbs mode
        self.write(AD9154_PHY_PRBS_TEST_CTRL,
            AD9154_PHY_PRBS_PAT_SEL_SET(prbs))

        # step 3: enable test for all lanes
        self.write(AD9154_PHY_PRBS_TEST_EN, 0xff)

        # step 4: reset
        self.write(AD9154_PHY_PRBS_TEST_CTRL,
            AD9154_PHY_PRBS_PAT_SEL_SET(prbs) |
            AD9154_PHY_TEST_RESET_SET(1))
        self.write(AD9154_PHY_PRBS_TEST_CTRL,
            AD9154_PHY_PRBS_PAT_SEL_SET(prbs))

        # step 5: prbs threshold
        self.write(AD9154_PHY_PRBS_TEST_THRESHOLD_LOBITS,
            (threshold & 0x0000ff) >> 0)
        self.write(AD9154_PHY_PRBS_TEST_THRESHOLD_MIDBITS,
            (threshold & 0x00ff00) >> 8)
        self.write(AD9154_PHY_PRBS_TEST_THRESHOLD_HIBITS,
            (threshold & 0xff0000) >> 16)

        # step 6: start
        self.write(AD9154_PHY_PRBS_TEST_CTRL,
            AD9154_PHY_PRBS_PAT_SEL_SET(prbs))
        self.write(AD9154_PHY_PRBS_TEST_CTRL,
            AD9154_PHY_PRBS_PAT_SEL_SET(prbs) |
            AD9154_PHY_TEST_START_SET(1))

        # step 7: wait 500 ms
        time.sleep(0.5)

        # step 8 : stop
        self.write(AD9154_PHY_PRBS_TEST_CTRL,
            AD9154_PHY_PRBS_PAT_SEL_SET(prbs))

        status = self.read(AD9154_PHY_PRBS_TEST_STATUS)

        errors = [0]*8

        for i in range(8):
            # step 9.a: select src err
            self.write(AD9154_PHY_PRBS_TEST_CTRL,
                AD9154_PHY_SRC_ERR_CNT_SET(i))
            # step 9.b: retrieve number of errors
            errors[i] = (self.read(AD9154_PHY_PRBS_TEST_ERRCNT_LOBITS) << 0)
            errors[i] |= (self.read(AD9154_PHY_PRBS_TEST_ERRCNT_MIDBITS) << 8)
            errors[i] |= (self.read(AD9154_PHY_PRBS_TEST_ERRCNT_HIBITS) << 16)

        return status, errors

    def stpl_test(self, m=4, s=2):
        status = [0]*m
        for i in range(m):
            for j in range(s):
                # select converter
                self.write(AD9154_SHORT_TPL_TEST_0,
                    AD9154_SHORT_TPL_TEST_EN_SET(0) |
                    AD9154_SHORT_TPL_TEST_RESET_SET(0) |
                    AD9154_SHORT_TPL_DAC_SEL_SET(i) |
                    AD9154_SHORT_TPL_SP_SEL_SET(j))
                # set expected value
                data = seed_to_data((i << 8) | j, True)
                self.write(AD9154_SHORT_TPL_TEST_1, data & 0xff)
                self.write(AD9154_SHORT_TPL_TEST_2, (data & 0xff00) >> 8)
                # enable stpl
                self.write(AD9154_SHORT_TPL_TEST_0,
                    AD9154_SHORT_TPL_TEST_EN_SET(1) |
                    AD9154_SHORT_TPL_TEST_RESET_SET(0) |
                    AD9154_SHORT_TPL_DAC_SEL_SET(i) |
                    AD9154_SHORT_TPL_SP_SEL_SET(j))
                # reset stpl
                self.write(AD9154_SHORT_TPL_TEST_0,
                    AD9154_SHORT_TPL_TEST_EN_SET(1) |
                    AD9154_SHORT_TPL_TEST_RESET_SET(1) |
                    AD9154_SHORT_TPL_DAC_SEL_SET(i) |
                    AD9154_SHORT_TPL_SP_SEL_SET(j))
                # release reset stpl
                self.write(AD9154_SHORT_TPL_TEST_0,
                    AD9154_SHORT_TPL_TEST_EN_SET(1) |
                    AD9154_SHORT_TPL_TEST_RESET_SET(0) |
                    AD9154_SHORT_TPL_DAC_SEL_SET(i) |
                    AD9154_SHORT_TPL_SP_SEL_SET(j))
                status[i] |= self.read(AD9154_SHORT_TPL_TEST_3)

        return status

    def print_status(self):
        x = self.read(AD9154_IRQ_STATUS0)
        print("LANEFIFOERR: {:d}, SERPLLLOCK: {:d}, SERPLLLOST: {:d}, "
                "DACPLLLOCK: {:d}, DACPLLLOST: {:d}".format(
                AD9154_LANEFIFOERR_GET(x), AD9154_SERPLLLOCK_GET(x),
                AD9154_SERPLLLOST_GET(x), AD9154_DACPLLLOCK_GET(x),
                AD9154_DACPLLLOST_GET(x)))
        x = self.read(AD9154_IRQ_STATUS1)
        print("PRBS0: {:d}, PRBS1: {:d}, PRBS2: {:d}, PRBS3: {:d}".format(
                AD9154_PRBS0_GET(x), AD9154_PRBS1_GET(x),
                AD9154_PRBS2_GET(x), AD9154_PRBS3_GET(x)))
        x = self.read(AD9154_IRQ_STATUS2)
        print("SYNC_TRIP0: {:d}, SYNC_WLIM0: {:d}, SYNC_ROTATE0: {:d}, "
                "SYNC_LOCK0: {:d}, NCO_ALIGN0: {:d}, BLNKDONE0: {:d}, "
                "PDPERR0: {:d}".format(
                AD9154_SYNC_TRIP0_GET(x), AD9154_SYNC_WLIM0_GET(x),
                AD9154_SYNC_ROTATE0_GET(x), AD9154_SYNC_LOCK0_GET(x),
                AD9154_NCO_ALIGN0_GET(x), AD9154_BLNKDONE0_GET(x),
                AD9154_PDPERR0_GET(x)))
        x = self.read(AD9154_IRQ_STATUS3)
        print("SYNC_TRIP1: {:d}, SYNC_WLIM1: {:d}, SYNC_ROTATE1: {:d}, "
                "SYNC_LOCK1: {:d}, NCO_ALIGN1: {:d}, BLNKDONE1: {:d}, "
                "PDPERR1: {:d}".format(
                AD9154_SYNC_TRIP1_GET(x), AD9154_SYNC_WLIM1_GET(x),
                AD9154_SYNC_ROTATE1_GET(x), AD9154_SYNC_LOCK1_GET(x),
                AD9154_NCO_ALIGN1_GET(x), AD9154_BLNKDONE1_GET(x),
                AD9154_PDPERR1_GET(x)))
        x = self.read(AD9154_JESD_CHECKS)
        print("ERR_INTSUPP: {:d}, ERR_SUBCLASS: {:d}, ERR_KUNSUPP: {:d}, "
                "ERR_JESDBAD: {:d}, ERR_WINLIMIT: {:d}, ERR_DLYOVER: {:d}".format(
                AD9154_ERR_INTSUPP_GET(x), AD9154_ERR_SUBCLASS_GET(x),
                AD9154_ERR_KUNSUPP_GET(x), AD9154_ERR_JESDBAD_GET(x),
                AD9154_ERR_WINLIMIT_GET(x), AD9154_ERR_DLYOVER_GET(x)))

        x = self.read(AD9154_DACPLLSTATUS)
        print("DACPLL_LOCK: {:d}, VCO_CAL_PROGRESS: {:d}, CP_CAL_VALID: {:d}, "
                "CP_OVERRANGE_L: {:d}, CP_OVERRANGE_H: {:d}".format(
                AD9154_DACPLL_LOCK_GET(x), AD9154_VCO_CAL_PROGRESS_GET(x),
                AD9154_CP_CAL_VALID_GET(x), AD9154_CP_OVERRANGE_L_GET(x),
                AD9154_CP_OVERRANGE_H_GET(x)))

        x = self.read(AD9154_PLL_STATUS)
        print("PLL_LOCK_RB: {:d}, CURRENTS_READY_RB: {:d}, "
                "VCO_CAL_IN_PROGRESS_RB: {:d}, PLL_CAL_VALID_RB: {:d}, "
                "PLL_OVERRANGE_L_RB: {:d}, PLL_OVERRANGE_H_RB: {:d}".format(
                AD9154_SERDES_PLL_LOCK_RB_GET(x),
                AD9154_SERDES_CURRENTS_READY_RB_GET(x),
                AD9154_SERDES_VCO_CAL_IN_PROGRESS_RB_GET(x),
                AD9154_SERDES_PLL_CAL_VALID_RB_GET(x),
                AD9154_SERDES_PLL_OVERRANGE_L_RB_GET(x),
                AD9154_SERDES_PLL_OVERRANGE_H_RB_GET(x)))

        print("CODEGRPSYNC: 0x{:02x}".format(self.read(AD9154_CODEGRPSYNCFLG)))
        print("FRAMESYNC: 0x{:02x}".format(self.read(AD9154_FRAMESYNCFLG)))
        print("GOODCHECKSUM: 0x{:02x}".format(self.read(AD9154_GOODCHKSUMFLG)))
        print("INITIALLANESYNC: 0x{:02x}".format(self.read(AD9154_INITLANESYNCFLG)))

        x = self.read(AD9154_SYNC_LASTERR_H)
        print("SYNC_LASTERR: 0x{:04x}".format(self.read(AD9154_SYNC_LASTERR_L) |
                    (AD9154_LASTERROR_H_GET(x) << 8)))
        print("SYNC_LASTOVER: {:d}, SYNC_LASTUNDER: {:d}".format(
                AD9154_LASTOVER_GET(x), AD9154_LASTUNDER_GET(x)))
        x = self.read(AD9154_SYNC_STATUS)
        print("SYNC_TRIP: {:d}, SYNC_WLIM: {:d}, SYNC_ROTATE: {:d}, "
                "SYNC_LOCK: {:d}, SYNC_BUSY: {:d}".format(
                AD9154_SYNC_TRIP_GET(x), AD9154_SYNC_WLIM_GET(x),
                AD9154_SYNC_ROTATE_GET(x), AD9154_SYNC_LOCK_GET(x),
                AD9154_SYNC_BUSY_GET(x)))

        print("LANE_FIFO_FULL: 0x{:02x}".format(self.read(AD9154_FIFO_STATUS_REG_0)))
        print("LANE_FIFO_EMPTY: 0x{:02x}".format(self.read(AD9154_FIFO_STATUS_REG_1)))
        print("DID_REG: 0x{:02x}".format(self.read(AD9154_DID_REG)))
        print("BID_REG: 0x{:02x}".format(self.read(AD9154_BID_REG)))
        print("SCR_L_REG: 0x{:02x}".format(self.read(AD9154_SCR_L_REG)))
        print("F_REG: 0x{:02x}".format(self.read(AD9154_F_REG)))
        print("K_REG: 0x{:02x}".format(self.read(AD9154_K_REG)))
        print("M_REG: 0x{:02x}".format(self.read(AD9154_M_REG)))
        print("CS_N_REG: 0x{:02x}".format(self.read(AD9154_CS_N_REG)))
        print("NP_REG: 0x{:02x}".format(self.read(AD9154_NP_REG)))
        print("S_REG: 0x{:02x}".format(self.read(AD9154_S_REG)))
        print("HD_CF_REG: 0x{:02x}".format(self.read(AD9154_HD_CF_REG)))
        print("RES1_REG: 0x{:02x}".format(self.read(AD9154_RES1_REG)))
        print("RES2_REG: 0x{:02x}".format(self.read(AD9154_RES2_REG)))
        print("LIDx_REG: 0x{:02x} 0x{:02x} 0x{:02x} 0x{:02x} 0x{:02x} 0x{:02x} 0x{:02x} 0x{:02x}".format(
                self.read(AD9154_LID0_REG), self.read(AD9154_LID1_REG),
                self.read(AD9154_LID2_REG), self.read(AD9154_LID3_REG),
                self.read(AD9154_LID4_REG), self.read(AD9154_LID5_REG),
                self.read(AD9154_LID6_REG), self.read(AD9154_LID7_REG)))
        print("CHECKSUMx_REG: 0x{:02x} 0x{:02x} 0x{:02x} 0x{:02x} 0x{:02x} 0x{:02x} 0x{:02x} 0x{:02x}".format(
                self.read(AD9154_CHECKSUM0_REG), self.read(AD9154_CHECKSUM1_REG),
                self.read(AD9154_CHECKSUM2_REG), self.read(AD9154_CHECKSUM3_REG),
                self.read(AD9154_CHECKSUM4_REG), self.read(AD9154_CHECKSUM5_REG),
                self.read(AD9154_CHECKSUM6_REG), self.read(AD9154_CHECKSUM7_REG)))
        print("COMPSUMx_REG: 0x{:02x} 0x{:02x} 0x{:02x} 0x{:02x} 0x{:02x} 0x{:02x} 0x{:02x} 0x{:02x}".format(
                self.read(AD9154_COMPSUM0_REG), self.read(AD9154_COMPSUM1_REG),
                self.read(AD9154_COMPSUM2_REG), self.read(AD9154_COMPSUM3_REG),
                self.read(AD9154_COMPSUM4_REG), self.read(AD9154_COMPSUM5_REG),
                self.read(AD9154_COMPSUM6_REG), self.read(AD9154_COMPSUM7_REG)))
        print("BADDISPARITY: 0x{:02x}".format(self.read(AD9154_BADDISPARITY)))
        print("NITDISPARITY: 0x{:02x}".format(self.read(AD9154_NIT_W)))
        print("UNEXPECTEDCONTROL: 0x{:02x}".format(self.read(AD9154_UNEXPECTEDCONTROL_W)))
