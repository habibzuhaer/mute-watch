"""Public bridge / router contracts — role=bridge for prep obfuscation scoring.

Starter set of well-known bridges (Ethereum + majors). Expand from your dumps.
"""

from __future__ import annotations

# address(lower) -> entity name
BRIDGE_CONTRACTS: dict[str, str] = {
    # Stargate
    "0x8731d54e9d02c286767d671aac4cd310a8bc4c1d": "Stargate",
    "0x150f94b44927f078737562f0fcf3c95c01cc2376": "Stargate",
    # Across
    "0x5c7bcd6e7de5423a257d81b442095a1a6ced35c5": "Across",
    # Hop
    "0xb8901acb165ed027e32754e0ffe830802919095b": "Hop Protocol",
    # Multichain / Anyswap (legacy)
    "0x6b7a87899490ece95443e979ca9485cbe7e71505": "Multichain",
    # Wormhole token bridge
    "0x3ee18b2214aff97000d974cf647e7c347e8fa585": "Wormhole",
    # LayerZero endpoint (infra — softer signal)
    "0x66a71dcef29a0ffbdbe3c6a460a3b5bc225cd675": "LayerZero",
    # Synapse
    "0x2796317b0ff8538f253ef80837724ce94784cc2c": "Synapse",
    # Celer cBridge
    "0x5427fefa711eff984124bfbb1ab6fbf5e3da3560": "Celer cBridge",
    # Orbiter
    "0x80c67432656d59144ceff962e8faf8926599bcf8": "Orbiter",
    # Native Polygon PoS bridge
    "0xa0c68c638235ee32657e8f770da848a3de0d9e9e": "Polygon Bridge",
    # Arbitrum bridge
    "0x4dbd4fc535ac27206064b04fffdc2b4c6dc2b77c": "Arbitrum Bridge",
    # Optimism gateway
    "0x99c9fc46f92e8a1c0dec1b1747d010903e884be1": "Optimism Bridge",
    # Base bridge
    "0x3154cf16ccdb4c6d922629664174b904d80f2c35": "Base Bridge",
}

BRIDGE_CONTRACTS = {
    k.lower(): v
    for k, v in BRIDGE_CONTRACTS.items()
    if isinstance(k, str) and k.startswith("0x") and len(k) == 42
}


def bridge_name(addr: str | None) -> str | None:
    if not addr:
        return None
    return BRIDGE_CONTRACTS.get(addr.lower())
