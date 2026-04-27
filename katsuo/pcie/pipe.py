from amaranth import *
from amaranth.lib import wiring, data, enum

from .code import Symbol

class PowerState(enum.Enum, shape = 2):
    L0 = 0
    L0s = 1
    L1 = 2
    L2 = 3

class RxStatus(enum.Enum, shape = 3):
    OK = 0
    SKP_ADDED = 1
    SKP_REMOVED = 2
    DETECTED = 3
    DECODE_ERROR = 4
    ELASTIC_OVERFLOW = 5
    ELASTIC_UNDERFLOW = 6
    DISPARITY_ERROR = 7

class Signature(wiring.Signature):
    def __init__(self, width: int):
        super().__init__({
            'tx_data': wiring.Out(data.ArrayLayout(Symbol, width)),
            'rx_data': wiring.In(data.ArrayLayout(Symbol, width)),
            'tx_detect_loopback': wiring.Out(1),
            'tx_elec_idle': wiring.Out(1),
            'tx_compliance': wiring.Out(1),
            'rx_polarity': wiring.Out(1),
            'power_down': wiring.Out(PowerState),
            'phy_status': wiring.In(1),
            'rx_status': wiring.In(RxStatus),
            'rx_valid': wiring.In(1),
            'rx_elec_idle': wiring.In(1),
            # TODO: Add more signals as needed (rate, eq, etc…)
        })

        self.width = width
