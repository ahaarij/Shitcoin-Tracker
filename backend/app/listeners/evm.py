"""
EVM listener: one independent task per chain.

Subscribes (eth_subscribe "logs") to the four "a new pool was created" events used by
Uniswap v2/v3/v4 and their many forks (PancakeSwap, SushiSwap, Aerodrome, Velodrome...).
For each pool we look at both tokens, fetch name()/symbol() with one batched eth_call,
skip the "money side" (WETH, USDC, native coin...), and publish whatever is left.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import OrderedDict

import aiohttp
import websockets

from .. import config
from ..config import EvmChain
from ..hub import hub, iso_now

log = logging.getLogger("evm")

# keccak256 event signatures -> our "source" label
V2_PAIR_CREATED = "0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9"    # Uniswap v2 + forks
V3_POOL_CREATED = "0x783cca1c0412dd0d695e784568c96da2e9c22ff989357a2e8b1d9b2b4e6b7118"    # Uniswap v3 + forks
AERO_POOL_CREATED = "0x2128d88d14c80cb081c1252a5acff7a264671bf199ce226b53788fb26065005e"  # Aerodrome / Velodrome
V4_INITIALIZE = "0xdd466e674ea557f56295e2d0218a125ea4b4f0f6f3307b95f85e6110838d6438"      # Uniswap v4

SOURCES = {
    V2_PAIR_CREATED: "uniswap-v2",
    V3_POOL_CREATED: "uniswap-v3",
    AERO_POOL_CREATED: "aerodrome",
    V4_INITIALIZE: "uniswap-v4",
}

# Tokens that are the "money side" of a pair, never the new coin.
QUOTE_SYMBOLS = {
    "WETH", "ETH", "WBNB", "BNB", "WPOL", "WMATIC", "POL", "MATIC", "WAVAX", "AVAX",
    "USDC", "USDC.E", "USDBC", "USDT", "USDT0", "DAI", "BUSD", "FDUSD", "USD1", "USDE",
    "WBTC", "CBBTC", "BTCB", "FRAX", "LUSD", "TUSD", "PYUSD", "RLUSD", "USDS", "STETH", "WSTETH",
    # Popular launchpad / ecosystem quote tokens that new coins are often paired against
    "ZORA", "VIRTUAL", "CLANKER", "AERO", "VELO", "CAKE", "WSOL", "SOL", "EURC", "GHO", "CRVUSD", "XAUT",
}
NATIVE = "0x0000000000000000000000000000000000000000"


def topic_to_addr(topic: str) -> str:
    return "0x" + topic[-40:].lower()


def decode_string(hex_result: str | None) -> str:
    """Decode an ABI `string` return value (or an old-style bytes32 one, e.g. MKR)."""
    if not hex_result or hex_result == "0x":
        return "?"
    try:
        data = bytes.fromhex(hex_result[2:])
        if len(data) >= 64:
            length = int.from_bytes(data[32:64], "big")
            if 0 < length <= len(data) - 64:
                return _clean(data[64:64 + length].decode("utf-8", "ignore")) or "?"
        return _clean(data[:32].rstrip(b"\x00").decode("utf-8", "ignore")) or "?"
    except Exception:  # noqa: BLE001
        return "?"


def _clean(s: str) -> str:
    # Strip control characters scammers sometimes put in names.
    return "".join(ch for ch in s if ch.isprintable()).strip()[:80]


def tokens_from_log(log_: dict) -> tuple[str, tuple[str, str]] | None:
    """Return (source, (tokenA, tokenB)) for a pool-creation log, else None."""
    topics = log_.get("topics") or []
    if not topics:
        return None
    t0 = topics[0].lower()
    if t0 in (V2_PAIR_CREATED, V3_POOL_CREATED, AERO_POOL_CREATED) and len(topics) >= 3:
        return SOURCES[t0], (topic_to_addr(topics[1]), topic_to_addr(topics[2]))
    if t0 == V4_INITIALIZE and len(topics) >= 4:  # topics[1] is the pool id; currencies are [2] and [3]
        return SOURCES[t0], (topic_to_addr(topics[2]), topic_to_addr(topics[3]))
    return None


def pool_info(log_: dict) -> dict:
    """Where the pool's tokens live, so sniper analysis can exclude it (it isn't a buyer)."""
    topics = log_.get("topics") or []
    data = (log_.get("data") or "0x")[2:]
    word = lambda i: "0x" + data[i * 64 + 24:(i + 1) * 64] if len(data) >= (i + 1) * 64 else None  # noqa: E731
    t0 = topics[0].lower() if topics else ""
    if t0 == V2_PAIR_CREATED:
        return {"pool": word(0)}            # PairCreated(t0, t1, pair, uint)
    if t0 == V3_POOL_CREATED:
        return {"pool": word(1)}            # PoolCreated(t0, t1, fee, tickSpacing, pool)
    if t0 == AERO_POOL_CREATED:
        return {"pool": word(0)}            # PoolCreated(t0, t1, stable, pool, uint)
    if t0 == V4_INITIALIZE:
        return {"poolManager": (log_.get("address") or "").lower() or None}  # v4 pools live inside the PoolManager
    return {}


class ChainListener:
    def __init__(self, chain: EvmChain) -> None:
        self.c = chain
        # Cache of address -> (name, symbol). WETH/USDC appear in nearly every pool, so this
        # saves most RPC calls and keeps us well inside free-tier rate limits.
        self.info_cache: OrderedDict[str, tuple[str, str]] = OrderedDict()
        self.rpc_sem = asyncio.Semaphore(8)

    async def token_info(self, session: aiohttp.ClientSession, addr: str) -> tuple[str, str]:
        if addr == NATIVE:
            return ("Native coin", "NATIVE")
        if addr in self.info_cache:
            self.info_cache.move_to_end(addr)
            return self.info_cache[addr]
        calls = [
            {"jsonrpc": "2.0", "id": 1, "method": "eth_call", "params": [{"to": addr, "data": "0x06fdde03"}, "latest"]},  # name()
            {"jsonrpc": "2.0", "id": 2, "method": "eth_call", "params": [{"to": addr, "data": "0x95d89b41"}, "latest"]},  # symbol()
        ]
        result = ("?", "?")
        for attempt in range(2):
            try:
                async with self.rpc_sem:
                    async with session.post(self.c.http_url, json=calls, timeout=aiohttp.ClientTimeout(total=8)) as r:
                        res = await r.json(content_type=None)
                if isinstance(res, list):
                    by_id = {x.get("id"): x.get("result") for x in res if isinstance(x, dict)}
                    result = (decode_string(by_id.get(1)), decode_string(by_id.get(2)))
                    break
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(1 + attempt)  # rate-limited or flaky: one gentle retry
        if result != ("?", "?"):
            self.info_cache[addr] = result
            if len(self.info_cache) > 5000:
                self.info_cache.popitem(last=False)
        return result

    async def handle_log(self, session: aiohttp.ClientSession, log_: dict) -> None:
        parsed = tokens_from_log(log_)
        if not parsed:
            return
        source, pair = parsed
        candidates = [a for a in pair if a != NATIVE and f"{self.c.key}:{a}" not in hub.seen]
        if not candidates:
            return
        infos = await asyncio.gather(*(self.token_info(session, a) for a in candidates))
        for addr, (name, symbol) in zip(candidates, infos):
            if symbol.upper() in QUOTE_SYMBOLS:
                continue
            hub.add_token({
                "id": f"{self.c.key}:{addr}",
                "chain": self.c.key,
                "name": name,
                "symbol": symbol,
                "address": addr,
                "detectedAt": iso_now(),
                "source": source,
                "dexscreenerUrl": f"https://dexscreener.com/{self.c.dexscreener}/{addr}",
                "extra": {
                    **({"txHash": log_["transactionHash"]} if log_.get("transactionHash") else {}),
                    **{k: v for k, v in pool_info(log_).items() if v},
                },
            })

    async def run(self) -> None:
        sub = {
            "jsonrpc": "2.0", "id": 1, "method": "eth_subscribe",
            "params": ["logs", {"topics": [[V2_PAIR_CREATED, V3_POOL_CREATED, AERO_POOL_CREATED, V4_INITIALIZE]]}],
        }
        backoff = 2
        tasks: set[asyncio.Task] = set()
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=config.SSL_CONTEXT)) as session:
            while True:
                try:
                    async with websockets.connect(
                        self.c.ws_url, ping_interval=20, ping_timeout=20, open_timeout=15, max_size=2**23,
                        ssl=config.SSL_CONTEXT if self.c.ws_url.startswith("wss") else None,
                    ) as ws:
                        await ws.send(json.dumps(sub))
                        # Wait for the subscription reply (ignore anything else that arrives first).
                        while True:
                            reply = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
                            if reply.get("id") == 1:
                                break
                        if "error" in reply:
                            raise RuntimeError(reply["error"].get("message", reply["error"]))
                        hub.set_state(self.c.key, "connected", endpoint=_redact(self.c.ws_url))
                        backoff = 2
                        while True:
                            raw = await asyncio.wait_for(ws.recv(), timeout=config.EVM_STALE_SECONDS)
                            msg = json.loads(raw)
                            log_ = (msg.get("params") or {}).get("result")
                            if isinstance(log_, dict) and not log_.get("removed"):
                                t = asyncio.create_task(self.handle_log(session, log_))
                                tasks.add(t)  # keep a reference so it isn't garbage-collected
                                t.add_done_callback(tasks.discard)
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001
                    reason = "no data (stale)" if isinstance(e, asyncio.TimeoutError) else f"{type(e).__name__}: {e}"[:200]
                    hub.set_state(self.c.key, "reconnecting", error=reason)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 60)


def _redact(url: str) -> str:
    """Never leak an API key (e.g. Alchemy's /v2/<key>) through /health."""
    return url.split("/v2/")[0] + "/v2/***" if "/v2/" in url else url


async def run(chain: EvmChain) -> None:
    await ChainListener(chain).run()
