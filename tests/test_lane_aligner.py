import pytest

from amaranth import *
from amaranth.sim import Simulator, SimulatorContext

from katsuo.stream.sim import *

from katsuo.pcie.dll.misc import LaneAligner
from katsuo.pcie.code import Symbol

from amaranth.hdl import Assume, Cover

def assume_stream_rules(m, stream):
    '''Assume that a stream obeys stream rules.'''
    past_valid = Signal()
    past_ready = Signal()
    past_payload = Signal.like(stream.payload)

    m.d.sync += [
        past_valid.eq(stream.valid),
        past_ready.eq(stream.ready),
        past_payload.eq(stream.payload),
    ]

    with m.If(past_valid & ~past_ready):
        m.d.comb += [
            Assume(stream.valid),
            Assume(stream.payload == past_payload),
        ]

def assert_stream_rules(m, stream):
    '''Assert that a stream obeys stream rules.'''
    past_valid = Signal()
    past_ready = Signal()
    past_payload = Signal.like(stream.payload)

    m.d.sync += [
        past_valid.eq(stream.valid),
        past_ready.eq(stream.ready),
        past_payload.eq(stream.payload),
    ]

    with m.If(past_valid & ~past_ready):
        m.d.comb += [
            Assert(stream.valid),
            Assert(stream.payload == past_payload),
        ]

def test_formal_stream_rules(formal):
    '''Streams must obey stream rules.'''

    m = Module()
    m.submodules.dut = dut = LaneAligner(shape = Symbol, width = 2, token = Symbol.STP)

    assume_stream_rules(m, dut.i)
    assert_stream_rules(m, dut.o)

    has_start_token = Signal()
    prev_has_start_token = Signal()

    for lane in dut.i.p:
        with m.If(lane == Symbol.STP):
            m.d.comb += has_start_token.eq(1)
    with m.If(dut.i.valid & dut.i.ready):
        m.d.sync += prev_has_start_token.eq(has_start_token)


    with m.If(dut.o.valid & dut.o.ready & prev_has_start_token):
        m.d.comb += Assume(~has_start_token)
        m.d.comb += Assert(dut.o.p[0] == Symbol.STP)
        for lane in dut.o.p[1:]:
            m.d.comb += Assert(lane != Symbol.STP)

    #for lane in dut.o.p[1:]:
    #    m.d.comb += Assert(lane != Symbol.STP)

    formal(m, ports = dut, depth = 20)



import subprocess
import textwrap
from amaranth.back import rtlil
from amaranth import ValueLike

class FormalError(Exception):
    pass

def flatten_ports(ports):
    if isinstance(ports, Const):
        return
    elif isinstance(ports, ValueLike):
        yield Value.cast(ports)
    elif hasattr(ports, 'signature'):
        for *_, v in ports.signature.flatten(ports):
            yield from flatten_ports(v)
    else:
        for p in ports:
            yield from flatten_ports(p)

@pytest.fixture
def formal(tmp_path):
    def _exec(spec, ports, depth):
        __tracebackhide__ = True

        ports = list(flatten_ports(ports))

        top = rtlil.convert(spec, ports = ports, platform = 'formal')

        config = textwrap.dedent(f'''\
            [options]
            mode bmc
            depth {depth}
            wait on
            
            [engines]
            smtbmc
                                
            [script]
            read_rtlil top.il
            prep
                                
            [file top.il]
            {top}
        ''')

        res = subprocess.run(['sby', '-f', '-d', tmp_path], input = config, text = True)
        if res.returncode != 0:
            raise FormalError('Formal verification failed')

    return _exec
