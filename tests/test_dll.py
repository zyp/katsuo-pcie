from amaranth import Module, Signal, Value
from amaranth.sim import Simulator, SimulatorContext

from katsuo.pcie.code import Symbol

from katsuo.pcie.dll.dllp import DLLPacketSender
from katsuo.pcie.dll.tlp import TLPacketSender

from katsuo.pcie.dll.dllp_ng import DLLPacketReceiver
from katsuo.pcie.dll.tlp_ng import TLPacketReceiver

import itertools
from katsuo.stream.sim import stream_get, send_packet

def test_dllp_sender():
    dut = DLLPacketSender(phy_width = 2)

    sim = Simulator(dut)
    sim.add_clock(125e-6)

    @sim.add_testbench
    async def testbench(ctx: SimulatorContext):
        ctx.set(dut.o.ready, 1)
        await ctx.tick()
        ctx.set(Value.cast(dut.i.payload), 0x12345678)
        ctx.set(dut.i.valid, 1)
        await ctx.tick().until(dut.i.ready == 1)
        ctx.set(dut.i.valid, 0)
        await ctx.tick().until(dut.o.valid == 0)

    with sim.write_vcd('test.vcd'):
        sim.run()

def test_dllp_receiver():
    dut = DLLPacketReceiver(phy_width = 2)

    sim = Simulator(dut)
    sim.add_clock(125e-6)

    @sim.add_testbench
    async def testbench(ctx: SimulatorContext):
        await ctx.tick()
        dllp = [Symbol.SDP, 0x40, 0x0c, 0x01, 0x40, 0xbd, 0xa6, Symbol.END]

        async def send(sequence):
            #sequence = [Symbol.const({'d': Value.cast(symbol), 'k': 0}) if isinstance(symbol, int) else symbol for symbol in sequence]
            #sequence = [Value.cast(symbol) for symbol in sequence]
            ctx.set(dut.i.valid, 1)
            for i in range(0, len(sequence), 2):
                ctx.set(Value.cast(dut.i.p[0]), sequence[i])
                ctx.set(Value.cast(dut.i.p[1]), sequence[i + 1])
                await ctx.tick()
            ctx.set(dut.i.valid, 0)
        
        # Send three DLLPs aligned to first lane
        await send([*(dllp * 3), 0, 0])

        # Send three DLLPs aligned to second lane
        await send([0, *(dllp * 3), 0, 0, 0])

    with sim.write_vcd('test.vcd'):
        sim.run()

def test_tlp_receiver():
    dut = TLPacketReceiver(phy_width = 2, tl_width = 4)

    sim = Simulator(dut)
    sim.add_clock(125e-6)

    @sim.add_testbench
    async def testbench(ctx: SimulatorContext):
        await ctx.tick()
        tlp = [
            Symbol.STP,
            0x00, 0x00,
            0x74, 0x00, 0x00, 0x01,  0x00, 0x98, 0x00, 0x50,  0x00, 0x00, 0x00, 0x00,  0x00, 0x00, 0x00, 0x00,
            0xfa, 0x01, 0x00, 0x00,
            0x34, 0xc2, 0x5f, 0x8a,
            Symbol.END,
        ]

        async def send(sequence):
            for i in range(0, len(sequence), 2):
                ctx.set(Value.cast(dut.i.p[0]), sequence[i])
                ctx.set(Value.cast(dut.i.p[1]), sequence[i + 1])
                await ctx.tick()
        
        # Send three TLPs aligned to first lane
        await send([*(tlp * 3), 0, 0])

        # Send three TLPs aligned to second lane
        await send([0, *(tlp * 3), 0, 0, 0])

    with sim.write_vcd('test.vcd'):
        sim.run()

def test_tlp_sender():
    dut = TLPacketSender(phy_width = 2, tl_width = 4)

    sim = Simulator(dut)
    sim.add_clock(125e-6)

    @sim.add_testbench
    async def input_testbench(ctx: SimulatorContext):
        await ctx.tick()
        tlp = [((w >> 24) & 0xff) | ((w >> 16) & 0xff) << 8 | ((w >> 8) & 0xff) << 16 | (w & 0xff) << 24 for w in [
        #    Symbol.STP,
        #    0x00, 0x00,
            0x74000001, 0x00980050, 0x00000000, 0x00000000,
            0xfa010000,
        #    0x34, 0xc2, 0x5f, 0x8a,
        #    Symbol.END,
        ]]

        await send_packet(ctx, dut.i, tlp)
        await send_packet(ctx, dut.i, tlp)

    @sim.add_testbench
    async def output_testbench(ctx: SimulatorContext):
        tlp = [
            0x00, Symbol.STP,
            0x00, 0x00,
            0x74, 0x00, 0x00, 0x01,  0x00, 0x98, 0x00, 0x50,  0x00, 0x00, 0x00, 0x00,  0x00, 0x00, 0x00, 0x00,
            0xfa, 0x01, 0x00, 0x00,
            0x34, 0xc2, 0x5f, 0x8a,
            Symbol.END, 0x00,

            0x00, Symbol.STP,
            0x00, 0x01,
            0x74, 0x00, 0x00, 0x01,  0x00, 0x98, 0x00, 0x50,  0x00, 0x00, 0x00, 0x00,  0x00, 0x00, 0x00, 0x00,
            0xfa, 0x01, 0x00, 0x00,
            0xaa, 0x41, 0x85, 0x15,
            Symbol.END, 0x00,
        ]

        for symbols in itertools.batched(tlp, 2):
            p = await stream_get(ctx, dut.o)
            for i in range(2):
                if isinstance(symbols[i], int):
                    assert p.data[i].k == 0
                    assert p.data[i].d == symbols[i]
                else:
                    assert p.data[i] == symbols[i]

    @sim.add_process
    async def timeout(ctx: SimulatorContext):
        await ctx.tick().repeat(10_000)
        raise TimeoutError('Simulation timed out')

    with sim.write_vcd('test.vcd'):
        sim.run()
