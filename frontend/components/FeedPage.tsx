"use client";

import { useMemo } from "react";
import { Controls } from "./Controls";
import { Header } from "./Header";
import { matches, searchQuery, useRadarContext } from "./RadarProvider";
import { TokenCard } from "./TokenCard";
import { BACKEND_URL } from "@/lib/config";
import type { Token } from "@/lib/types";

/** "/" — the live feed of every new token. */
export function FeedPage() {
  const r = useRadarContext();
  const { settings, tokens } = r;
  const query = searchQuery(settings);

  const visible = useMemo(() => {
    const out: Token[] = [];
    for (const t of tokens) {
      if (matches(t, settings, query)) {
        out.push(t);
        if (out.length >= settings.maxLen) break;
      }
    }
    return out;
  }, [tokens, settings, query]);

  const anyChainOn = Object.values(settings.chains).some(Boolean);

  return (
    <>
      <div className="sticky top-0 z-20">
        <Header
          socket={r.socket}
          status={r.status}
          reconnectIn={r.reconnectIn}
          active="feed"
          runnerCount={Object.keys(r.runners).length}
        />
        <Controls
          settings={settings}
          update={r.update}
          toggleChain={r.toggleChain}
          status={r.status}
          paused={r.paused}
          setPaused={r.setPaused}
          onToggleSound={r.toggleSound}
          onToggleNotify={r.toggleNotify}
        />
      </div>

      <main className="relative z-10 mx-auto w-full max-w-6xl flex-1 px-4 py-4">
        {r.paused && (
          <button
            type="button"
            onClick={() => r.setPaused(false)}
            className="mb-3 flex w-full items-center justify-center gap-2 rounded-lg border border-warn/40 bg-warn/10 py-2 font-mono text-sm text-warn transition-colors hover:bg-warn/15"
          >
            <span className="size-1.5 animate-pulse-dot rounded-full bg-warn" />
            Paused —{" "}
            {r.pendingCount > 0
              ? `${r.pendingCount} new token${r.pendingCount === 1 ? "" : "s"} waiting`
              : "no new tokens yet"}{" "}
            · click to resume
          </button>
        )}

        <div className="mb-2 flex items-center justify-between font-mono text-[11px] uppercase tracking-[0.14em] text-faint">
          <span>
            Showing {visible.length.toLocaleString()}
            {visible.length >= settings.maxLen ? ` (max ${settings.maxLen})` : ""}
          </span>
          <span className="hidden sm:inline">newest first</span>
        </div>

        {visible.length > 0 ? (
          <ul className="flex flex-col gap-1.5">
            {visible.map((t) => (
              <TokenCard key={t.id} token={t} />
            ))}
          </ul>
        ) : (
          <EmptyState socket={r.socket} hasTokens={tokens.length > 0} anyChainOn={anyChainOn} />
        )}
      </main>
    </>
  );
}

export function RadarSweep({ size = "size-24" }: { size?: string }) {
  return (
    <div className={`relative ${size} overflow-hidden rounded-full border border-signal/20`}>
      <div className="absolute inset-[20%] rounded-full border border-signal/15" />
      <div className="absolute inset-[40%] rounded-full border border-signal/10" />
      <div
        className="absolute inset-0 animate-sweep"
        style={{ background: "conic-gradient(from 0deg, transparent 0 70%, rgb(57 255 159 / 0.35) 100%)" }}
      />
    </div>
  );
}

function EmptyState({ socket, hasTokens, anyChainOn }: { socket: string; hasTokens: boolean; anyChainOn: boolean }) {
  let title = "Scanning chains…";
  let body = "New tokens will appear here the instant they launch.";
  if (!anyChainOn) {
    title = "All chains are hidden";
    body = "Turn on at least one chain above.";
  } else if (hasTokens) {
    title = "No matches";
    body = "Nothing matches your filters yet. Try clearing the search.";
  } else if (socket === "closed") {
    title = "Can't reach the backend";
    body = `Trying ${BACKEND_URL} — check NEXT_PUBLIC_BACKEND_URL and that the backend is running.`;
  }
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-24 text-center">
      <RadarSweep />
      <div>
        <p className="font-semibold text-ink">{title}</p>
        <p className="mt-1 max-w-md break-words text-sm text-dim">{body}</p>
      </div>
    </div>
  );
}
