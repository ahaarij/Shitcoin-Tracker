"use client";

import Link from "next/link";
import { CHAINS } from "@/lib/chains";
import type { ChainState, SocketState, Status } from "@/lib/types";

const STATE_COLOR: Record<ChainState | "unknown", string> = {
  connected: "var(--color-signal)",
  connecting: "var(--color-warn)",
  reconnecting: "var(--color-warn)",
  down: "var(--color-bad)",
  disabled: "var(--color-faint)",
  unknown: "var(--color-faint)",
};

function RadarMark() {
  return (
    <div className="relative size-9 shrink-0 overflow-hidden rounded-full border border-signal/30 bg-panel">
      <div className="absolute inset-[22%] rounded-full border border-signal/20" />
      <div
        className="absolute inset-0 animate-sweep"
        style={{ background: "conic-gradient(from 0deg, transparent 0 75%, rgb(57 255 159 / 0.55) 100%)" }}
      />
      <div className="absolute left-[62%] top-[30%] size-1.5 rounded-full bg-signal shadow-[0_0_8px_var(--color-signal)]" />
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex flex-col items-end leading-none">
      <span className="font-mono text-lg font-semibold tabular-nums text-ink sm:text-xl">{value}</span>
      <span className="mt-1 text-[10px] uppercase tracking-[0.14em] text-faint">{label}</span>
    </div>
  );
}

function NavTab({ href, active, children }: { href: string; active: boolean; children: React.ReactNode }) {
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={`flex h-8 items-center gap-1.5 rounded-md px-3 font-mono text-xs uppercase tracking-wider transition-colors ${
        active ? "bg-panel-2 text-ink shadow-[inset_0_0_0_1px_var(--color-line-2)]" : "text-dim hover:text-ink"
      }`}
    >
      {children}
    </Link>
  );
}

export function Header({
  socket,
  status,
  reconnectIn,
  active,
  runnerCount,
}: {
  socket: SocketState;
  status: Status | null;
  reconnectIn: number | null;
  active: "feed" | "runners";
  runnerCount: number;
}) {
  const byChain = new Map(status?.chains.map((c) => [c.chain, c]));
  const live = socket === "open";
  const conn =
    socket === "open"
      ? { label: "LIVE", color: "var(--color-signal)" }
      : socket === "connecting"
        ? { label: "CONNECTING", color: "var(--color-warn)" }
        : { label: reconnectIn != null ? `RETRY ${reconnectIn}s` : "OFFLINE", color: "var(--color-bad)" };

  return (
    <header className="border-b border-line bg-bg/85 backdrop-blur-md">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3">
        <div className="flex items-center gap-3">
          <RadarMark />
          <div className="leading-tight">
            <h1 className="text-[15px] font-bold uppercase tracking-[0.18em] text-ink">New Token Radar</h1>
            <div className="flex items-center gap-1.5 font-mono text-[11px]" style={{ color: conn.color }}>
              <span
                className={`size-1.5 rounded-full ${live ? "animate-pulse-dot" : ""}`}
                style={{ background: conn.color, boxShadow: `0 0 6px ${conn.color}` }}
              />
              {conn.label}
            </div>
          </div>
        </div>

        <nav className="flex items-center gap-1 rounded-lg border border-line bg-bg p-0.5" aria-label="Pages">
          <NavTab href="/" active={active === "feed"}>
            Live feed
          </NavTab>
          <NavTab href="/runners" active={active === "runners"}>
            Runners
            <span className={`rounded px-1 tabular-nums ${runnerCount ? "bg-signal/15 text-signal" : "bg-line text-faint"}`}>
              {runnerCount}
            </span>
          </NavTab>
        </nav>

        {/* Per-chain status dots */}
        <ul className="order-3 flex w-full flex-wrap items-center gap-x-3 gap-y-1.5 sm:order-none sm:w-auto sm:flex-1">
          {CHAINS.map((c) => {
            const st = byChain.get(c.key);
            const state: ChainState | "unknown" = live ? (st?.state ?? "unknown") : "unknown";
            const title = st
              ? `${c.label}: ${st.state}${st.tokensPerMinute ? ` · ${st.tokensPerMinute}/min` : ""}${st.lastError && st.state !== "connected" ? `\n${st.lastError}` : ""}`
              : c.label;
            return (
              <li key={c.key} title={title} className="flex items-center gap-1.5 font-mono text-[11px] text-dim">
                <span
                  className="size-2 rounded-full"
                  style={{
                    background: STATE_COLOR[state],
                    boxShadow: state === "connected" ? `0 0 6px ${STATE_COLOR[state]}` : undefined,
                  }}
                />
                {c.short}
              </li>
            );
          })}
        </ul>

        <div className="ml-auto flex items-center gap-5 sm:ml-0">
          <Stat label="tokens seen" value={status ? status.totalSeen.toLocaleString() : "—"} />
          <Stat label="per minute" value={status ? status.tokensPerMinute : "—"} />
        </div>
      </div>
    </header>
  );
}
