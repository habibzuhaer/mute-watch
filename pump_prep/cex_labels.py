"""Known CEX hot / deposit wallets (public Etherscan-style labels).

Exact match on transfer `to`. Starter set — expand from your own label dumps.
"""

from __future__ import annotations

CEX_HOT_WALLETS: dict[str, str] = {
    # Binance
    "0x3f5ce5fbfe3e9af3971dd833d26ba9b5c936f0be": "Binance",
    "0xd551234ae421e3bcba99a0da6d736074f22192ff": "Binance",
    "0x0681d8db095565fe8a346fa0277bffb8f47c2e0f": "Binance",
    "0xfe9e8709d3215310075d67e3ed32a380ccf451c8": "Binance",
    "0x4e9ce36e442e55ecd9025b9a6e0d88485d628a67": "Binance",
    "0xbe0eb53f46cd790cd13851f5ca6b29dfe45cb9d9": "Binance",
    "0xf977814e90da44bfa03b6295a0616a897441acec": "Binance",
    "0x28c6c06298d514db089934071355e5743bf21d60": "Binance",
    "0x21a31ee1afc51d94c2efccaa2092ad1028285549": "Binance",
    "0xdfd5293d8e347dfe59e90efd55b2956a1343963d": "Binance",
    "0x56eddb7aa87536c09ccc2793473599fd21a8b4f2": "Binance",
    "0x9696f59e4d72e237be84ffd425dcad154bf96976": "Binance",
    "0x5a52e96bacdabb82fd05763e25335261b270efcb": "Binance",
    # Bybit
    "0x1db92e2eebc8e0c075a02bea49a2935bcd2dfcf4": "Bybit",
    "0xf89d7b9c864f589bbf53a82105107622b35eaa40": "Bybit",
    # OKX
    "0x6cc5f688a315f3dc28a7781717a9a798a59fda7b": "OKX",
    "0x236f9f97e0e62388479bf9e7ba675a7919e50667": "OKX",
    "0x98ec059dc3adfbdd63429454aeb0c990cba4de00": "OKX",
    # Kraken
    "0x267be1c1d684f78cb4f6a176c4911b741e4ffdc0": "Kraken",
    "0x53d284357ec70ce289d6d64134dfac8e511c8a3d": "Kraken",
    "0x2910543af39aba0cd09dab72f5006d9e5f6dec45": "Kraken",
    # Coinbase
    "0x71660c4005ba85c37ccec55d0c4493e66fe775d3": "Coinbase",
    "0x503828976d22510aad0201ac7ec88293211d23da": "Coinbase",
    "0xddfabcdc4d8ffc6d5beaf154f18b778f892a0740": "Coinbase",
    "0xb5d85cbf7cb3ee0d56b3bb207d5fc4b82f43f511": "Coinbase",
    "0xa9d1e08c7793af67e9d92fe308d5697fb81d3e43": "Coinbase",
    # KuCoin
    "0x2b5634c139687127c0d3a86b13f734cf0ea2f06c": "KuCoin",
    "0x689c56aef474df92d44a1b70850f808370ae219f": "KuCoin",
    # Gate
    "0x0d0707963952f2fba59dd06f2b425ace40b492fe": "Gate",
    "0x1c4b70a3968436b9a0a9cf5205c787eb81bb558c": "Gate",
    # Bitget
    "0x1ab4973a48dc892cd9971ece8e01edc69a8338c5": "Bitget",
    # HTX
    "0x18709e89bd403f470088abdacebe86cc60dda12e": "HTX",
    "0x46705dfff24256421a05d056c29ba62b3837b75c": "HTX",
    # Bitfinex / Gemini / Crypto.com
    "0x1151314c646ce4e0efd76d1af4760ae66a9fe30f": "Bitfinex",
    "0xd24400ae8bfebb18ca49be86258a3c749cf46853": "Gemini",
    "0x6262998ced04146fa42253a5c0af90ba6b2c7c7c": "Crypto.com",
}

CEX_HOT_WALLETS = {
    k.lower(): v
    for k, v in CEX_HOT_WALLETS.items()
    if isinstance(k, str) and k.startswith("0x") and len(k) == 42
}

STABLE_OR_MAJOR = {
    "eth",
    "weth",
    "btc",
    "wbtc",
    "usdt",
    "usdc",
    "dai",
    "busd",
    "tusd",
    "fdusd",
    "usde",
    "usds",
    "steth",
    "wsteth",
    "cbeth",
    "bnb",
    "wbnb",
    "matic",
    "wmatic",
    "pol",
    "sol",
    "trx",
}


def cex_name(address: str | None) -> str | None:
    if not address:
        return None
    return CEX_HOT_WALLETS.get(address.lower())


def is_major_symbol(symbol: str | None) -> bool:
    if not symbol:
        return False
    return symbol.strip().lower() in STABLE_OR_MAJOR
