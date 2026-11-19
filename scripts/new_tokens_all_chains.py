"""
NEW TOKEN RADAR — live feed of brand-new tokens across many chains. 100% free.

  Solana   -> every new Pump.fun token (via PumpPortal's free WebSocket)
  EVM      -> every new token that gets its first trading pool on
              Ethereum, BNB Chain, Base, Arbitrum, Polygon, Optimism, Avalanche
              (Uniswap v2/v3/v4 + all forks like PancakeSwap, SushiSwap, Aerodrome...)

Setup:  pip install websockets aiohttp
Run:    python new_tokens_all_chains.py

No API keys. Uses free public nodes (publicnode.com). Each chain runs on its own
connection and auto-reconnects, so one chain dropping never stops the others.
"""

import asyncio
import json
from datetime import datetime

import aiohttp
import websockets

# ---------------------------------------------------------------------------
# Settings — turn chains on/off here
# ---------------------------------------------------------------------------

ENABLE_SOLANA = True

EVM_CHAINS = {
    # name:        (websocket URL,                                  http URL,                                      dexscreener slug)
    "ETHEREUM":  ("wss://ethereum-rpc.publicnode.com",            "https://ethereum-rpc.publicnode.com",         "ethereum"),
    "BNB":       ("wss://bsc-rpc.publicnode.com",                 "https://bsc-rpc.publicnode.com",              "bsc"),
    "BASE":      ("wss://base-rpc.publicnode.com",                "https://base-rpc.publicnode.com",             "base"),
    "ARBITRUM":  ("wss://arbitrum-one-rpc.publicnode.com",        "https://arbitrum-one-rpc.publicnode.com",     "arbitrum"),
    "POLYGON":   ("wss://polygon-bor-rpc.publicnode.com",         "https://polygon-bor-rpc.publicnode.com",      "polygon"),
    "OPTIMISM":  ("wss://optimism-rpc.publicnode.com",            "https://optimism-rpc.publicnode.com",         "optimism"),
    "AVALANCHE": ("wss://avalanche-c-chain-rpc.publicnode.com",   "https://avalanche-c-chain-rpc.publicnode.com", "avalanche"),
}

# ---------------------------------------------------------------------------
# On-chain event signatures (keccak256 hashes) that mean "a new pool was created"
# ---------------------------------------------------------------------------
V2_PAIR_CREATED   = "0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9"  # Uniswap v2 + forks (Pancake, Sushi...)
V3_POOL_CREATED   = "0x783cca1c0412dd0d695e784568c96da2e9c22ff989357a2e8b1d9b2b4e6b7118"  # Uniswap v3 + forks
AERO_POOL_CREATED = "0x2128d88d14c80cb081c1252a5acff7a264671bf199ce226b53788fb26065005e"  # Aerodrome / Velodrome
V4_INITIALIZE     = "0xdd466e674ea557f56295e2d0218a125ea4b4f0f6f3307b95f85e6110838d6438"  # Uniswap v4 (Clanker, Zora, etc.)

# Tokens that are the "money side" of a pair, never the new coin
QUOTE_SYMBOLS = {
    "WETH", "ETH", "WBNB", "BNB", "WPOL", "WMATIC", "POL", "MATIC", "WAVAX", "AVAX",
    "USDC", "USDC.E", "USDBC", "USDT", "USDT0", "DAI", "BUSD", "FDUSD", "USD1", "USDE",
    "WBTC", "CBBTC", "BTCB", "FRAX", "LUSD", "TUSD", "PYUSD", "RLUSD", "USDS", "STETH", "WSTETH",
}
NATIVE = "0x0000000000000000000000000000000000000000"

seen: set[str] = set()


def now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def announce(chain: str, name: str, symbol: str, address: str, slug: str, extra: str = "") -> None:
    print(f"\n[{now()}] 🆕 {chain:<9} {name} (${symbol})")
    print(f"   Address:  {address}")
    if extra:
        print(f"   {extra}")
    print(f"   Chart:    https://dexscreener.com/{slug}/{address}")


# ---------------------------------------------------------------------------
# Solana (Pump.fun)
# ---------------------------------------------------------------------------
SOLANA_FEEDS = ["wss://pumpportal.fun/api/data", "wss://pumpdev.io/ws"]


async def solana() -> None:
    i = 0
    while True:
        url = SOLANA_FEEDS[i % len(SOLANA_FEEDS)]
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                await ws.send(json.dumps({"method": "subscribeNewToken"}))
                print(f"[{now()}] ✅ SOLANA connected")
                async for raw in ws:
                    try:
                        t = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    mint = t.get("mint")
                    if not mint or "name" not in t or mint in seen:
                        continue
                    seen.add(mint)
                    extra = f"Pump.fun: https://pump.fun/coin/{mint}"
                    if t.get("solAmount") is not None:
                        extra = f"Dev buy:  {float(t['solAmount']):.3f} SOL   |   " + extra
                    announce("SOLANA", t.get("name", "?"), t.get("symbol", "?"), mint, "solana", extra)
        except Exception as e:
            print(f"[{now()}] ⚠️  SOLANA dropped ({type(e).__name__}); reconnecting...")
            i += 1
            await asyncio.sleep(2)


# ---------------------------------------------------------------------------
# EVM chains
# ---------------------------------------------------------------------------

def topic_to_addr(topic: str) -> str:
    return "0x" + topic[-40:]


def decode_string(hex_result: str) -> str:
    """Decode an ABI string return value (or old-style bytes32)."""
    if not hex_result or hex_result == "0x":
        return "?"
    data = bytes.fromhex(hex_result[2:])
    try:
        if len(data) >= 64:
            length = int.from_bytes(data[32:64], "big")
            if 0 < length <= len(data) - 64:
                return data[64:64 + length].decode("utf-8", "ignore").strip() or "?"
        return data[:32].rstrip(b"\x00").decode("utf-8", "ignore").strip() or "?"
    except Exception:
        return "?"


async def token_info(session: aiohttp.ClientSession, http_url: str, addr: str) -> tuple[str, str]:
    if addr == NATIVE:
        return ("Native coin", "NATIVE")
    calls = [
        {"jsonrpc": "2.0", "id": 1, "method": "eth_call", "params": [{"to": addr, "data": "0x06fdde03"}, "latest"]},  # name()
        {"jsonrpc": "2.0", "id": 2, "method": "eth_call", "params": [{"to": addr, "data": "0x95d89b41"}, "latest"]},  # symbol()
    ]
    try:
        async with session.post(http_url, json=calls, timeout=aiohttp.ClientTimeout(total=5)) as r:
            res = await r.json(content_type=None)
        res = sorted(res, key=lambda x: x.get("id", 0))
        return decode_string(res[0].get("result")), decode_string(res[1].get("result"))
    except Exception:
        return ("?", "?")


def tokens_from_log(log: dict) -> tuple[str, str] | None:
    topics = log.get("topics", [])
    if not topics:
        return None
    t0 = topics[0].lower()
    if t0 in (V2_PAIR_CREATED, V3_POOL_CREATED, AERO_POOL_CREATED) and len(topics) >= 3:
        return topic_to_addr(topics[1]), topic_to_addr(topics[2])
    if t0 == V4_INITIALIZE and len(topics) >= 4:
        return topic_to_addr(topics[2]), topic_to_addr(topics[3])
    return None


async def handle_log(chain: str, http_url: str, slug: str, log: dict, session: aiohttp.ClientSession) -> None:
    pair = tokens_from_log(log)
    if not pair:
        return
    infos = await asyncio.gather(*(token_info(session, http_url, a) for a in pair))
    for addr, (name, symbol) in zip(pair, infos):
        if addr == NATIVE or symbol.upper() in QUOTE_SYMBOLS:
            continue
        key = f"{chain}:{addr.lower()}"
        if key in seen:
            continue
        seen.add(key)
        announce(chain, name, symbol, addr, slug)


async def evm_chain(chain: str, ws_url: str, http_url: str, slug: str) -> None:
    sub = {
        "jsonrpc": "2.0", "id": 1, "method": "eth_subscribe",
        "params": ["logs", {"topics": [[V2_PAIR_CREATED, V3_POOL_CREATED, AERO_POOL_CREATED, V4_INITIALIZE]]}],
    }
    backoff = 2
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with websockets.connect(ws_url, ping_interval=20, ping_timeout=20, max_size=2**23) as ws:
                    await ws.send(json.dumps(sub))
                    reply = json.loads(await ws.recv())
                    if "error" in reply:
                        raise RuntimeError(reply["error"])
                    print(f"[{now()}] ✅ {chain} connected")
                    backoff = 2
                    async for raw in ws:
                        msg = json.loads(raw)
                        log = msg.get("params", {}).get("result")
                        if isinstance(log, dict) and not log.get("removed"):
                            asyncio.create_task(handle_log(chain, http_url, slug, log, session))
            except Exception as e:
                print(f"[{now()}] ⚠️  {chain} dropped ({type(e).__name__}: {e}); retry in {backoff}s")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)


async def main() -> None:
    print("🔭 New Token Radar starting — Ctrl+C to stop\n")
    tasks = [evm_chain(c, *cfg) for c, cfg in EVM_CHAINS.items()]
    if ENABLE_SOLANA:
        tasks.append(solana())
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
