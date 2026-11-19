"""
Launch recorder (research): every trade in the first minutes of every Pump.fun token, plus how the
token did afterwards. Turned on by LAUNCH_FILE (JSON lines). Two lines per token, joined by "mint":
  {"kind": "early", ...}    written once its first LAUNCH_TRADE_SECONDS are over (the trades)
  {"kind": "outcome", ...}  written when its tracking ends after LAUNCH_TRACK_HOURS
Writing the trades early keeps memory small and means a restart only loses unfinished outcomes.

Per token:
  meta        name, symbol, creator, dev buy, launch market cap, whether the create event was seen
              on the trade stream (if it wasn't, the stream was probably dropping messages then)
  trades      first LAUNCH_TRADE_SECONDS of trades, compact rows:
                [ms after launch, 1=buy/-1=sell, SOL, tokens, wallet #, market cap in SOL]
              wallet # indexes `wallets` (0 = the creator when known)
  activity    counts for the whole tracking period (trades, buys, sells, SOL volume)
  checkpoints market cap in SOL at 1m, 2m, 5m, 10m, 15m, 30m, 1h, 2h, 3h, 6h after launch
  peak        highest market cap seen on the bonding curve, and when
  graduated   when the bonding curve completed (the token moved to PumpSwap); after that its price
              comes from DexScreener at the checkpoints
"""

from __future__ import annotations

import asyncio
import gzip
import json
import logging
import os
import time

import aiohttp

from . import config
from .hub import hub
from .listeners import pumplogs

log = logging.getLogger("launches")

CHECKPOINTS = (60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600)
DEX_API = "https://api.dexscreener.com/tokens/v1/solana/{}"


class Launch:
    __slots__ = ("mint", "t0", "meta", "trades", "wallets", "counts", "peak", "last", "checkpoints",
                 "graduated_at", "sol_usd", "capped", "early_done", "n_wallets")

    def __init__(self, mint: str, t0: float) -> None:
        self.mint = mint
        self.t0 = t0
        self.meta: dict = {"seenCreate": False}
        self.trades: list[list] = []
        self.wallets: dict[str, int] = {}
        self.counts = {"trades": 0, "buys": 0, "sells": 0, "buySol": 0.0, "sellSol": 0.0}
        self.peak: tuple[float, float] | None = None   # (seconds after launch, mcSol)
        self.last: tuple[float, float] | None = None
        self.checkpoints: dict[str, float | None] = {}
        self.graduated_at: float | None = None
        self.sol_usd: float | None = None
        self.capped = False
        self.early_done = False
        self.n_wallets = 0


class Recorder:
    def __init__(self) -> None:
        self.live: dict[str, Launch] = {}
        self.written = 0
        self.session: aiohttp.ClientSession | None = None

    # ------------------------------------------------------------------ inputs
    def _get(self, mint: str, t: float) -> Launch:
        ln = self.live.get(mint)
        if ln is None:
            ln = self.live[mint] = Launch(mint, t)
            ln.sol_usd = _sol_usd()
        return ln

    def on_create(self, ev: dict) -> None:
        ln = self._get(ev["mint"], ev["receivedAt"])
        ln.t0 = min(ln.t0, ev["receivedAt"])
        ln.meta.update(seenCreate=True, name=ev["name"], symbol=ev["symbol"], creator=ev["user"],
                       hasUri=bool(ev["uri"]))
        ln.wallets.setdefault(ev["user"], len(ln.wallets))

    def on_token(self, token: dict) -> None:
        """New token from the PumpPortal/pumpdev launch feed (always complete, even if the trade stream drops)."""
        if token.get("chain") != "solana" or token.get("source") != "pumpfun":
            return
        ln = self._get(token["address"], time.time())
        ex = token.get("extra") or {}
        ln.meta.setdefault("name", token["name"])
        ln.meta.setdefault("symbol", token["symbol"])
        ln.meta.update(devBuySol=ex.get("devBuySol"), launchMcSol=ex.get("marketCapSol"))
        if ex.get("creator"):
            ln.meta.setdefault("creator", ex["creator"])
            ln.wallets.setdefault(ex["creator"], len(ln.wallets))

    def on_trade(self, ev: dict) -> None:
        ln = self.live.get(ev["mint"])
        if ln is None:
            return
        age = ev["receivedAt"] - ln.t0
        mc = ev["marketCapSol"]
        side = 1 if ev["txType"] == "buy" else -1
        c = ln.counts
        c["trades"] += 1
        if side > 0:
            c["buys"] += 1
            c["buySol"] += ev["solAmount"]
        else:
            c["sells"] += 1
            c["sellSol"] += ev["solAmount"]
        ln.last = (age, mc)
        if ln.peak is None or mc > ln.peak[1]:
            ln.peak = (age, mc)
        if age <= config.LAUNCH_TRADE_SECONDS and not ln.early_done:
            if len(ln.trades) < config.LAUNCH_MAX_TRADES:
                w = ln.wallets.setdefault(ev["traderPublicKey"], len(ln.wallets))
                ln.trades.append([int(age * 1000), side, round(ev["solAmount"], 4), round(ev["tokenAmount"]), w,
                                  round(mc, 2)])
            else:
                ln.capped = True

    def on_complete(self, ev: dict) -> None:
        ln = self.live.get(ev["mint"])
        if ln is not None and ln.graduated_at is None:
            ln.graduated_at = ev["receivedAt"] - ln.t0

    # ------------------------------------------------------------------ loop
    async def run(self) -> None:
        if not config.LAUNCH_FILE:
            return
        hub.on_token.append(self.on_token)
        pumplogs.on_create.append(self.on_create)
        pumplogs.on_trade.append(self.on_trade)
        pumplogs.on_complete.append(self.on_complete)
        log.info("recording launches to %s", config.LAUNCH_FILE)
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15),
                                         connector=aiohttp.TCPConnector(ssl=config.SSL_CONTEXT)) as session:
            self.session = session
            try:
                while True:
                    await asyncio.sleep(15)
                    try:
                        await self._tick()
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:  # noqa: BLE001
                        log.warning("launch recorder tick failed: %s: %s", type(e).__name__, e)
            finally:
                self.flush(complete=False)

    async def _tick(self) -> None:
        now = time.time()
        need_dex: list[tuple[Launch, str]] = []
        for ln in self.live.values():
            age = now - ln.t0
            for cp in CHECKPOINTS:
                key = str(cp)
                if age >= cp and key not in ln.checkpoints:
                    if ln.graduated_at is not None and cp > ln.graduated_at:
                        need_dex.append((ln, key))
                    else:
                        ln.checkpoints[key] = round(ln.last[1], 2) if ln.last else None
        await self._dex(need_dex)
        early = [ln for ln in self.live.values() if not ln.early_done and now - ln.t0 > config.LAUNCH_TRADE_SECONDS + 5]
        if early:
            self._write([self._early(ln) for ln in early])
            for ln in early:  # free the memory; the outcome line only needs the counters
                ln.early_done, ln.n_wallets = True, len(ln.wallets)
                ln.trades, ln.wallets = [], {}
        done = [m for m, ln in self.live.items() if now - ln.t0 > config.LAUNCH_TRACK_HOURS * 3600 + 30]
        if done:
            self._write([self._outcome(self.live.pop(m), complete=True) for m in done])

    async def _dex(self, items: list[tuple[Launch, str]]) -> None:
        """Graduated tokens trade on PumpSwap, which the bonding-curve stream doesn't cover: ask DexScreener."""
        if not items or not self.session:
            return
        by_mint: dict[str, list[tuple[Launch, str]]] = {}
        for ln, key in items:
            by_mint.setdefault(ln.mint, []).append((ln, key))
        mints = list(by_mint)
        for i in range(0, len(mints), 30):
            chunk = mints[i:i + 30]
            prices: dict[str, float] = {}
            try:
                async with self.session.get(DEX_API.format(",".join(chunk))) as r:
                    if r.status == 200:
                        for p in await r.json():
                            addr = (p.get("baseToken") or {}).get("address")
                            mc = p.get("marketCap") or p.get("fdv")
                            native = p.get("priceNative")
                            if addr in by_mint and native and (p.get("quoteToken") or {}).get("symbol") in ("SOL", "WSOL"):
                                val = float(native) * 1e9
                                if val > prices.get(addr, 0):
                                    prices[addr] = val
                            elif addr in by_mint and mc and _sol_usd():
                                prices.setdefault(addr, float(mc) / _sol_usd())
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                pass
            for m in chunk:
                for ln, key in by_mint[m]:
                    ln.checkpoints[key] = round(prices[m], 2) if m in prices else None
                    if m in prices and (ln.peak is None or prices[m] > ln.peak[1]):
                        ln.peak = (time.time() - ln.t0, prices[m])

    # ------------------------------------------------------------------ output
    def _early(self, ln: Launch) -> dict:
        return {
            "kind": "early",
            "mint": ln.mint,
            "launchedAt": round(ln.t0, 3),
            "solUsd": ln.sol_usd,
            "meta": ln.meta,
            "seconds": config.LAUNCH_TRADE_SECONDS,
            "wallets": [w for w, _ in sorted(ln.wallets.items(), key=lambda kv: kv[1])],
            "trades": ln.trades,
            "tradesCapped": ln.capped,
        }

    def _outcome(self, ln: Launch, complete: bool) -> dict:
        return {
            "kind": "outcome",
            "mint": ln.mint,
            "launchedAt": round(ln.t0, 3),
            "complete": complete,
            "meta": ln.meta,
            "activity": {**{k: round(v, 4) if isinstance(v, float) else v for k, v in ln.counts.items()},
                         "walletsFirstMinutes": ln.n_wallets or len(ln.wallets)},
            "checkpoints": ln.checkpoints,
            "peak": {"ageSec": round(ln.peak[0], 1), "mcSol": round(ln.peak[1], 2)} if ln.peak else None,
            "last": {"ageSec": round(ln.last[0], 1), "mcSol": round(ln.last[1], 2)} if ln.last else None,
            "graduatedAtSec": round(ln.graduated_at, 1) if ln.graduated_at is not None else None,
        }

    def _write(self, lines: list[dict]) -> None:
        if not lines:
            return
        try:
            # A path ending in .gz is written gzip-compressed (~3x smaller); each batch is its own gzip
            # member, which `gzip -d` / Python's gzip module read as one continuous file.
            opener = gzip.open if config.LAUNCH_FILE.endswith(".gz") else open
            with opener(config.LAUNCH_FILE, "at") as f:
                for line in lines:
                    f.write(json.dumps(line, separators=(",", ":")) + "\n")
            self.written += len(lines)
        except OSError as e:
            log.warning("could not write %s: %s", config.LAUNCH_FILE, e)

    def flush(self, complete: bool) -> None:
        """Shutting down: save what we have, marked complete=false."""
        lines = [self._early(ln) for ln in self.live.values() if not ln.early_done]
        lines += [self._outcome(ln, complete) for ln in self.live.values()]
        self._write(lines)
        self.live.clear()

    def stats(self) -> dict:
        size = os.path.getsize(config.LAUNCH_FILE) if config.LAUNCH_FILE and os.path.exists(config.LAUNCH_FILE) else 0
        return {
            "enabled": bool(config.LAUNCH_FILE),
            "tracking": len(self.live),
            "recordingTrades": sum(1 for ln in self.live.values() if time.time() - ln.t0 <= config.LAUNCH_TRADE_SECONDS),
            "linesWritten": self.written,
            "fileBytes": size,
            "stream": {k: v for k, v in pumplogs.state.items()},
        }


def _sol_usd() -> float | None:
    from .market import tracker  # late import: market imports a lot
    return tracker.sol_usd


recorder = Recorder()
