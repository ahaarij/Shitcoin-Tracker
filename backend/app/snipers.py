"""
Sniper analysis: how much of a token's supply is held right now by the wallets that bought
in the first few seconds after launch.

Solana (Pump.fun)
  1. List every transaction that touched the mint (oldest first) with getSignaturesForAddress.
     The oldest one is the creation transaction.
  2. Decode the transactions in the first SNIPER_SLOTS slots (~0.4 s each) and look at
     token-balance changes per wallet (owner).
       * wallets that receive tokens INSIDE the creation tx (other than the creator) are protocol
         accounts: the bonding curve, and Pump.fun "Mayhem mode" agent vaults. Not snipers.
       * the creator is reported separately as "dev".
       * everyone else who gained tokens in that window is a sniper.
  3. Read the current balance of every sniper token account in one getMultipleAccounts call.
     Re-checking later is just that one call (+ the mint for supply), so it's cheap.

EVM chains
  Same idea with ERC-20 Transfer logs in the first few blocks after the pool was created,
  excluding the pool / PoolManager, the token contract, burn addresses and the deployer.
  Pass-through addresses (routers that receive and forward in the same window) are dropped.
  Current holdings come from balanceOf().

Percentages are of circulating supply: total supply minus tokens parked in protocol vaults
(e.g. Mayhem agent) — the bonding curve's unsold tokens still count, like every holder tool.
All of this uses free public RPC nodes; set SOLANA_RPC_URLS (e.g. a free Helius URL) for
higher rate limits.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections import defaultdict

import aiohttp

from . import config
from .hub import iso_now

log = logging.getLogger("snipers")

MAX_SIG_PAGES = 15        # 15k transactions; a 30-minute-old token with more than that is skipped
MAX_EARLY_TXS = 80        # transactions decoded from the sniper window
TOP_WALLETS = 12          # wallets listed in the UI

TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
BURN = {"0x0000000000000000000000000000000000000000", "0x000000000000000000000000000000000000dead"}
# Approximate block times, to turn SNIPER_SECONDS into a number of blocks per chain.
BLOCK_SECONDS = {"ethereum": 12, "bnb": 0.75, "base": 2, "arbitrum": 0.25, "polygon": 2, "optimism": 2, "avalanche": 2}


class AnalysisError(Exception):
    pass


class Analyzer:
    def __init__(self) -> None:
        self.sol_sem = asyncio.Semaphore(4)  # be gentle with free Solana RPCs
        self.evm_sem = asyncio.Semaphore(4)

    # ================================================================== RPC plumbing
    async def _sol(self, session: aiohttp.ClientSession, method: str, params: list):
        last = None
        for url in config.SOLANA_RPC_URLS:
            for attempt in range(2):
                try:
                    async with self.sol_sem:
                        async with session.post(
                            url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                            timeout=aiohttp.ClientTimeout(total=20),
                        ) as r:
                            if r.status in (403, 429) or r.status >= 500:
                                last = f"HTTP {r.status} from {url}"
                                await asyncio.sleep(1.5 * (attempt + 1))
                                continue
                            data = await r.json(content_type=None)
                    if "error" in data:
                        last = f"{method}: {data['error']}"
                        break  # try the next endpoint
                    return data["result"]
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    last = f"{type(e).__name__} from {url}"
        raise AnalysisError(last or f"{method} failed")

    async def _evm(self, session: aiohttp.ClientSession, url: str, payload):
        async with self.evm_sem:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=20)) as r:
                if r.status != 200:
                    raise AnalysisError(f"HTTP {r.status}")
                return await r.json(content_type=None)

    # ================================================================== public API
    async def analyze(self, session: aiohttp.ClientSession, token: dict) -> tuple[dict, dict]:
        """First full analysis. Returns (public result, private context for cheap refreshes)."""
        if token["chain"] == "solana":
            return await self._solana(session, token)
        return await self._evm_analyze(session, token)

    async def refresh(self, session: aiohttp.ClientSession, token: dict, ctx: dict) -> dict:
        """Re-read current balances of the known snipers."""
        if token["chain"] == "solana":
            return await self._solana_balances(session, token, ctx)
        return await self._evm_balances(session, token, ctx)

    # ================================================================== Solana
    async def _solana(self, session: aiohttp.ClientSession, token: dict) -> tuple[dict, dict]:
        mint = token["address"]
        dev = token.get("extra", {}).get("creator")

        sigs: list[dict] = []
        before = None
        for _ in range(MAX_SIG_PAGES):
            opts: dict = {"limit": 1000}
            if before:
                opts["before"] = before
            page = await self._sol(session, "getSignaturesForAddress", [mint, opts])
            sigs.extend(page)
            if len(page) < 1000:
                break
            before = page[-1]["signature"]
        else:
            raise AnalysisError("too many transactions to find the launch")
        if not sigs:
            raise AnalysisError("no transactions found")
        sigs.reverse()  # oldest first
        create_sig = sigs[0]["signature"]
        create_slot = sigs[0]["slot"]
        early = [s for s in sigs if s["slot"] <= create_slot + config.SNIPER_SLOTS and not s.get("err")][:MAX_EARLY_TXS]

        txs = await asyncio.gather(*(
            self._sol(session, "getTransaction", [s["signature"], {
                "encoding": "jsonParsed", "maxSupportedTransactionVersion": 1, "commitment": "confirmed"}])
            for s in early
        ), return_exceptions=True)

        protocol: set[str] = set()
        bought: dict[str, float] = defaultdict(float)
        accounts: dict[str, set[str]] = defaultdict(set)  # owner -> token accounts
        dev_bought = 0.0
        for s, tx in zip(early, txs):
            if isinstance(tx, Exception) or not tx:
                if s["signature"] == create_sig:
                    raise AnalysisError("could not read the creation transaction")
                continue
            keys = [k["pubkey"] if isinstance(k, dict) else k for k in tx["transaction"]["message"]["accountKeys"]]
            meta = tx.get("meta") or {}
            pre = {b["accountIndex"]: _ui(b) for b in meta.get("preTokenBalances") or [] if b.get("mint") == mint}
            for b in meta.get("postTokenBalances") or []:
                if b.get("mint") != mint or not b.get("owner"):
                    continue
                owner, acct = b["owner"], keys[b["accountIndex"]]
                delta = _ui(b) - pre.get(b["accountIndex"], 0.0)
                accounts[owner].add(acct)
                if s["signature"] == create_sig:
                    if owner == dev:
                        dev_bought += max(delta, 0)
                    else:
                        protocol.add(owner)  # bonding curve, Mayhem agent vault, ...
                elif owner != dev and owner not in protocol and delta > 0:
                    bought[owner] += delta

        curve = token.get("extra", {}).get("bondingCurve")
        ctx = {
            "snipers": {o: sorted(accounts[o]) for o in bought},
            "bought": dict(bought),
            "dev": sorted(accounts.get(dev, [])) if dev else [],
            "dev_bought": dev_bought,
            # protocol vaults to subtract from supply (everything except the bonding curve)
            "vaults": sorted({a for o in protocol if o != curve for a in accounts[o]}) if curve else [],
            "window": f"first {config.SNIPER_SLOTS} slots (~{config.SNIPER_SLOTS * 0.4:.0f}s)",
            "launch_txs": len(early),
        }
        return await self._solana_balances(session, token, ctx), ctx

    async def _solana_balances(self, session: aiohttp.ClientSession, token: dict, ctx: dict) -> dict:
        mint = token["address"]
        sniper_accts = [a for accts in ctx["snipers"].values() for a in accts]
        all_accts = [mint, *sniper_accts, *ctx["dev"], *ctx["vaults"]]
        values: list = []
        for i in range(0, len(all_accts), 100):
            res = await self._sol(session, "getMultipleAccounts", [all_accts[i:i + 100], {"encoding": "jsonParsed"}])
            values.extend(res["value"])
        by_acct = dict(zip(all_accts, values))

        mint_info = (((by_acct.get(mint) or {}).get("data") or {}).get("parsed") or {}).get("info") or {}
        try:
            supply = int(mint_info["supply"]) / 10 ** int(mint_info["decimals"])
        except (KeyError, ValueError, TypeError):
            raise AnalysisError("could not read token supply")

        def bal(acct: str) -> float:
            info = ((((by_acct.get(acct) or {}).get("data") or {}).get("parsed") or {}).get("info") or {})
            return float((info.get("tokenAmount") or {}).get("uiAmount") or 0)

        circulating = max(supply - sum(bal(a) for a in ctx["vaults"]), 1.0)
        holding = {o: sum(bal(a) for a in accts) for o, accts in ctx["snipers"].items()}
        dev_bal = sum(bal(a) for a in ctx["dev"])
        ctx.update(holding=holding, dev_bal=dev_bal, circulating=circulating, method="solana")
        return _result(ctx, holding, dev_bal, circulating, method="solana")

    @staticmethod
    def apply_trade(token: dict, ctx: dict, trade: dict) -> dict | None:
        """Live Pump.fun trade by a sniper or the dev: adjust their balance right away instead of
        waiting for the next RPC re-check. Returns an updated result, or None if not relevant."""
        if ctx.get("method") != "solana" or "holding" not in ctx:
            return None
        trader = trade.get("traderPublicKey")
        try:
            amount = float(trade.get("tokenAmount") or 0)
        except (TypeError, ValueError):
            return None
        sign = 1 if trade.get("txType") == "buy" else -1 if trade.get("txType") == "sell" else 0
        if not sign or not amount:
            return None
        if trader in ctx["holding"]:
            ctx["holding"][trader] = max(0.0, ctx["holding"][trader] + sign * amount)
        elif trader == token.get("extra", {}).get("creator"):
            ctx["dev_bal"] = max(0.0, ctx["dev_bal"] + sign * amount)
        else:
            return None
        return _result(ctx, ctx["holding"], ctx["dev_bal"], ctx["circulating"], method="solana")

    # ================================================================== EVM
    async def _evm_analyze(self, session: aiohttp.ClientSession, token: dict) -> tuple[dict, dict]:
        chain = next((c for c in config.EVM_CHAINS if c.key == token["chain"]), None)
        extra = token.get("extra", {})
        if not chain or not extra.get("txHash"):
            raise AnalysisError("missing chain config or creation tx")
        url, addr = chain.http_url, token["address"].lower()

        receipt = (await self._evm(session, url, {"jsonrpc": "2.0", "id": 1, "method": "eth_getTransactionReceipt",
                                                  "params": [extra["txHash"]]})).get("result")
        if not receipt:
            raise AnalysisError("creation receipt not found")
        start = int(receipt["blockNumber"], 16)
        deployer = (receipt.get("from") or "").lower()
        blocks = max(1, math.ceil(config.SNIPER_SECONDS / BLOCK_SECONDS.get(chain.key, 2)))
        logs = (await self._evm(session, url, {"jsonrpc": "2.0", "id": 1, "method": "eth_getLogs", "params": [{
            "address": addr, "topics": [TRANSFER], "fromBlock": hex(start), "toBlock": hex(start + blocks)}]})).get("result")
        if not isinstance(logs, list):
            raise AnalysisError("eth_getLogs failed")

        exclude = {addr, deployer, *BURN}
        for k in ("pool", "poolManager"):
            if extra.get(k):
                exclude.add(extra[k].lower())
        received: dict[str, float] = defaultdict(float)
        sent: dict[str, float] = defaultdict(float)
        for lg in logs:
            if len(lg.get("topics", [])) < 3:
                continue
            frm, to = "0x" + lg["topics"][1][-40:], "0x" + lg["topics"][2][-40:]
            value = int(lg.get("data") or "0x0", 16)
            if lg.get("transactionHash") == extra["txHash"]:
                exclude.add(to)  # tokens moved inside the pool-creation tx are setup, not sniping
                continue
            received[to] += value
            sent[frm] += value
        # Drop pass-through addresses (routers) that forwarded almost everything they got.
        bought_raw = {a: v for a, v in received.items() if a not in exclude and v > 0 and sent.get(a, 0) < 0.9 * v}

        top = sorted(bought_raw, key=bought_raw.get, reverse=True)[:60]  # biggest early buyers
        ctx = {
            "snipers": {a: [a] for a in top},
            "bought_raw": {a: bought_raw[a] for a in top},
            "dev": [deployer] if deployer else [],
            "vaults": [],
            "window": f"first {blocks} block{'s' if blocks > 1 else ''} after the pool was created",
            "launch_txs": len({lg.get("transactionHash") for lg in logs}),
            "url": url,
        }
        return await self._evm_balances(session, token, ctx), ctx

    async def _evm_balances(self, session: aiohttp.ClientSession, token: dict, ctx: dict) -> dict:
        addr = token["address"]
        owners = list(ctx["snipers"])
        calls = [{"jsonrpc": "2.0", "id": 0, "method": "eth_call", "params": [{"to": addr, "data": "0x18160ddd"}, "latest"]},
                 {"jsonrpc": "2.0", "id": 1, "method": "eth_call", "params": [{"to": addr, "data": "0x313ce567"}, "latest"]}]
        for i, o in enumerate(owners + ctx["dev"]):
            calls.append({"jsonrpc": "2.0", "id": i + 2, "method": "eth_call",
                          "params": [{"to": addr, "data": "0x70a08231" + o[2:].rjust(64, "0")}, "latest"]})
        res = await self._evm(session, ctx["url"], calls)
        if not isinstance(res, list):
            raise AnalysisError("balance batch failed")
        by_id = {x.get("id"): x.get("result") for x in res if isinstance(x, dict)}
        to_int = lambda h: int(h, 16) if isinstance(h, str) and h not in ("0x", "") else 0  # noqa: E731
        decimals = to_int(by_id.get(1)) or 18
        supply = to_int(by_id.get(0)) / 10 ** decimals
        if supply <= 0:
            raise AnalysisError("could not read total supply")
        holding = {o: to_int(by_id.get(i + 2)) / 10 ** decimals for i, o in enumerate(owners)}
        dev_bal = sum(to_int(by_id.get(len(owners) + 2 + j)) / 10 ** decimals for j in range(len(ctx["dev"])))
        ctx["bought"] = {o: v / 10 ** decimals for o, v in ctx["bought_raw"].items()}
        ctx.setdefault("dev_bought", 0.0)
        ctx.update(holding=holding, dev_bal=dev_bal, circulating=supply, method="evm")
        return _result(ctx, holding, dev_bal, supply, method="evm")


def _ui(b: dict) -> float:
    try:
        return float((b.get("uiTokenAmount") or {}).get("uiAmount") or 0)
    except (TypeError, ValueError):
        return 0.0


def _result(ctx: dict, holding: dict[str, float], dev_bal: float, circulating: float, method: str) -> dict:
    pct = lambda v: round(v / circulating * 100, 2)  # noqa: E731
    bought = ctx["bought"]
    wallets = sorted(
        ({"address": o, "boughtPct": pct(bought.get(o, 0)), "holdingPct": pct(holding.get(o, 0))} for o in ctx["snipers"]),
        key=lambda w: (w["holdingPct"], w["boughtPct"]), reverse=True,
    )
    holding_pct = pct(sum(holding.values()))
    return {
        "method": method,
        "window": ctx["window"],
        "launchTxs": ctx["launch_txs"],
        "count": len(ctx["snipers"]),
        "stillHolding": sum(1 for v in holding.values() if v > 0),
        "boughtPct": pct(sum(bought.values())),
        "holdingPct": holding_pct,
        "devBoughtPct": pct(ctx.get("dev_bought", 0.0)),
        "devHoldingPct": pct(dev_bal),
        "maxAllowedPct": config.RUNNER_MAX_SNIPER_PCT,
        "passes": holding_pct <= config.RUNNER_MAX_SNIPER_PCT,
        "wallets": wallets[:TOP_WALLETS],
        "checkedAt": iso_now(),
    }


analyzer = Analyzer()
