from litex.gen import *

class ChannelInterface:
    def __init__(self, encoder, decoders):
        self.rx_ready = Signal()
        self.encoder = encoder
        self.decoders = decoders


class TransceiverInterface:
    def __init__(self, channel_interfaces):
        self.clock_domains.cd_rtio = ClockDomain()
        for i in range(len(channel_interfaces)):
            name = "rtio_rx" + str(i)
            setattr(self.clock_domains, "cd_"+name, ClockDomain(name=name))
        self.channels = channel_interfaces
