"""
The Hub is the single shared piece of state:

  * a ring buffer of the most recent tokens (for /api/recent and WS snapshots)
  * a bounded de-duplication set
  * per-chain connection status + tokens-per-minute counters
  * the set of connected browser WebSocket clients, with fan-out broadcast

Everything runs on one asyncio event loop, so no locks are needed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket

from . import config

log = logging.getLogger("hub")


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class BoundedSet:
    """A set that forgets its oldest entries once it reaches `maxlen` (keeps memory flat forever)."""

    def __init__(self, maxlen: int) -> None:
        self._d: OrderedDict[str, None] = OrderedDict()
        self._max = maxlen

    def __contains__(self, key: str) -> bool:
        return key in self._d

    def add(self, key: str) -> bool:
        """Add key; return False if it was already present."""
        if key in self._d:
            return False
        self._d[key] = None
        if len(self._d) > self._max:
            self._d.popitem(last=False)
        return True


@dataclass
class ChainStatus:
    chain: str
    label: str
    state: str = "connecting"          # connecting | connected | reconnecting | down | disabled
    last_event_at: str | None = None
    connected_since: str | None = None
    last_error: str | None = None
    failures: int = 0                   # consecutive failed connection attempts
    total: int = 0
    endpoint: str | None = None
    _events: deque = field(default_factory=deque)  # monotonic timestamps within the last 60s

    def tokens_per_minute(self) -> int:
        cutoff = time.monotonic() - 60
        while self._events and self._events[0] < cutoff:
            self._events.popleft()
        return len(self._events)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chain": self.chain,
            "label": self.label,
            "state": self.state,
            "lastEventAt": self.last_event_at,
            "connectedSince": self.connected_since,
            "lastError": self.last_error,
            "tokensPerMinute": self.tokens_per_minute(),
            "total": self.total,
        }


class Client:
    """One connected browser. A bounded queue protects us from slow consumers."""

    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=2000)
        self.dead = False


class Hub:
    def __init__(self) -> None:
        self.tokens: deque[dict] = deque(maxlen=config.BUFFER_SIZE)
        self.seen = BoundedSet(200_000)
        self.total_seen = 0
        self.started_at = iso_now()
        self.clients: set[Client] = set()
        self.on_token: list = []
        self.on_trade: list = []  # callbacks for live Solana trades of watched tokens  # callbacks run for every new token (the price tracker registers here)
        self.chains: dict[str, ChainStatus] = {}
        for key in config.ALL_CHAINS:
            st = ChainStatus(key, config.CHAIN_LABELS[key])
            if key not in config.ENABLED_CHAINS:
                st.state = "disabled"
            self.chains[key] = st

    # ------------------------------------------------------------------ tokens
    def add_token(self, token: dict) -> bool:
        """Store + broadcast a normalized token. Returns False if it was a duplicate."""
        if not self.seen.add(token["id"]):
            return False
        self.tokens.append(token)
        self.total_seen += 1
        st = self.chains[token["chain"]]
        st.total += 1
        st.last_event_at = token["detectedAt"]
        st._events.append(time.monotonic())
        for cb in self.on_token:
            try:
                cb(token)
            except Exception:  # noqa: BLE001
                log.exception("on_token callback failed")
        self.broadcast({"type": "token", "data": token})
        return True

    def recent(self, limit: int) -> list[dict]:
        """Newest first."""
        limit = max(0, min(limit, len(self.tokens)))
        return [self.tokens[-1 - i] for i in range(limit)]

    # ------------------------------------------------------------------ status
    def set_state(self, chain: str, state: str, error: str | None = None, endpoint: str | None = None) -> None:
        st = self.chains[chain]
        if state == "connected":
            st.failures = 0
            st.last_error = None
            st.connected_since = iso_now()
        elif state == "reconnecting":
            st.failures += 1
            st.connected_since = None
            if error:
                st.last_error = error
            # After several failures in a row, report the chain as "down" (red dot in the UI).
            if st.failures >= 3:
                state = "down"
        if endpoint:
            st.endpoint = endpoint
        changed = st.state != state
        st.state = state
        if changed:
            log.info("%-9s -> %s%s", chain, state, f" ({error})" if error else "")
            self.broadcast({"type": "status", "data": self.status()})

    def status(self) -> dict[str, Any]:
        chains = [c.to_dict() for c in self.chains.values()]
        return {
            "startedAt": self.started_at,
            "now": iso_now(),
            "totalSeen": self.total_seen,
            "tokensPerMinute": sum(c["tokensPerMinute"] for c in chains),
            "clients": len(self.clients),
            "chains": chains,
        }

    # ------------------------------------------------------------------ clients
    def register(self, ws: WebSocket) -> Client:
        client = Client(ws)
        self.clients.add(client)
        return client

    def unregister(self, client: Client) -> None:
        client.dead = True
        self.clients.discard(client)

    def send_to(self, client: Client, msg: dict) -> None:
        self._enqueue(client, json.dumps(msg, separators=(",", ":")))

    def broadcast(self, msg: dict) -> None:
        if not self.clients:
            return
        raw = json.dumps(msg, separators=(",", ":"))  # serialize once for everyone
        for client in list(self.clients):
            self._enqueue(client, raw)

    def _enqueue(self, client: Client, raw: str) -> None:
        if client.dead:
            return
        try:
            client.queue.put_nowait(raw)
        except asyncio.QueueFull:
            # The browser isn't reading fast enough (tab frozen, bad network). Drop it;
            # it will reconnect and get a fresh snapshot.
            log.warning("dropping slow client")
            self.unregister(client)
            asyncio.create_task(self._close(client))

    @staticmethod
    async def _close(client: Client) -> None:
        try:
            await client.ws.close(code=1013)  # 1013 = "try again later"
        except Exception:
            pass

    async def periodic(self) -> None:
        """Push status every few seconds (keeps tokens/min fresh) and a heartbeat ping."""
        last_ping = time.monotonic()
        while True:
            await asyncio.sleep(config.STATUS_PUSH_SECONDS)
            self.broadcast({"type": "status", "data": self.status()})
            if time.monotonic() - last_ping >= config.HEARTBEAT_SECONDS:
                last_ping = time.monotonic()
                self.broadcast({"type": "ping", "t": iso_now()})


hub = Hub()
