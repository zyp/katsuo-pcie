from amaranth import *
from amaranth.sim import Simulator, SimulatorContext

from katsuo.pcie import pipe

from katsuo.pcie.mac.ltssm import LTSSM
from katsuo.pcie.mac.training_set import TrainingSetSender, TrainingSetReceiver, TSType, DataRate
from katsuo.pcie.mac.skip_set import SkipSetSender

from katsuo.pcie.code import Symbol

def test_training_set_sender():
    dut = TrainingSetSender(width = 2)

    sim = Simulator(dut)
    sim.add_clock(125e-6)

    @sim.add_testbench
    async def testbench(ctx: SimulatorContext):
        ctx.set(dut.o.ready, 1)
        await ctx.tick()
        ctx.set(dut.i.p, {
            'ts_type': TSType.TS1,
            'link': Symbol.PAD,
            'lane': Symbol.PAD,
            'n_fts': 127,
            'data_rate': DataRate.GEN_1,
            'training_control': 0,
        })
        ctx.set(dut.i.valid, 1)
        await ctx.tick().until(dut.i.ready == 1)
        ctx.set(dut.i.valid, 0)
        await ctx.tick().until(dut.o.valid == 0)

    with sim.write_vcd('test.vcd'):
        sim.run()

def test_training_set_receiver():
    dut = TrainingSetReceiver(width = 2)

    sim = Simulator(dut)
    sim.add_clock(125e-6)

    @sim.add_testbench
    async def testbench(ctx: SimulatorContext):
        await ctx.tick()
        ts1 = [Symbol.COM, Symbol.PAD, Symbol.PAD, 127, DataRate.GEN_1, 0, *([TSType.TS1] * 10)]
        ts2 = [Symbol.COM, Symbol.PAD, Symbol.PAD, 127, DataRate.GEN_1, 0, *([TSType.TS2] * 10)]

        async def send(sequence):
            #sequence = [Symbol.const({'d': Value.cast(symbol), 'k': 0}) if isinstance(symbol, int) else symbol for symbol in sequence]
            #sequence = [Value.cast(symbol) for symbol in sequence]
            for i in range(0, len(sequence), 2):
                ctx.set(Value.cast(dut.data[0]), sequence[i])
                ctx.set(Value.cast(dut.data[1]), sequence[i + 1])
                await ctx.tick()
        
        # Send three TS1 training sets aligned to first lane
        await send([*(ts1 * 3), 0, 0])

        # Send three TS2 training sets aligned to second lane
        await send([0, *(ts2 * 3), 0, 0, 0])

    with sim.write_vcd('test.vcd'):
        sim.run()

def test_skip_set_sender():
    dut = SkipSetSender(width = 2)

    sim = Simulator(dut)
    sim.add_clock(125e-6)

    @sim.add_testbench
    async def testbench(ctx: SimulatorContext):
        ctx.set(dut.o.ready, 1)
        await ctx.tick().repeat(1000)

    with sim.write_vcd('test.vcd'):
        sim.run()

def test_ltssm_sm():
    phy_pipe = pipe.Signature(2).create()
    dut = LTSSM(phy_pipe)

    sim = Simulator(dut)
    sim.add_clock(125e-6)

    @sim.add_testbench
    async def testbench(ctx: SimulatorContext):
        await ctx.tick().repeat(10000)

    with sim.write_vcd('test.vcd'):
        sim.run()

def test_skip_set_sender():
    dut = SkipSetSender(width = 2)

    sim = Simulator(dut)
    sim.add_clock(125e-6)

    @sim.add_testbench
    async def testbench(ctx: SimulatorContext):
        ctx.set(dut.o.ready, 1)
        await ctx.tick().repeat(1000)

    with sim.write_vcd('test.vcd'):
        sim.run()
