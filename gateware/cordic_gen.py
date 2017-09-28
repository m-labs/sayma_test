from migen import *

from misoc.interconnect.csr import *
from misoc.cores.cordic import Cordic


class Cosine(Module, AutoCSR):
    def __init__(self, width=16):
        self._amplitude = CSRStorage(width)
        self._frequency = CSRStorage(2*width)

        self.submodules.cordic = cordic = Cordic(
                width=width, widthz=2*width, guard=None, eval_mode="pipelined")

        z = Signal(2*width)
        self.sync += z.eq(z + self._frequency.storage)

        self.comb += [
                cordic.xi.eq(self._amplitude.storage),
                cordic.yi.eq(0),
                cordic.zi.eq(z),
        ]
        self.o = cordic.xo


def test(n, width=16):
    dut = Cosine(width=width)
    dut._amplitude.storage.reset = C(int(1/dut.cordic.gain*(1 << width - 1)))
    dut._frequency.storage.reset = C(int(.12345*(1 << 2*width)))

    y = []
    def log():
        for i in range(n):
            yield
            y.append((yield dut.o))

    run_simulation(dut, log(), vcd_name="cordic_gen.vcd")
    import matplotlib.pyplot as plt
    plt.psd(y, NFFT=n//2)
    plt.show()


if __name__ == "__main__":
    test(1<<10)
