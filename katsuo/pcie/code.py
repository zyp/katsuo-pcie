from amaranth import *
from amaranth.lib import data

class Symbol(data.Struct):
    d: 8
    k: 1

_valid_k_codes = [
    (28, 0),
    (28, 1),
    (28, 2),
    (28, 3),
    (28, 4),
    (28, 5),
    (28, 6),
    (28, 7),
    (23, 7),
    (27, 7),
    (29, 7),
    (30, 7),
]

def _K(a, b):
    assert (a, b) in _valid_k_codes
    return Symbol.const({'d': a | (b << 5), 'k': 1})

Symbol.K = _K
Symbol.COM = Symbol.K(28, 5)
Symbol.STP = Symbol.K(27, 7)
Symbol.SDP = Symbol.K(28, 2)
Symbol.END = Symbol.K(29, 7)
Symbol.EDB = Symbol.K(30, 7)
Symbol.PAD = Symbol.K(23, 7)
Symbol.SKP = Symbol.K(28, 0)
Symbol.FTS = Symbol.K(28, 1)
Symbol.IDL = Symbol.K(28, 3)
Symbol.EIE = Symbol.K(28, 7)
