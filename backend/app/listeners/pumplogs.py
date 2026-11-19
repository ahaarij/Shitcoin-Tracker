"""
Every Pump.fun trade, straight from the Solana network (free, no API key).

Subscribes to `logsSubscribe` for the Pump.fun program and decodes the program's own events from
the transaction logs:
  TradeEvent    every buy/sell on a bonding curve (with the curve's reserves -> exact price)
  CreateEvent   a new token
  CompleteEvent the bonding curve filled up (the token "graduates" to PumpSwap)

Why not PumpPortal/pumpdev trade subscriptions: PumpPortal needs a funded API key for trades and
pumpdev's free tiers allow only 5-25 tokens and 1k-50k trades a month.

The free public endpoint (api.mainnet-beta.solana.com) is fine for this but drops a share of messages
under load. Each TradeEvent carries the curve reserves, so prices stay exact even when some trades
are missed; for complete coverage use a free Helius/other RPC WebSocket via SOLANA_LOGS_WS_URLS.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import struct
import time

import websockets

from .. import config
from ..hub import BoundedSet

log = logging.getLogger("pumplogs")

PUMP = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
_TRADE = hashlib.sha256(b"event:TradeEvent").digest()[:8]
_CREATE = hashlib.sha256(b"event:CreateEvent").digest()[:8]
_COMPLETE = hashlib.sha256(b"event:CompleteEvent").digest()[:8]
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

# Consumers: called with plain dicts (see _trade / _create / _complete for the shapes).
on_trade: list = []
on_create: list = []
on_complete: list = []

state = {"connected": False, "endpoint": None, "lastError": None, "since": None,
         "trades": 0, "creates": 0, "lastEventAt": None}


def b58(b: bytes) -> str:
    n = int.from_bytes(b, "big")
    s = ""
    while n:
        n, r = divmod(n, 58)
        s = _B58[r] + s
    return "1" * (len(b) - len(b.lstrip(b"\0"))) + s


def _str(d: bytes, o: int) -> tuple[str, int]:
    n = int.from_bytes(d[o:o + 4], "little")
    return d[o + 4:o + 4 + n].decode("utf-8", "replace"), o + 4 + n


def _trade(d: bytes, sig: str) -> dict | None:
    if len(d) < 121:
        return None
    sol, tok = struct.unpack_from("<QQ", d, 40)
    ts, vsol, vtok = struct.unpack_from("<qQQ", d, 89)
    if not vsol or not vtok or not tok:
        return None
    # price in SOL per token (SOL has 9 decimals, Pump.fun tokens 6); market cap on a 1B supply,
    # the same convention PumpPortal uses for marketCapSol.
    price = (vsol / 1e9) / (vtok / 1e6)
    return {
        "signature": sig,
        "mint": b58(d[8:40]),
        "txType": "buy" if d[56] else "sell",
        "traderPublicKey": b58(d[57:89]),
        "solAmount": sol / 1e9,
        "tokenAmount": tok / 1e6,
        "marketCapSol": price * 1e9,
        "priceSol": price,
        "timestamp": ts,
        "receivedAt": time.time(),
    }


def _create(d: bytes, sig: str) -> dict | None:
    try:
        name, o = _str(d, 8)
        symbol, o = _str(d, o)
        uri, o = _str(d, o)
        mint, curve, user = b58(d[o:o + 32]), b58(d[o + 32:o + 64]), b58(d[o + 64:o + 96])
    except Exception:  # noqa: BLE001 — malformed or a different layout
        return None
    return {"signature": sig, "mint": mint, "bondingCurve": curve, "user": user,
            "name": name[:80], "symbol": symbol[:24], "uri": uri[:300], "receivedAt": time.time()}


def _complete(d: bytes, sig: str) -> dict | None:
    if len(d) < 104:
        return None
    return {"signature": sig, "user": b58(d[8:40]), "mint": b58(d[40:72]), "receivedAt": time.time()}


def handle(value: dict) -> None:
    """Decode one logsNotification value and dispatch its Pump.fun events."""
    if value.get("err"):
        return  # failed transactions (most of the traffic is bots' failed attempts)
    sig = value.get("signature", "")
    stack: list[str] = []
    for line in value.get("logs") or ():
        if line.startswith("Program data: "):
            # Only trust events emitted by Pump.fun itself; other programs reuse the "TradeEvent" name.
            if not stack or stack[-1] != PUMP:
                continue
            try:
                d = base64.b64decode(line[14:])
            except ValueError:
                continue
            disc = d[:8]
            if disc == _TRADE:
                ev, cbs = _trade(d, sig), on_trade
                if ev:
                    state["trades"] += 1
            elif disc == _CREATE:
                ev, cbs = _create(d, sig), on_create
                if ev:
                    state["creates"] += 1
            elif disc == _COMPLETE:
                ev, cbs = _complete(d, sig), on_complete
            else:
                continue
            if ev:
                state["lastEventAt"] = ev["receivedAt"]
                for cb in cbs:
                    try:
                        cb(ev)
                    except Exception:  # noqa: BLE001
                        log.exception("pumplogs consumer failed")
        elif line.startswith("Program ") and " invoke [" in line:
            stack.append(line.split(" ", 2)[1])
        elif line.startswith("Program ") and (line.endswith(" success") or " failed" in line):
            if stack:
                stack.pop()


async def run() -> None:
    urls = config.SOLANA_LOGS_WS_URLS
    if not urls:
        return
    i, backoff = 0, 2
    seen = BoundedSet(20000)  # a reconnect can replay a few transactions
    while True:
        url = urls[i % len(urls)]
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=30, open_timeout=15,
                                          max_size=2 ** 24, ssl=config.SSL_CONTEXT) as ws:
                await ws.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "logsSubscribe",
                                          "params": [{"mentions": [PUMP]}, {"commitment": "confirmed"}]}))
                ack = json.loads(await asyncio.wait_for(ws.recv(), 15))
                if "result" not in ack:
                    raise RuntimeError(f"subscribe failed: {str(ack)[:150]}")
                state.update(connected=True, endpoint=_redact(url), lastError=None, since=time.time())
                log.info("pump.fun trade stream connected (%s)", _redact(url))
                backoff = 2
                while True:
                    raw = await asyncio.wait_for(ws.recv(), timeout=60)
                    try:
                        value = json.loads(raw)["params"]["result"]["value"]
                    except (KeyError, TypeError, json.JSONDecodeError):
                        continue
                    sig = value.get("signature")
                    if sig in seen:
                        continue
                    seen.add(sig)
                    handle(value)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            state.update(connected=False, lastError=f"{type(e).__name__}: {e}"[:200])
            log.info("pump.fun trade stream dropped (%s): %s", _redact(url), state["lastError"])
            i += 1
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)


def _redact(url: str) -> str:
    return url.split("?")[0] + ("?…" if "?" in url else "")
