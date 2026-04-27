# `katsuo.pcie`

PCIe stack written in Amaranth.

## Status

At the moment, I consider this to be a working proof of concept.
I'm taking a lot of shortcuts, implementing the happy path, and assuming/hoping nothing bad happens.
Most of the time it behaves as a functional Gen1 x1 device.

### PHY

Rudimentary support for the ECP5 serdes.

Initialization/reset sequence is not handled properly and the serdes sometimes gets into states where it doesn't want to start/lock.
Most of the time it works, and most of the time when it doesn't, a gateware reload is enough to persuade it.

The PHY-MAC connection is via a PIPE interface, but most signals except the datapath are still unimplemented.

### MAC

Or as the spec calls it; «Physical Layer, Logical Sub-block», upper half.
PIPE spec calls the layer above the PIPE interface a MAC, so I've gone with that.

The LTSSM is abbreviated and doesn't even have the `Detect` states, so it starts directly in `Polling`.
It also doesn't implement `Recover` or any low-power states, so while it can get to `L0` fine, the only way out is back to `Polling` and doing a full link re-train.

### Data Link Layer

DLL checks the integrity of incoming packets, discards packets that are bad or out of order and ACKs the rest.

Retransmit of outgoing packets is not implemented yet, packets are only sent once and ACKs/NAKs are ignored.

Flow control is not implemented yet.
We advertise infinite credits for inbound packets and don't respect the credit counters for outbound packets.

### Transaction Layer

Transaction layer implements a config request handler and has a config space with enough registers that the host will happily enumerate the device.
Most of the register contents are dummy data.

There is also a MSI handler, a memory request to tilelink handler and more to come.

### Packaging

Both this package and some of the dependencies are not set up with proper packaging and versioning yet, so don't expect a dependency resolver to be able to figure out how to make this work.
