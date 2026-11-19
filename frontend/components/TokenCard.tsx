"use client";

import { memo, useState } from "react";
import { chainMeta, sourceLabel } from "@/lib/chains";
import { compactUsd, formatChange, formatPrice } from "@/lib/format";
import { formatAge, useNow } from "@/lib/useNow";
import type { Token } from "@/lib/types";

export function shortAddr(a: string) {
  return a.length > 14 ? `${a.slice(0, 6)}…${a.slice(-4)}` : a;
}

/** Only allow http(s) links that came from the backend. */
export function safeUrl(u: string | undefined) {
  return u && /^https:\/\//.test(u) ? u : undefined;
}

function Age({ iso }: { iso: string }) {
  const now = useNow();
  const fresh = now && now - Date.parse(iso) < 60_000;
  return (
    <span className={`font-mono text-xs tabular-nums ${fresh ? "text-signal" : "text-dim"}`} suppressHydrationWarning>
      {formatAge(iso, now)}
    </span>
  );
}

export function CopyButton({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
        } catch {
          // Fallback for non-secure contexts (e.g. plain http on a LAN IP)
          const ta = document.createElement("textarea");
          ta.value = text;
          document.body.appendChild(ta);
          ta.select();
          document.execCommand("copy");
          ta.remove();
        }
        setDone(true);
        setTimeout(() => setDone(false), 1200);
      }}
      title="Copy address"
      aria-label="Copy address"
      className="rounded p-1 text-faint transition-colors hover:bg-line hover:text-ink"
    >
      {done ? (
        <svg viewBox="0 0 24 24" className="size-3.5 text-signal" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="m5 12 5 5L20 7" /></svg>
      ) : (
        <svg viewBox="0 0 24 24" className="size-3.5" fill="none" stroke="currentColor" strokeWidth="2"><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V5a2 2 0 0 1 2-2h10" /></svg>
      )}
    </button>
  );
}

function LinkButton({ href, children, accent }: { href?: string; children: React.ReactNode; accent?: string }) {
  if (!href) return null;
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer nofollow"
      className="inline-flex h-7 items-center rounded border border-line-2 px-2 font-mono text-[11px] text-dim transition-colors hover:border-faint hover:text-ink"
      style={accent ? { color: accent, borderColor: `${accent}55` } : undefined}
    >
      {children}
      <svg viewBox="0 0 24 24" className="ml-1 size-3 opacity-60" fill="none" stroke="currentColor" strokeWidth="2"><path d="M7 17 17 7M8 7h9v9" /></svg>
    </a>
  );
}

/**
 * Price column. Three possible states:
 *  1. DexScreener has the token  → market cap, price, 5-minute change, liquidity
 *  2. Solana, not indexed yet    → the launch market cap in SOL from Pump.fun
 *  3. Nothing yet                → "price pending"
 */
function MarketInfo({ token }: { token: Token }) {
  const m = token.market;
  if (m && (m.marketCapUsd != null || m.priceUsd != null)) {
    const change = formatChange(m.change5m);
    const up = (m.change5m ?? 0) >= 0;
    return (
      <div className="flex flex-col items-start font-mono leading-tight sm:items-end" title={`Updated ${m.updatedAt}${m.dex ? ` · ${m.dex}` : ""}`}>
        <div className="flex items-baseline gap-1.5">
          <span className="text-[10px] uppercase tracking-wider text-faint">MC</span>
          <span className="text-sm font-semibold tabular-nums text-ink">{compactUsd(m.marketCapUsd)}</span>
          {change && (
            <span className={`text-[11px] tabular-nums ${up ? "text-signal" : "text-bad"}`} title="Price change, last 5 minutes">
              {change}
            </span>
          )}
        </div>
        <div className="text-[11px] tabular-nums text-dim">
          {formatPrice(m.priceUsd)}
          {m.liquidityUsd != null && <span className="text-faint"> · liq {compactUsd(m.liquidityUsd)}</span>}
        </div>
      </div>
    );
  }
  if (typeof token.extra?.marketCapSol === "number") {
    return (
      <div className="flex flex-col items-start font-mono leading-tight sm:items-end" title="Market cap at launch, before DexScreener has indexed the token">
        <div className="flex items-baseline gap-1.5">
          <span className="text-[10px] uppercase tracking-wider text-faint">MC</span>
          <span className="text-sm tabular-nums text-dim">{token.extra.marketCapSol.toFixed(1)} SOL</span>
        </div>
        <div className="text-[11px] text-faint">at launch</div>
      </div>
    );
  }
  return <div className="font-mono text-[11px] text-faint" title="DexScreener usually indexes new tokens within a minute or two">price pending…</div>;
}

export const TokenCard = memo(function TokenCard({ token }: { token: Token }) {
  const chain = chainMeta(token.chain);
  const pumpUrl = safeUrl(token.extra?.pumpUrl);
  const dev = token.extra?.devBuySol;

  return (
    <li
      className={`token-card group relative overflow-hidden rounded-lg border border-line bg-panel transition-colors hover:border-line-2 ${
        token._live ? "animate-slide-in" : ""
      }`}
    >
      {/* chain-colored edge */}
      <span className="absolute inset-y-0 left-0 w-[3px]" style={{ background: chain.color }} />
      <div className={`flex flex-col gap-2 py-2.5 pl-4 pr-3 sm:flex-row sm:items-center sm:gap-4 ${token._live ? "animate-flash" : ""}`}>
        {/* Left: identity */}
        <div className="flex min-w-0 flex-1 items-start gap-3">
          <span
            className="mt-0.5 w-12 shrink-0 rounded px-1 py-0.5 text-center font-mono text-[10px] font-bold tracking-wider"
            style={{ color: chain.color, background: `${chain.color}1a`, boxShadow: `inset 0 0 0 1px ${chain.color}40` }}
            title={chain.label}
          >
            {chain.short}
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex min-w-0 items-baseline gap-2">
              <span className="truncate font-semibold text-ink" title={token.name}>
                {token.name}
              </span>
              <span className="shrink-0 font-mono text-sm text-signal/90" title={token.symbol}>
                ${token.symbol.length > 14 ? token.symbol.slice(0, 14) + "…" : token.symbol}
              </span>
            </div>
            <div className="mt-0.5 flex flex-wrap items-center gap-x-2.5 gap-y-1 font-mono text-[11px] text-dim">
              <span className="flex items-center gap-0.5">
                <span title={token.address}>{shortAddr(token.address)}</span>
                <CopyButton text={token.address} />
              </span>
              <span className="rounded bg-line px-1.5 py-px text-[10px] uppercase tracking-wide text-dim">
                {sourceLabel(token.source)}
              </span>
              {typeof dev === "number" && (
                <span className="text-warn" title="SOL the creator spent buying their own token at launch">
                  dev buy {dev < 0.01 ? dev.toFixed(4) : dev.toFixed(2)} SOL
                </span>
              )}
            </div>
          </div>
          <div className="shrink-0 sm:hidden">
            <Age iso={token.detectedAt} />
          </div>
        </div>

        {/* Right: age + links */}
        <div className="flex flex-wrap items-center gap-1.5 pl-[3.75rem] sm:pl-0">
          <div className="mr-3 w-full sm:w-36">
            <MarketInfo token={token} />
          </div>
          <div className="mr-2 hidden w-24 text-right sm:block">
            <Age iso={token.detectedAt} />
          </div>
          <LinkButton href={safeUrl(token.dexscreenerUrl)}>DexScreener</LinkButton>
          {pumpUrl && (
            <LinkButton href={pumpUrl} accent="#86efac">
              Pump.fun
            </LinkButton>
          )}
          <LinkButton href={chain.explorer(token.address)}>Explorer</LinkButton>
        </div>
      </div>
    </li>
  );
});
