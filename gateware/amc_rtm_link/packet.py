from math import ceil
from copy import copy
from collections import OrderedDict

from migen import *
from migen.genlib.misc import WaitTimer

from misoc.interconnect import stream
from misoc.interconnect.stream import EndpointDescription


def pack_layout(l, n):
    return [("chunk"+str(i), l) for i in range(n)]


class Unpack(Module):
    def __init__(self, n, layout_to, reverse=False):
        self.source = source = stream.Endpoint(layout_to)
        description_from = copy(source.description)
        description_from.payload_layout = pack_layout(description_from.payload_layout, n)
        self.sink = sink = stream.Endpoint(description_from)

        # # #

        mux = Signal(max=n)
        first = Signal()
        eop = Signal()
        self.comb += [
            first.eq(mux == 0),
            eop.eq(mux == (n-1)),
            source.stb.eq(sink.stb),
            sink.ack.eq(eop & source.ack)
        ]
        self.sync += [
            If(source.stb & source.ack,
                If(eop,
                    mux.eq(0)
                ).Else(
                    mux.eq(mux + 1)
                )
            )
        ]
        cases = {}
        for i in range(n):
            chunk = n-i-1 if reverse else i
            cases[i] = [source.payload.raw_bits().eq(getattr(sink.payload, "chunk"+str(chunk)).raw_bits())]
        self.comb += Case(mux, cases).makedefault()
        self.comb += [
            source.eop.eq(sink.eop & eop)
        ]


class Pack(Module):
    def __init__(self, layout_from, n, reverse=False):
        self.sink = sink = stream.Endpoint(layout_from)
        description_to = copy(sink.description)
        description_to.payload_layout = pack_layout(description_to.payload_layout, n)
        self.source = source = stream.Endpoint(description_to)

        # # #

        demux = Signal(max=n)

        load_part = Signal()
        strobe_all = Signal()
        cases = {}
        for i in range(n):
            chunk = n-i-1 if reverse else i
            cases[i] = [getattr(source.payload, "chunk"+str(chunk)).raw_bits().eq(sink.payload.raw_bits())]
        self.comb += [
            sink.ack.eq(~strobe_all | source.ack),
            source.stb.eq(strobe_all),
            load_part.eq(sink.stb & sink.ack)
        ]

        demux_eop = ((demux == (n - 1)) | sink.eop)

        self.sync += [
            If(source.ack, strobe_all.eq(0)),
            If(load_part,
                Case(demux, cases),
                If(demux_eop,
                    demux.eq(0),
                    strobe_all.eq(1)
                ).Else(
                    demux.eq(demux + 1)
                )
            ),
            If(source.stb & source.ack,
                source.eop.eq(sink.eop),
            ).Elif(sink.stb & sink.ack,
                source.eop.eq(sink.eop | source.eop)
            )
        ]


def reverse_bytes(signal):
    n = ceil(len(signal)/8)
    return Cat(iter([signal[i*8:(i+1)*8] for i in reversed(range(n))]))


class HeaderField:
    def __init__(self, byte, offset, width):
        self.byte = byte
        self.offset = offset
        self.width = width


class Header:
    def __init__(self, fields, length, swap_field_bytes=True):
        self.fields = fields
        self.length = length
        self.swap_field_bytes = swap_field_bytes

    def get_layout(self):
        layout = []
        for k, v in sorted(self.fields.items()):
            layout.append((k, v.width))
        return layout

    def get_field(self, obj, name, width):
        if "_lsb" in name:
            field = getattr(obj, name.replace("_lsb", ""))[:width]
        elif "_msb" in name:
            field = getattr(obj, name.replace("_msb", ""))[width:2*width]
        else:
            field = getattr(obj, name)
        if len(field) != width:
            raise ValueError("Width mismatch on " + name + " field")
        return field

    def encode(self, obj, signal):
        r = []
        for k, v in sorted(self.fields.items()):
            start = v.byte*8 + v.offset
            end = start + v.width
            field = self.get_field(obj, k, v.width)
            if self.swap_field_bytes:
                field = reverse_bytes(field)
            r.append(signal[start:end].eq(field))
        return r

    def decode(self, signal, obj):
        r = []
        for k, v in sorted(self.fields.items()):
            start = v.byte*8 + v.offset
            end = start + v.width
            field = self.get_field(obj, k, v.width)
            if self.swap_field_bytes:
                r.append(field.eq(reverse_bytes(signal[start:end])))
            else:
                r.append(field.eq(signal[start:end]))
        return r


class Arbiter(Module):
    def __init__(self, masters, slave):
        if len(masters) == 0:
            pass
        elif len(masters) == 1:
            self.grant = Signal()
            self.comb += masters.pop().connect(slave)
        else:
            self.submodules.rr = RoundRobin(len(masters))
            self.grant = self.rr.grant
            cases = {}
            for i, master in enumerate(masters):
                status = Status(master)
                self.submodules += status
                self.comb += self.rr.request[i].eq(status.ongoing)
                cases[i] = [master.connect(slave)]
            self.comb += Case(self.grant, cases)


class Dispatcher(Module):
    def __init__(self, master, slaves, one_hot=False):
        if len(slaves) == 0:
            self.sel = Signal()
        elif len(slaves) == 1:
            self.comb += master.connect(slaves.pop())
            self.sel = Signal()
        else:
            if one_hot:
                self.sel = Signal(len(slaves))
            else:
                self.sel = Signal(max=len(slaves))

            # # #

            status = Status(master)
            self.submodules += status

            sel = Signal.like(self.sel)
            sel_ongoing = Signal.like(self.sel)
            self.sync += \
                If(status.first,
                    sel_ongoing.eq(self.sel)
                )
            self.comb += \
                If(status.first,
                    sel.eq(self.sel)
                ).Else(
                    sel.eq(sel_ongoing)
                )
            cases = {}
            for i, slave in enumerate(slaves):
                if one_hot:
                    idx = 2**i
                else:
                    idx = i
                cases[idx] = [master.connect(slave)]
            cases["default"] = [master.ack.eq(1)]
            self.comb += Case(sel, cases)


packet_header_length = 12
packet_header_fields = {
    "preamble": HeaderField(0,  0, 32),
    "dst":      HeaderField(4,  0, 32),
    "length":   HeaderField(8,  0, 32)
}
packet_header = Header(packet_header_fields,
                       packet_header_length,
                       swap_field_bytes=True)


def phy_description(dw):
    layout = [("data", dw)]
    return EndpointDescription(layout)


def user_description(dw):
    layout = [
        ("data", dw),
        ("dst",    8),
        ("length", 32)
    ]
    return EndpointDescription(layout)


class MasterPort:
    def __init__(self, dw):
        self.source = stream.Endpoint(user_description(dw))
        self.sink = stream.Endpoint(user_description(dw))


class SlavePort:
    def __init__(self, dw, tag):
        self.sink = stream.Endpoint(user_description(dw))
        self.source = stream.Endpoint(user_description(dw))
        self.tag = tag


class UserPort(SlavePort):
    def __init__(self, dw, tag):
        SlavePort.__init__(self, dw, tag)



class Packetizer(Module):
    def __init__(self):
        self.sink = sink = stream.Endpoint(user_description(32))
        self.source = source = stream.Endpoint(phy_description(32))

        # # #

        # Packet description
        #   - preamble : 4 bytes
        #   - unused   : 3 bytes
        #   - dst      : 1 byte
        #   - length   : 4 bytes
        #   - payload
        header = [
            # preamble
            0x5aa55aa5,
            # dst
            sink.dst,
            # length
            sink.length
        ]

        header_unpack = Unpack(len(header), phy_description(32))
        self.submodules += header_unpack

        for i, byte in enumerate(header):
            chunk = getattr(header_unpack.sink.payload, "chunk" + str(i))
            self.comb += chunk.data.eq(byte)

        fsm = FSM(reset_state="IDLE")
        self.submodules += fsm

        fsm.act("IDLE",
            If(sink.stb,
                NextState("INSERT_HEADER")
            )
        )

        fsm.act("INSERT_HEADER",
            header_unpack.sink.stb.eq(1),
            source.stb.eq(1),
            source.data.eq(header_unpack.source.data),
            header_unpack.source.ack.eq(source.ack),
            If(header_unpack.sink.ack,
                NextState("COPY")
            )
        )

        fsm.act("COPY",
            source.stb.eq(sink.stb),
            source.data.eq(sink.data),
            sink.ack.eq(source.ack),
            If(source.ack & sink.eop,
                NextState("IDLE")
            )
        )


class Depacketizer(Module):
    def __init__(self, clk_freq, timeout=10):
        self.sink = sink = stream.Endpoint(phy_description(32))
        self.source = source = stream.Endpoint(user_description(32))

        # # #

        # Packet description
        #   - preamble : 4 bytes
        #   - unused   : 3 bytes
        #   - dst      : 1 byte
        #   - length   : 4 bytes
        #   - payload
        preamble = Signal(32)

        header = [
            # dst
            source.dst,
            # length
            source.length
        ]

        header_pack = ResetInserter()(Pack(phy_description(32), len(header)))
        self.submodules += header_pack

        for i, byte in enumerate(header):
            chunk = getattr(header_pack.source.payload, "chunk" + str(i))
            self.comb += byte.eq(chunk.data)

        fsm = FSM(reset_state="IDLE")
        self.submodules += fsm

        self.comb += preamble.eq(sink.data)
        fsm.act("IDLE",
            sink.ack.eq(1),
            If((sink.data == 0x5aa55aa5) & sink.stb,
                   NextState("RECEIVE_HEADER")
            ),
            header_pack.source.ack.eq(1)
        )

        self.submodules.timer = WaitTimer(clk_freq*timeout)
        self.comb += self.timer.wait.eq(~fsm.ongoing("IDLE"))

        fsm.act("RECEIVE_HEADER",
            header_pack.sink.stb.eq(sink.stb),
            header_pack.sink.payload.eq(sink.payload),
            If(self.timer.done,
                NextState("IDLE")
            ).Elif(header_pack.source.stb,
                NextState("COPY")
            ).Else(
                sink.ack.eq(1)
            )
        )

        self.comb += header_pack.reset.eq(self.timer.done)

        eop = Signal()
        cnt = Signal(32)

        fsm.act("COPY",
            source.stb.eq(sink.stb),
            source.eop.eq(eop),
            source.data.eq(sink.data),
            sink.ack.eq(source.ack),
            If((source.stb & source.ack & eop) | self.timer.done,
                NextState("IDLE")
            )
        )

        self.sync += \
            If(fsm.ongoing("IDLE"),
                cnt.eq(0)
            ).Elif(source.stb & source.ack,
                cnt.eq(cnt + 1)
            )
        self.comb += eop.eq(cnt == source.length[2:] - 1)


class Crossbar(Module):
    def __init__(self):
        self.users = OrderedDict()
        self.master = MasterPort(32)
        self.dispatch_param = "dst"

    def get_port(self, dst):
        port = UserPort(32, dst)
        if dst in self.users.keys():
            raise ValueError("Destination {0:#x} already assigned".format(dst))
        self.users[dst] = port
        return port

    def do_finalize(self):
        # TX arbitrate
        sinks = [port.sink for port in self.users.values()]
        self.submodules.arbiter = Arbiter(sinks, self.master.source)

        # RX dispatch
        sources = [port.source for port in self.users.values()]
        self.submodules.dispatcher = Dispatcher(self.master.sink,
                                                sources,
                                                one_hot=True)
        cases = {}
        cases["default"] = self.dispatcher.sel.eq(0)
        for i, (k, v) in enumerate(self.users.items()):
            cases[k] = self.dispatcher.sel.eq(2**i)
        self.comb += \
            Case(getattr(self.master.sink, self.dispatch_param), cases)


class Core(Module):
    def __init__(self, clk_freq):
        self.sink = sink = stream.Endpoint(phy_description(32))
        self.source = source = stream.Endpoint(phy_description(32))

        # # #

        # depacketizer / packetizer
        self.submodules.depacketizer = Depacketizer(clk_freq)
        self.submodules.packetizer = Packetizer()

        # crossbar
        self.submodules.crossbar = Crossbar()

        # dataflow
        self.comb += [
            sink.connect(self.depacketizer.sink),
            self.depacketizer.source.connect(self.crossbar.master.sink),

            self.crossbar.master.source.connect(self.packetizer.sink),
            self.packetizer.source.connect(self.source)
        ]
