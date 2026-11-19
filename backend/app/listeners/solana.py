"""
Solana listener: every new Pump.fun token via PumpPortal's free WebSocket.

Feeds (both used at the same time, results de-duplicated by mint address):
  wss://pumpportal.fun/api/data   (send {"method": "subscribeNewToken"})
  wss://pumpdev.io/ws             (same protocol)

Each feed reconnects independently with backoff; Solana only shows as unhealthy if all feeds are down.
"""

from __future__ import annotations

import asyncio
import json
import logging

import websockets

from .. import config
from ..hub import hub, iso_now

log = logging.getLogger("solana")


def normalize(t: dict) -> dict | None:
    mint = t.get("mint")
    if not mint or "name" not in t:
        return None  # subscription acks and other non-token messages
    pool = (t.get("pool") or "pump").lower()
    source = "pumpfun" if pool == "pump" else pool  # PumpPortal may tag other launchpads, e.g. "bonk"
    extra: dict = {}
    if source == "pumpfun":
        extra["pumpUrl"] = f"https://pump.fun/coin/{mint}"
    if t.get("solAmount") is not None:
        try:
            extra["devBuySol"] = round(float(t["solAmount"]), 4)
        except (TypeError, ValueError):
            pass
    if t.get("marketCapSol") is not None:
        try:
            extra["marketCapSol"] = round(float(t["marketCapSol"]), 2)
        except (TypeError, ValueError):
            pass
    if t.get("signature"):
        extra["txHash"] = t["signature"]
    if t.get("bondingCurveKey"):
        extra["bondingCurve"] = t["bondingCurveKey"]
    if isinstance(t.get("uri"), str):
        extra["metadataUri"] = t["uri"][:300]  # JSON with image/socials; fetched only for runners
    if t.get("traderPublicKey"):
        extra["creator"] = t["traderPublicKey"]
    return {
        "id": f"solana:{mint}",
        "chain": "solana",
        "name": str(t.get("name") or "?")[:80],
        "symbol": str(t.get("symbol") or "?")[:24],
        "address": mint,
        "detectedAt": iso_now(),
        "source": source,
        "dexscreenerUrl": f"https://dexscreener.com/solana/{mint}",
        "extra": extra,
    }


async def _feed(url: str, up: dict[str, bool]) -> None:
    """One feed, reconnecting forever. `up` tracks which feeds are currently connected."""
    backoff = 2
    while True:
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=20, open_timeout=15,
                                          ssl=config.SSL_CONTEXT if url.startswith("wss") else None) as ws:
                await ws.send(json.dumps({"method": "subscribeNewToken"}))
                if _watched:  # resubscribe live trades after a reconnect
                    await ws.send(json.dumps({"method": "subscribeTokenTrade", "keys": sorted(_watched)}))
                _sockets[url] = ws
                up[url] = True
                hub.set_state("solana", "connected", endpoint=", ".join(u for u, ok in up.items() if ok))
                backoff = 2
                while True:
                    # Pump.fun mints constantly; long silence means the feed is stuck.
                    raw = await asyncio.wait_for(ws.recv(), timeout=config.SOLANA_STALE_SECONDS)
                    try:
                        msg = json.loads(raw)
                        tx_type = msg.get("txType", "create")
                        if tx_type in ("buy", "sell"):
                            for cb in hub.on_trade:  # live trade of a watched token
                                cb(msg)
                            continue
                        if tx_type != "create":
                            continue  # e.g. pumpdev's "create_pool" (migration), not a new token
                        token = normalize(msg)
                    except (json.JSONDecodeError, AttributeError):
                        continue
                    if token:
                        hub.add_token(token)  # the hub dedupes by mint across both feeds
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — any failure just means "reconnect"
            _sockets.pop(url, None)
            up[url] = False
            reason = "no data (stale)" if isinstance(e, asyncio.TimeoutError) else f"{type(e).__name__}: {e}"[:200]
            log.info("feed %s dropped: %s", url, reason)
            if not any(up.values()):  # only report the chain unhealthy if *every* feed is down
                hub.set_state("solana", "reconnecting", error=f"{url}: {reason}")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)


async def run() -> None:
    # Run every feed at once instead of failing over: in testing, PumpPortal sometimes stays
    # connected but delivers only a trickle, while pumpdev.io keeps streaming (or vice versa).
    up = {url: False for url in config.SOLANA_FEEDS}
    await asyncio.gather(*(_feed(url, up) for url in config.SOLANA_FEEDS))


# ---------------------------------------------------------------------------- live trades
# The runner tracker asks for every trade of a few tokens (runners + candidates) so their
# charts move in real time. Subscriptions go over the SAME sockets as the new-token feed,
# because the feeds allow only one connection per IP.
_sockets: dict[str, object] = {}   # url -> open websocket
_watched: set[str] = set()


def watch(mint: str) -> None:
    if mint in _watched or len(_watched) >= 300:
        return
    _watched.add(mint)
    _send_all({"method": "subscribeTokenTrade", "keys": [mint]})


def unwatch(mint: str) -> None:
    if mint in _watched:
        _watched.discard(mint)
        _send_all({"method": "unsubscribeTokenTrade", "keys": [mint]})


def _send_all(msg: dict) -> None:
    raw = json.dumps(msg)
    for ws in list(_sockets.values()):
        asyncio.create_task(_safe_send(ws, raw))


async def _safe_send(ws, raw: str) -> None:
    try:
        await ws.send(raw)
    except Exception:  # noqa: BLE001 — a dead socket reconnects and resubscribes on its own
        pass
