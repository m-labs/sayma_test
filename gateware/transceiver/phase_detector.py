from litex.gen import *
from litex.gen.genlib.cdc import MultiReg, PulseSynchronizer

from litex.soc.interconnect.csr import *


class PhaseDetector(Module, AutoCSR):
    def __init__(self, nbits=8):
        self.mdata = Signal(8)
        self.sdata = Signal(8)

        self.reset = CSR()
        self.status = CSRStatus(2)

        # # #

        # ideal sampling (middle of the eye):
        #  _____       _____       _____
        # |     |_____|     |_____|     |_____|   data
        #    +     +     +     +     +     +      master sampling
        #       -     -     -     -     -     -   slave sampling (90°/bit period)
        # Since taps are fixed length delays, this ideal case is not possible
        # and we will fall in the 2 following possible cases:
        #
        # 1) too late sampling (idelay needs to be decremented):
        #  _____       _____       _____
        # |     |_____|     |_____|     |_____|   data
        #     +     +     +     +     +     +     master sampling
        #        -     -     -     -     -     -  slave sampling (90°/bit period)
        # on mdata transition, mdata != sdata
        #
        #
        # 2) too early sampling (idelay needs to be incremented):
        #  _____       _____       _____
        # |     |_____|     |_____|     |_____|   data
        #   +     +     +     +     +     +       master sampling
        #      -     -     -     -     -     -    slave sampling (90°/bit period)
        # on mdata transition, mdata == sdata

        transition = Signal()
        inc = Signal()
        dec = Signal()

        # find transition
        mdata_d = Signal(8)
        self.sync.serdes_2p5x += mdata_d.eq(self.mdata)
        self.comb += transition.eq(mdata_d != self.mdata)


        # find what to do
        self.comb += [
            inc.eq(transition & (self.mdata == self.sdata)),
            dec.eq(transition & (self.mdata != self.sdata))
        ]

        # error accumulator
        lateness = Signal(nbits, reset=2**(nbits - 1))
        too_late = Signal()
        too_early = Signal()
        reset_lateness = Signal()
        self.comb += [
            too_late.eq(lateness == (2**nbits - 1)),
            too_early.eq(lateness == 0)
        ]
        self.sync.serdes_2p5x += [
            If(reset_lateness,
                lateness.eq(2**(nbits - 1))
            ).Elif(~too_late & ~too_early,
                If(inc, lateness.eq(lateness - 1)),
                If(dec, lateness.eq(lateness + 1))
            )
        ]

        # control / status cdc
        self.specials += MultiReg(Cat(too_late, too_early), self.status.status)
        self.submodules.do_reset_lateness = PulseSynchronizer("sys", "serdes_2p5x")
        self.comb += [
            reset_lateness.eq(self.do_reset_lateness.o),
            self.do_reset_lateness.i.eq(self.reset.re)
        ]