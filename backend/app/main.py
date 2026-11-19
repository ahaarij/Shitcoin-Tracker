"""
New Token Radar — backend service.

Runs every chain listener as a background asyncio task for the whole life of the
process, and streams each new token to browsers over a WebSocket.

    GET /health              ok + per-chain connection status
    GET /api/recent?limit=N  newest N tokens from the in-memory ring buffer
    GET /api/status          per-chain status, last event time, tokens/minute
    GET /api/runners         tokens that pumped >= +200% within 30 min of launch (configurable)
    WS  /ws                  snapshot on connect, then live {type:"token"|"status"|"market"|"runners"|"ping"}

Run locally:  uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import logging
import re
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from . import config, market
from .hub import hub
from .listeners import evm, solana

logging.basicConfig(
    level=config.LOG_LEVEL,
    format="%(asctime)s %(levelname)-7s %(name)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(_: FastAPI):
    tasks: list[asyncio.Task] = []
    if config.SOLANA_ENABLED:
        tasks.append(asyncio.create_task(solana.run(), name="solana"))
    for chain in config.EVM_CHAINS:
        tasks.append(asyncio.create_task(evm.run(chain), name=chain.key))
    if config.ENABLE_PRICES:
        tasks.append(asyncio.create_task(market.run(), name="market"))
    tasks.append(asyncio.create_task(hub.periodic(), name="periodic"))
    log.info("started listeners: %s", ", ".join(config.ENABLED_CHAINS) or "(none)")
    log.info("allowed origins: %s", config.ALLOWED_ORIGINS)
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()
        for t in tasks:
            with suppress(asyncio.CancelledError, Exception):
                await t


app = FastAPI(title="New Token Radar", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_origin_regex=config.ALLOWED_ORIGIN_REGEX,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/")
def root() -> dict:
    return {"name": "New Token Radar backend", "endpoints": ["/health", "/api/recent", "/api/status", "/ws"]}


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "chains": {
            c.chain: {"state": c.state, "endpoint": c.endpoint, "lastError": c.last_error}
            for c in hub.chains.values()
        },
    }


@app.get("/api/recent")
def recent(limit: int = Query(200, ge=1, le=1000)) -> dict:
    return {"tokens": hub.recent(limit)}


@app.get("/api/runners")
def runners(limit: int = Query(100, ge=1, le=300)) -> dict:
    """Tokens that rose >= RUNNER_MIN_GAIN_PCT within RUNNER_WINDOW_MINUTES of launch, newest first."""
    return {
        "rules": {
            "minGainPct": config.RUNNER_MIN_GAIN_PCT,
            "windowMinutes": config.RUNNER_WINDOW_MINUTES,
            "trackHours": config.RUNNER_TRACK_HOURS,
            "minLiquidityUsd": config.RUNNER_MIN_LIQUIDITY_USD,
            "maxSniperPct": config.RUNNER_MAX_SNIPER_PCT,
        },
        "runners": market.tracker.runner_list(limit),
    }


@app.get("/api/status")
def status() -> dict:
    return hub.status()


def _origin_allowed(origin: str | None) -> bool:
    """Browsers don't apply CORS to WebSockets, so we check the Origin header ourselves."""
    if "*" in config.ALLOWED_ORIGINS or not origin:
        return True  # non-browser clients (curl, scripts) send no Origin
    origin = origin.rstrip("/")
    if origin in config.ALLOWED_ORIGINS:
        return True
    return bool(config.ALLOWED_ORIGIN_REGEX and re.fullmatch(config.ALLOWED_ORIGIN_REGEX, origin))


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    if not _origin_allowed(ws.headers.get("origin")):
        log.warning("rejected websocket from origin %s", ws.headers.get("origin"))
        await ws.close(code=1008)  # policy violation
        return

    await ws.accept()
    client = hub.register(ws)
    # Snapshot first: newest tokens + current chain statuses.
    hub.send_to(client, {
        "type": "snapshot",
        "data": {
            "tokens": hub.recent(config.SNAPSHOT_SIZE),
            "status": hub.status(),
            "runners": market.tracker.runner_list(100),
        },
    })

    async def sender() -> None:
        while not client.dead:
            raw = await client.queue.get()
            await ws.send_text(raw)

    async def receiver() -> None:
        # We don't expect commands; reading just lets us notice disconnects promptly
        # and answer an application-level {"type":"ping"} from the browser.
        while True:
            msg = await ws.receive_text()
            if msg == "ping" or '"ping"' in msg:
                hub.send_to(client, {"type": "pong"})

    send_task = asyncio.create_task(sender())
    recv_task = asyncio.create_task(receiver())
    try:
        await asyncio.wait({send_task, recv_task}, return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:
        pass
    finally:
        hub.unregister(client)
        for t in (send_task, recv_task):
            t.cancel()
            with suppress(asyncio.CancelledError, WebSocketDisconnect, Exception):
                await t
        with suppress(Exception):
            await ws.close()
