"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { BACKEND_URL, WS_URL } from "./config";
import type { Market, Runner, RunnerRules, RunnerTick, ServerMessage, SocketState, Status, Token } from "./types";

/** Tokens kept in memory client-side (the visible list is capped separately). */
const STORE_CAP = 2000;
/** If nothing (not even a status push) arrives for this long, assume the socket is dead. */
const SILENCE_MS = 30_000;

function byNewest(a: Token, b: Token) {
  return b.detectedAt.localeCompare(a.detectedAt);
}

/**
 * Live connection to the backend.
 *  - loads /api/recent immediately so the page is never empty
 *  - opens the WebSocket, auto-reconnects with exponential backoff + jitter
 *  - batches incoming tokens into one React update per animation frame
 *  - while paused, buffers tokens and exposes how many are waiting
 *  - keeps the list of runners (tokens that pumped soon after launch) up to date
 */
export function useRadar(onNewTokens?: (tokens: Token[]) => void, onNewRunner?: (r: Runner) => void) {
  const [tokens, setTokens] = useState<Token[]>([]);
  const [status, setStatus] = useState<Status | null>(null);
  const [socket, setSocket] = useState<SocketState>("connecting");
  const [paused, setPausedState] = useState(false);
  const [pendingCount, setPendingCount] = useState(0);
  const [reconnectIn, setReconnectIn] = useState<number | null>(null);
  const [runners, setRunners] = useState<Record<string, Runner>>({});
  const [runnerRules, setRunnerRules] = useState<RunnerRules | null>(null);
  const knownRunners = useRef<Set<string> | null>(null); // null until the first list arrives

  const ids = useRef(new Set<string>());
  const incoming = useRef<Token[]>([]);
  const pending = useRef<Token[]>([]);
  const pausedRef = useRef(false);
  const frame = useRef<number | null>(null);
  const onNewRef = useRef(onNewTokens);
  onNewRef.current = onNewTokens;
  const onRunnerRef = useRef(onNewRunner);
  onRunnerRef.current = onNewRunner;

  /** Add/refresh runners. `live` = came from a real-time push (so a new one can trigger an alert). */
  const upsertRunners = useCallback((list: Runner[], live: boolean) => {
    if (!list.length && knownRunners.current) return;
    const first = knownRunners.current === null;
    knownRunners.current ??= new Set();
    for (const r of list) {
      if (!knownRunners.current.has(r.id)) {
        knownRunners.current.add(r.id);
        if (live && !first) onRunnerRef.current?.(r);
      }
    }
    setRunners((prev) => {
      const next = { ...prev };
      for (const r of list) {
        // Never let an older copy (e.g. from a slow HTTP response) overwrite a newer one.
        if (!next[r.id] || next[r.id].updatedAt <= r.updatedAt) next[r.id] = r;
      }
      return next;
    });
  }, []);

  /** Merge a batch (any order) into the list, dropping duplicates. */
  const merge = useCallback((batch: Token[]) => {
    const fresh = batch.filter((t) => !ids.current.has(t.id));
    // Tokens we already have may come back (e.g. in a reconnect snapshot) with newer prices.
    const priced = new Map(batch.filter((t) => ids.current.has(t.id) && t.market).map((t) => [t.id, t.market]));
    if (!fresh.length && !priced.size) return;
    fresh.forEach((t) => ids.current.add(t.id));
    setTokens((prev) => {
      const withPrices = priced.size ? prev.map((t) => (priced.has(t.id) ? { ...t, market: priced.get(t.id) } : t)) : prev;
      if (!fresh.length) return withPrices;
      const next = [...fresh, ...withPrices].sort(byNewest);
      if (next.length > STORE_CAP) {
        next.splice(STORE_CAP).forEach((t) => ids.current.delete(t.id));
      }
      return next;
    });
  }, []);

  const flush = useCallback(() => {
    frame.current = null;
    const batch = incoming.current;
    incoming.current = [];
    if (batch.length) merge(batch);
  }, [merge]);

  const enqueueLive = useCallback(
    (t: Token) => {
      if (ids.current.has(t.id)) return;
      const live = { ...t, _live: true };
      onNewRef.current?.([live]);
      if (pausedRef.current) {
        if (pending.current.length < STORE_CAP && !pending.current.some((p) => p.id === t.id)) {
          pending.current.push(live);
          setPendingCount(pending.current.length);
        }
        return;
      }
      incoming.current.push(live);
      frame.current ??= requestAnimationFrame(flush);
    },
    [flush],
  );

  /** Attach fresh prices to tokens already on screen (and to any waiting in the pause buffer). */
  const applyMarket = useCallback((updates: { id: string; market: Market }[]) => {
    const byId = new Map(updates.map((u) => [u.id, u.market]));
    pending.current = pending.current.map((t) => (byId.has(t.id) ? { ...t, market: byId.get(t.id) } : t));
    incoming.current = incoming.current.map((t) => (byId.has(t.id) ? { ...t, market: byId.get(t.id) } : t));
    setTokens((prev) => {
      let changed = false;
      const next = prev.map((t) => {
        const m = byId.get(t.id);
        if (!m) return t;
        changed = true;
        return { ...t, market: m };
      });
      return changed ? next : prev;
    });
  }, []);

  /** Live-trade updates: extend each runner's chart and refresh its numbers. */
  const applyTicks = useCallback((ticks: RunnerTick[]) => {
    setRunners((prev) => {
      const next = { ...prev };
      for (const t of ticks) {
        const r = next[t.id];
        if (!r) continue;
        let history = r.history;
        if (t.point) {
          const last = history[history.length - 1];
          history = last && last[0] >= t.point[0] ? [...history.slice(0, -1), t.point] : [...history, t.point];
          if (history.length > 400) {
            // Keep it light: halve the resolution of older points, never touch the latest 100.
            const old = history.slice(0, -100);
            history = [old[0], ...old.filter((_, i) => i > 0 && i % 2 === 0), ...history.slice(-100)];
          }
        }
        next[t.id] = {
          ...r,
          history,
          now: t.now,
          peak: t.peak,
          market: t.market ?? r.market,
          milestones: t.milestones,
          snipers: t.snipers ?? r.snipers,
          live: t.live,
          updatedAt: t.updatedAt,
        };
      }
      return next;
    });
  }, []);

  const setPaused = useCallback(
    (p: boolean) => {
      pausedRef.current = p;
      setPausedState(p);
      if (!p && pending.current.length) {
        merge(pending.current);
        pending.current = [];
        setPendingCount(0);
      }
    },
    [merge],
  );

  // ---- initial HTTP load (so first paint has data even before the socket opens)
  useEffect(() => {
    const ctrl = new AbortController();
    fetch(`${BACKEND_URL}/api/recent?limit=200`, { signal: ctrl.signal })
      .then((r) => (r.ok ? r.json() : null))
      .then((d: { tokens: Token[] } | null) => d?.tokens && merge(d.tokens))
      .catch(() => {});
    fetch(`${BACKEND_URL}/api/runners?limit=300`, { signal: ctrl.signal })
      .then((r) => (r.ok ? r.json() : null))
      .then((d: { rules: RunnerRules; runners: Runner[] } | null) => {
        if (!d) return;
        setRunnerRules(d.rules);
        upsertRunners(d.runners, false);
      })
      .catch(() => {});
    fetch(`${BACKEND_URL}/api/status`, { signal: ctrl.signal })
      .then((r) => (r.ok ? r.json() : null))
      .then((s: Status | null) => s && setStatus((cur) => cur ?? s))
      .catch(() => {});
    return () => ctrl.abort();
  }, [merge, upsertRunners]);

  // ---- WebSocket with reconnect
  useEffect(() => {
    let ws: WebSocket | null = null;
    let attempt = 0;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let countdown: ReturnType<typeof setInterval> | null = null;
    let watchdog: ReturnType<typeof setTimeout> | null = null;
    let disposed = false;

    const armWatchdog = () => {
      if (watchdog) clearTimeout(watchdog);
      watchdog = setTimeout(() => ws?.close(), SILENCE_MS);
    };

    const scheduleReconnect = () => {
      if (disposed) return;
      // 1s, 2s, 4s ... capped at 30s, with +/-30% jitter so many tabs don't stampede.
      const base = Math.min(30_000, 1000 * 2 ** attempt);
      const delay = Math.round(base * (0.7 + Math.random() * 0.6));
      attempt++;
      const until = Date.now() + delay;
      setReconnectIn(Math.ceil(delay / 1000));
      countdown = setInterval(() => setReconnectIn(Math.max(0, Math.ceil((until - Date.now()) / 1000))), 500);
      retryTimer = setTimeout(connect, delay);
    };

    function connect() {
      if (countdown) clearInterval(countdown);
      setReconnectIn(null);
      setSocket("connecting");
      try {
        ws = new WebSocket(WS_URL);
      } catch {
        setSocket("closed");
        scheduleReconnect();
        return;
      }

      ws.onopen = () => {
        attempt = 0;
        setSocket("open");
        armWatchdog();
      };

      ws.onmessage = (ev) => {
        armWatchdog();
        let msg: ServerMessage;
        try {
          msg = JSON.parse(ev.data as string);
        } catch {
          return;
        }
        switch (msg.type) {
          case "snapshot":
            merge(msg.data.tokens); // fills any gap from while we were disconnected
            setStatus(msg.data.status);
            if (msg.data.runners) upsertRunners(msg.data.runners, false);
            break;
          case "runners":
            upsertRunners(msg.data, true);
            break;
          case "tick":
            applyTicks(msg.data);
            break;
          case "token":
            enqueueLive(msg.data);
            break;
          case "status":
            setStatus(msg.data);
            break;
          case "market":
            applyMarket(msg.data);
            break;
          default:
            break; // ping / pong: the watchdog reset above is all we need
        }
      };

      ws.onclose = () => {
        if (watchdog) clearTimeout(watchdog);
        ws = null;
        if (disposed) return;
        setSocket("closed");
        scheduleReconnect();
      };

      ws.onerror = () => ws?.close();
    }

    // Reconnect right away when the tab becomes visible again or the network comes back.
    const kick = () => {
      if (!ws && !disposed && document.visibilityState === "visible") {
        if (retryTimer) clearTimeout(retryTimer);
        attempt = 0;
        connect();
      }
    };
    document.addEventListener("visibilitychange", kick);
    window.addEventListener("online", kick);

    connect();

    return () => {
      disposed = true;
      document.removeEventListener("visibilitychange", kick);
      window.removeEventListener("online", kick);
      if (retryTimer) clearTimeout(retryTimer);
      if (countdown) clearInterval(countdown);
      if (watchdog) clearTimeout(watchdog);
      if (frame.current) cancelAnimationFrame(frame.current);
      frame.current = null;
      ws?.close();
    };
  }, [merge, enqueueLive, applyMarket, upsertRunners, applyTicks]);

  return { tokens, status, socket, reconnectIn, paused, setPaused, pendingCount, runners, runnerRules };
}
