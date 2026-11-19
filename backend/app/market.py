"""
Live prices (DexScreener's free API, no key), runner detection, sniper checks and real-time
runner charts.

Every token the listeners find is registered here. Every few seconds we pick the tokens that
most need a refresh, ask DexScreener about them in batches of 30 (its max), and:

  * attach a short price summary to the token (`token["market"]`) for the live feed
  * keep a market-cap history per token
  * when a token's market cap is up >= RUNNER_MIN_GAIN_PCT (default +200%) from its starting
    value while younger than RUNNER_WINDOW_MINUTES (default 30), it becomes a CANDIDATE
  * a candidate becomes a RUNNER once a sniper check shows the wallets that bought in the
    first seconds hold <= RUNNER_MAX_SNIPER_PCT (default 10%) of supply right now
    (re-checked every ~45 s while the 30-minute window is open)

Starting value ("baseline"):
  * Solana / Pump.fun: the launch market cap reported by Pump.fun (in SOL) x the SOL price.
  * EVM chains: the first market cap DexScreener reports (usually within ~1 minute).

Real time: Solana candidates and runners are subscribed to the live Pump.fun trade stream, so
their charts (and sniper/dev holdings) update on every trade, pushed to browsers at most once a
second per token. EVM runners refresh from DexScreener every ~10 s.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import time
from collections import OrderedDict
from datetime import datetime, timezone
from urllib.parse import urlparse

import aiohttp

from . import config
from .hub import hub, iso_now
from .listeners import solana as sol_feed
from .snipers import AnalysisError, analyzer

log = logging.getLogger("market")

API = "https://api.dexscreener.com/tokens/v1/{chain}/{addresses}"
WSOL = "So11111111111111111111111111111111111111112"
BATCH = 30                 # DexScreener accepts up to 30 addresses per request
INTERVAL = 5               # seconds between refresh rounds
REQUESTS_PER_ROUND = 10    # 10 req / 5 s = 120 req/min max (limit is 300)
FIRST_CHECK_AFTER = 15     # DexScreener needs a few seconds to index a brand-new token
MILESTONES = (100, 200, 300, 500, 1000, 2000, 5000, 10000)  # % gains whose first-hit time we record
HISTORY_POINTS = 600       # market-cap samples kept per token (older ones get thinned, never dropped)
SENT_HISTORY_POINTS = 180  # samples sent to browsers per runner
SNIPER_RECHECK = 45        # seconds between sniper checks for a candidate that failed the rule
SNIPER_REFRESH = 60        # seconds between sniper re-checks for runners (live trades fill the gaps)

WINDOW = config.RUNNER_WINDOW_MINUTES * 60
FEED_TRACK = max(3600, WINDOW + 300)           # normal tokens: prices for the feed up to 1 h
RUNNER_TRACK = config.RUNNER_TRACK_HOURS * 3600


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_iso(s: str) -> float:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return time.time()


def _num(x) -> float | None:
    try:
        v = float(x)
        return v if v == v else None  # drop NaN
    except (TypeError, ValueError):
        return None


class Tracked:
    """Everything we know about one token's price action."""

    def __init__(self, token: dict) -> None:
        self.token = token
        self.born = _parse_iso(token["detectedAt"])
        self.last_checked: float | None = None
        self.baseline: float | None = None
        self.baseline_kind: str | None = None   # "launch" | "first-seen"
        self.history: list[tuple[float, float]] = []
        self.milestones: dict[str, int] = {}     # "200" -> seconds after launch
        self.peak: tuple[float, float] | None = None  # (ts, mcUsd)
        self.pair: dict | None = None            # detailed pair stats from DexScreener
        self.meta: dict | None = None            # image / description / socials
        self.candidate: dict | None = None       # gain rule met (waiting on the sniper rule)
        self.hit: dict | None = None             # both rules met -> runner
        # sniper analysis
        self.sniper: dict | None = None
        self.sniper_ctx: dict | None = None
        self.sniper_busy = False
        self.sniper_next = 0.0
        self.sniper_errors = 0
        self.sniper_error: str | None = None
        # real time
        self.watching = False
        self.last_tick = 0.0
        self.tick_dirty = False
        # research log (STUDY_FILE)
        self.signal: dict | None = None          # snapshot when the app would have flagged it

    @property
    def age(self) -> float:
        return time.time() - self.born


class Tracker:
    def __init__(self) -> None:
        self.tracked: dict[str, Tracked] = {}
        self.runners: OrderedDict[str, dict] = OrderedDict()  # id -> record, oldest hit first
        self.sol_usd: float | None = None
        self.sol_usd_at = 0.0
        self.dirty = False
        self.session: aiohttp.ClientSession | None = None

    # ------------------------------------------------------------------ registration
    def add(self, token: dict) -> None:
        tr = Tracked(token)
        self._set_launch_baseline(tr)
        self.tracked[token["id"]] = tr

    def _set_launch_baseline(self, tr: Tracked) -> None:
        mc_sol = tr.token.get("extra", {}).get("marketCapSol")
        if tr.baseline is None and tr.token["chain"] == "solana" and mc_sol and self.sol_usd:
            tr.baseline = float(mc_sol) * self.sol_usd
            tr.baseline_kind = "launch"

    # ------------------------------------------------------------------ public views
    def runner_list(self, limit: int = 300) -> list[dict]:
        """Newest hit first."""
        return list(reversed(self.runners.values()))[:limit]

    # ------------------------------------------------------------------ main loops
    async def run(self) -> None:
        hub.on_token.append(self.add)  # only collect tokens while the tracker is actually running
        hub.on_trade.append(self.on_trade)
        self._load()
        last_save = time.time()
        async with aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=config.SSL_CONTEXT),
            headers={"Accept": "application/json", "User-Agent": "new-token-radar/1.0"},
        ) as session:
            self.session = session
            ticker = asyncio.create_task(self._tick_loop())
            try:
                while True:
                    try:
                        if time.time() - self.sol_usd_at > 60:
                            await self._refresh_sol_price(session)
                        await self._round(session)
                        self._schedule_sniper_checks(session)
                        self._prune()
                        if self.dirty and time.time() - last_save > 60:
                            self._save()
                            last_save = time.time()
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:  # noqa: BLE001 — a pricing hiccup must never kill the loop
                        log.warning("market round failed: %s: %s", type(e).__name__, e)
                    await asyncio.sleep(INTERVAL)
            finally:
                ticker.cancel()
                self._save()
                for tr in self.tracked.values():  # shutting down: log unfinished ones too
                    self._study(tr, complete=False)

    async def _tick_loop(self) -> None:
        """Once a second, push the latest live-trade updates of runners to browsers."""
        while True:
            await asyncio.sleep(1)
            ticks = []
            for tr in self.tracked.values():
                if not tr.tick_dirty:
                    continue
                tr.tick_dirty = False
                if tr.hit:
                    rec = self._record(tr)
                    self.runners[tr.token["id"]] = rec
                    ticks.append({
                        "id": rec["id"],
                        "point": rec["history"][-1] if rec["history"] else None,
                        "now": rec["now"], "peak": rec["peak"], "market": rec["market"],
                        "milestones": rec["milestones"], "snipers": rec["snipers"],
                        "live": True, "updatedAt": rec["updatedAt"],
                    })
            if ticks:
                hub.broadcast({"type": "tick", "data": ticks})

    def _due(self, tr: Tracked, now: float) -> tuple[int, float] | None:
        """Return a sort key (lower = more urgent) or None if this token doesn't need a refresh now."""
        age = now - tr.born
        if tr.hit:
            if age > RUNNER_TRACK:
                return None
            tier, every = 1, 10
        elif tr.candidate and age <= WINDOW + 120:
            tier, every = 1, 10
        elif tr.candidate and config.STUDY_FILE:
            if age > RUNNER_TRACK:
                return None
            tier, every = 3, 60  # keep following rejected candidates so the study has their outcome
        elif age <= WINDOW:
            tier, every = 2, (30 if tr.history else 40)
        elif age <= FEED_TRACK:
            tier, every = 3, 120
        else:
            return None
        if tr.last_checked is None:
            return None if age < FIRST_CHECK_AFTER else (0, -age)
        since = now - tr.last_checked
        if since < every:
            return None
        return (tier, -since)

    async def _round(self, session: aiohttp.ClientSession) -> None:
        now = time.time()
        due = [(k, tr) for tr in self.tracked.values() if (k := self._due(tr, now)) is not None]
        if not due:
            return
        due.sort(key=lambda x: x[0])

        # Group the most urgent tokens by chain into batches of 30, up to the per-round budget.
        open_batches: dict[str, list[Tracked]] = {}
        batches: list[list[Tracked]] = []
        for _, tr in due:
            chain = tr.token["chain"]
            lst = open_batches.setdefault(chain, [])
            if not lst:
                if len(batches) >= REQUESTS_PER_ROUND:
                    continue
                batches.append(lst)
            lst.append(tr)
            if len(lst) == BATCH:
                open_batches[chain] = []

        results = await asyncio.gather(*(self._fetch(session, b) for b in batches))
        market_updates, runner_updates = [], []
        for batch, pairs in zip(batches, results):
            if pairs is None:
                continue  # request failed: retry next round
            for tr in batch:
                tr.last_checked = now
                pair = _pick_pair(pairs, tr.token["address"])
                if not pair:
                    continue
                self._observe_pair(tr, pair, now)
                market_updates.append({"id": tr.token["id"], "market": tr.token["market"]})
                if tr.hit:
                    rec = self._record(tr)
                    self.runners[tr.token["id"]] = rec
                    runner_updates.append(rec)
                    self.dirty = True

        if market_updates:
            hub.broadcast({"type": "market", "data": market_updates})
        if runner_updates:
            hub.broadcast({"type": "runners", "data": runner_updates})

    # ------------------------------------------------------------------ observations
    def _observe_pair(self, tr: Tracked, pair: dict, now: float) -> None:
        """Update a token from a DexScreener pair."""
        tr.token["market"] = _summarize(pair)
        tr.pair = _pair_detail(pair)
        if tr.meta is None and pair.get("info"):
            tr.meta = _meta_from_dexscreener(pair["info"])
        mc = tr.token["market"]["marketCapUsd"]
        # For live-traded tokens, the trade stream is fresher than DexScreener; don't let a
        # slightly stale DexScreener number jump the chart around.
        if mc and not (tr.watching and now - tr.last_tick < 15):
            self._observe_mc(tr, mc, now)

    def _observe_mc(self, tr: Tracked, mc: float, now: float) -> None:
        """A new market-cap reading (from DexScreener or a live trade)."""
        if not mc or mc <= 0:
            return
        self._set_launch_baseline(tr)
        if tr.baseline is None:
            tr.baseline, tr.baseline_kind = mc, "first-seen"

        if tr.history and now - tr.history[-1][0] < 1.0:
            tr.history[-1] = (now, mc)  # at most one point per second
        else:
            tr.history.append((now, mc))
            if len(tr.history) > HISTORY_POINTS:
                _thin(tr.history)
        if tr.peak is None or mc > tr.peak[1]:
            tr.peak = (now, mc)

        age = now - tr.born
        gain = (mc / tr.baseline - 1) * 100
        for m in MILESTONES:
            if gain >= m and str(m) not in tr.milestones:
                tr.milestones[str(m)] = int(age)

        if tr.hit or tr.candidate or age > WINDOW or gain < config.RUNNER_MIN_GAIN_PCT:
            return
        liq = (tr.token.get("market") or {}).get("liquidityUsd")
        if liq is not None and liq < config.RUNNER_MIN_LIQUIDITY_USD:
            return  # a "pump" in a near-empty pool is noise
        # Gain rule met -> candidate. Start live trades + an immediate sniper check.
        tr.candidate = {"at": _iso(now), "ageSec": int(age), "mcUsd": mc, "gainPct": round(gain, 1)}
        tr.sniper_next = 0.0
        self._watch(tr)
        log.info("candidate %s %s +%.0f%% at %ds", tr.token["chain"], tr.token["symbol"], gain, age)

    def on_trade(self, msg: dict) -> None:
        """Live Pump.fun trade for a watched token (candidates + runners)."""
        tr = self.tracked.get(f"solana:{msg.get('mint')}")
        mc_sol = _num(msg.get("marketCapSol"))
        if not tr or not mc_sol or not self.sol_usd:
            return
        now = time.time()
        mc = mc_sol * self.sol_usd
        tr.last_tick = now
        m = tr.token.get("market")
        if m and m.get("marketCapUsd") and m.get("priceUsd"):
            m["priceUsd"] = m["priceUsd"] * mc / m["marketCapUsd"]
        if m:
            m["marketCapUsd"] = mc
            m["updatedAt"] = iso_now()
        self._observe_mc(tr, mc, now)
        if tr.sniper_ctx:
            updated = analyzer.apply_trade(tr.token, tr.sniper_ctx, msg)
            if updated:
                tr.sniper = updated
        tr.tick_dirty = True

    def _watch(self, tr: Tracked) -> None:
        if tr.token["chain"] == "solana" and not tr.watching:
            sol_feed.watch(tr.token["address"])
            tr.watching = True

    def _unwatch(self, tr: Tracked) -> None:
        if tr.watching:
            sol_feed.unwatch(tr.token["address"])
            tr.watching = False

    # ------------------------------------------------------------------ sniper rule
    def _schedule_sniper_checks(self, session: aiohttp.ClientSession) -> None:
        now = time.time()
        for tr in self.tracked.values():
            if tr.sniper_busy or now < tr.sniper_next:
                continue
            if tr.hit and tr.age <= RUNNER_TRACK:
                pass  # keep runner holdings fresh
            elif tr.candidate and not tr.hit and tr.age <= WINDOW + 120:
                pass  # waiting to pass the sniper rule
            else:
                continue
            tr.sniper_busy = True
            asyncio.create_task(self._check_snipers(session, tr))

    async def _check_snipers(self, session: aiohttp.ClientSession, tr: Tracked) -> None:
        try:
            if tr.sniper_ctx is None:
                tr.sniper, tr.sniper_ctx = await analyzer.analyze(session, tr.token)
            else:
                tr.sniper = await analyzer.refresh(session, tr.token, tr.sniper_ctx)
            tr.sniper_errors, tr.sniper_error = 0, None
            tr.sniper_next = time.time() + (SNIPER_REFRESH if tr.hit else SNIPER_RECHECK)
        except (AnalysisError, aiohttp.ClientError, asyncio.TimeoutError, KeyError, ValueError) as e:
            tr.sniper_errors += 1
            tr.sniper_error = str(e)[:200]
            tr.sniper_next = time.time() + 15 * tr.sniper_errors
            log.info("sniper check failed for %s (%d): %s", tr.token["symbol"], tr.sniper_errors, e)
            return
        finally:
            tr.sniper_busy = False

        if tr.hit:
            tr.tick_dirty = True  # push the new holdings with the next tick / refresh
            if tr.token["chain"] != "solana":
                rec = self._record(tr)
                self.runners[tr.token["id"]] = rec
                hub.broadcast({"type": "runners", "data": [rec]})
            return

        if tr.candidate and tr.signal is None:
            tr.signal = self._snapshot(tr)  # first sniper read after the gain rule
        if tr.candidate and tr.sniper["passes"] and tr.age <= WINDOW + 120:
            self._promote(tr)

    def _promote(self, tr: Tracked) -> None:
        tr.hit = {**tr.candidate, "verifiedAt": iso_now(), "sniperPctAtVerify": tr.sniper["holdingPct"]}
        rec = self._record(tr)
        tr.signal = self._snapshot(tr, rec)  # what you'd have seen when it appeared on the page
        self.runners[tr.token["id"]] = rec
        self.dirty = True
        hub.broadcast({"type": "runners", "data": [rec]})
        log.info("RUNNER %s %s +%.0f%% at %ds · snipers hold %.1f%%", tr.token["chain"], tr.token["symbol"],
                 tr.hit["gainPct"], tr.hit["ageSec"], tr.sniper["holdingPct"])
        if self.session:
            asyncio.create_task(self._fetch_meta(self.session, tr))

    # ------------------------------------------------------------------ records
    def _record(self, tr: Tracked) -> dict:
        t = tr.token
        mc = tr.history[-1][1] if tr.history else None
        peak_ts, peak_mc = tr.peak or (None, None)
        base = tr.baseline or 0
        gain = lambda v: round((v / base - 1) * 100, 1) if v and base else None  # noqa: E731
        hist = tr.history
        if len(hist) > SENT_HISTORY_POINTS:
            step = len(hist) / SENT_HISTORY_POINTS
            hist = [hist[int(i * step)] for i in range(SENT_HISTORY_POINTS - 1)] + [hist[-1]]
        return {
            "id": t["id"],
            "chain": t["chain"],
            "name": t["name"],
            "symbol": t["symbol"],
            "address": t["address"],
            "source": t["source"],
            "detectedAt": t["detectedAt"],
            "dexscreenerUrl": t["dexscreenerUrl"],
            "extra": {k: v for k, v in t.get("extra", {}).items() if k not in ("metadataUri", "pool", "poolManager", "bondingCurve")},
            "baseline": {"mcUsd": tr.baseline, "kind": tr.baseline_kind},
            "hit": tr.hit,
            "peak": {
                "mcUsd": peak_mc,
                "gainPct": gain(peak_mc),
                "at": _iso(peak_ts) if peak_ts else None,
                "ageSec": int(peak_ts - tr.born) if peak_ts else None,
            },
            "now": {
                "mcUsd": mc,
                "gainPct": gain(mc),
                "fromPeakPct": round((mc / peak_mc - 1) * 100, 1) if mc and peak_mc else None,
            },
            "market": t.get("market"),
            "pair": tr.pair,
            "meta": tr.meta,
            "snipers": tr.sniper,
            "milestones": tr.milestones,
            "history": [[int(ts - tr.born), round(v, 2)] for ts, v in hist],
            "tracking": tr.age <= RUNNER_TRACK,
            "live": tr.watching and time.time() - tr.last_tick < 20,
            "updatedAt": iso_now(),
        }

    def _snapshot(self, tr: Tracked, rec: dict | None = None) -> dict:
        rec = dict(rec or self._record(tr))
        rec.pop("history", None)
        rec["candidate"] = tr.candidate
        rec["snapshotAgeSec"] = int(tr.age)
        return rec

    def _study(self, tr: Tracked, complete: bool = True) -> None:
        if not config.STUDY_FILE or not tr.candidate:
            return
        final = self._record(tr)
        final["candidate"] = tr.candidate
        line = {"id": tr.token["id"], "runner": tr.hit is not None, "complete": complete,
                "signal": tr.signal, "final": final,
                "fullHistory": [[int(ts - tr.born), round(v, 2)] for ts, v in tr.history]}
        try:
            with open(config.STUDY_FILE, "a") as f:
                f.write(json.dumps(line) + "\n")
        except Exception as e:  # noqa: BLE001
            log.warning("could not write %s: %s", config.STUDY_FILE, e)

    def _prune(self) -> None:
        now = time.time()
        for tr in self.tracked.values():
            # A candidate whose window closed without passing the sniper rule: stop watching it.
            if tr.candidate and not tr.hit and now - tr.born > WINDOW + 120 and tr.watching:
                self._unwatch(tr)
        for k in [k for k, tr in self.tracked.items()
                  if now - tr.born > (RUNNER_TRACK if tr.hit or (tr.candidate and config.STUDY_FILE)
                                      else FEED_TRACK) + 60]:
            tr = self.tracked.pop(k)
            self._study(tr)
            self._unwatch(tr)
            if tr.hit and k in self.runners:
                self.runners[k]["tracking"] = False
                self.runners[k]["live"] = False
        while len(self.runners) > config.MAX_RUNNERS:
            self.runners.popitem(last=False)

    # ------------------------------------------------------------------ network
    async def _fetch(self, session: aiohttp.ClientSession, batch: list[Tracked]) -> list[dict] | None:
        chain = batch[0].token["chain"]
        slug = config.DEXSCREENER_SLUGS.get(chain, chain)
        url = API.format(chain=slug, addresses=",".join(tr.token["address"] for tr in batch))
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 429:
                    log.warning("DexScreener rate limit hit; backing off this round")
                    return None
                if r.status != 200:
                    return None
                data = await r.json(content_type=None)
                return data if isinstance(data, list) else []
        except Exception:  # noqa: BLE001
            return None

    async def _refresh_sol_price(self, session: aiohttp.ClientSession) -> None:
        self.sol_usd_at = time.time()
        try:
            async with session.get(API.format(chain="solana", addresses=WSOL),
                                   timeout=aiohttp.ClientTimeout(total=10)) as r:
                pairs = await r.json(content_type=None)
            usd = [p for p in pairs if (p.get("baseToken") or {}).get("address") == WSOL
                   and (p.get("quoteToken") or {}).get("symbol") in ("USDC", "USDT")]
            best = max(usd, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0)
            price = _num(best.get("priceUsd"))
            if price and price > 0:
                self.sol_usd = price
        except Exception as e:  # noqa: BLE001
            log.info("SOL price refresh failed: %s", e)

    async def _fetch_meta(self, session: aiohttp.ClientSession, tr: Tracked) -> None:
        """Pump.fun tokens point to a JSON file with image, description and socials."""
        if tr.meta:
            return
        uri = _safe_url(_ipfs(tr.token.get("extra", {}).get("metadataUri")))
        if not uri:
            return
        try:
            async with session.get(uri, timeout=aiohttp.ClientTimeout(total=10), allow_redirects=False) as r:
                if r.status != 200:
                    return
                raw = await r.content.read(64_000)  # metadata is tiny; refuse anything big
            m = json.loads(raw)
            if not isinstance(m, dict):
                return
            tr.meta = {
                "image": _safe_url(_ipfs(m.get("image"))),
                "description": str(m.get("description") or "")[:600] or None,
                "website": _safe_url(m.get("website")),
                "twitter": _safe_url(m.get("twitter")),
                "telegram": _safe_url(m.get("telegram")),
            }
            if tr.hit:
                rec = self._record(tr)
                self.runners[tr.token["id"]] = rec
                hub.broadcast({"type": "runners", "data": [rec]})
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ persistence (optional)
    def _load(self) -> None:
        path = config.RUNNERS_FILE
        if not path or not os.path.exists(path):
            return
        try:
            with open(path) as f:
                for rec in json.load(f):
                    rec["tracking"] = False  # history survives a restart; live tracking doesn't
                    rec["live"] = False
                    self.runners[rec["id"]] = rec
            log.info("loaded %d runners from %s", len(self.runners), path)
        except Exception as e:  # noqa: BLE001
            log.warning("could not load %s: %s", path, e)

    def _save(self) -> None:
        path = config.RUNNERS_FILE
        if not path or not self.dirty:
            return
        try:
            tmp = path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(list(self.runners.values()), f)
            os.replace(tmp, path)
            self.dirty = False
        except Exception as e:  # noqa: BLE001
            log.warning("could not save %s: %s", path, e)


# ---------------------------------------------------------------------- helpers
def _thin(history: list) -> None:
    """Halve the resolution of the older part of the history, keeping the first point
    and the most recent 200 points at full resolution. The chart keeps its full shape."""
    keep_recent = 200
    old, recent = history[:-keep_recent], history[-keep_recent:]
    history[:] = old[:1] + old[1::2] + recent


def _pick_pair(pairs: list[dict], address: str) -> dict | None:
    """Of all pools containing our token (as the base token), take the most liquid one."""
    addr = address.lower()
    mine = [p for p in pairs if (p.get("baseToken") or {}).get("address", "").lower() == addr]
    if not mine:
        return None
    return max(mine, key=lambda p: ((p.get("liquidity") or {}).get("usd") or 0, (p.get("volume") or {}).get("h24") or 0))


def _summarize(p: dict) -> dict:
    change = p.get("priceChange") or {}
    volume = p.get("volume") or {}
    return {
        "priceUsd": _num(p.get("priceUsd")),
        "marketCapUsd": _num(p.get("marketCap")) or _num(p.get("fdv")),
        "liquidityUsd": _num((p.get("liquidity") or {}).get("usd")),
        "volume1hUsd": _num(volume.get("h1")),
        "change5m": _num(change.get("m5")),
        "change1h": _num(change.get("h1")),
        "dex": p.get("dexId"),
        "updatedAt": iso_now(),
    }


def _pair_detail(p: dict) -> dict:
    txns = p.get("txns") or {}
    vol = p.get("volume") or {}
    chg = p.get("priceChange") or {}
    windows = ("m5", "h1", "h6", "h24")
    return {
        "address": p.get("pairAddress"),
        "url": _safe_url(p.get("url")),
        "dex": p.get("dexId"),
        "quoteSymbol": (p.get("quoteToken") or {}).get("symbol"),
        "createdAt": _iso(p["pairCreatedAt"] / 1000) if p.get("pairCreatedAt") else None,
        "priceNative": _num(p.get("priceNative")),
        "fdvUsd": _num(p.get("fdv")),
        "txns": {w: {"buys": int((txns.get(w) or {}).get("buys") or 0),
                     "sells": int((txns.get(w) or {}).get("sells") or 0)} for w in windows},
        "volume": {w: _num(vol.get(w)) for w in windows},
        "priceChange": {w: _num(chg.get(w)) for w in windows},
    }


def _meta_from_dexscreener(info: dict) -> dict:
    socials = {s.get("type"): s.get("url") for s in info.get("socials") or [] if isinstance(s, dict)}
    websites = [w.get("url") for w in info.get("websites") or [] if isinstance(w, dict)]
    return {
        "image": _safe_url(info.get("imageUrl")),
        "description": None,
        "website": _safe_url(websites[0]) if websites else None,
        "twitter": _safe_url(socials.get("twitter")),
        "telegram": _safe_url(socials.get("telegram")),
    }


def _ipfs(u) -> str | None:
    if isinstance(u, str) and u.startswith("ipfs://"):
        return "https://ipfs.io/ipfs/" + u[len("ipfs://"):]
    return u if isinstance(u, str) else None


def _safe_url(u) -> str | None:
    """Only public https URLs. Token metadata is written by anonymous token creators, so
    never fetch or link anything else (no http, no javascript:, no internal addresses)."""
    if not isinstance(u, str) or len(u) > 500:
        return None
    try:
        p = urlparse(u.strip())
    except ValueError:
        return None
    if p.scheme != "https" or not p.hostname:
        return None
    host = p.hostname.lower()
    if host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        return None
    try:
        ipaddress.ip_address(host)
        return None  # raw IPs are never legitimate token links
    except ValueError:
        pass
    return u.strip()


tracker = Tracker()


async def run() -> None:
    await tracker.run()
