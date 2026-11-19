// Number formatting for the price column.

const SUB = "₀₁₂₃₄₅₆₇₈₉";

/** $1.2K, $3.4M, $5.6B */
export function compactUsd(n: number | null | undefined): string {
  if (n == null || !isFinite(n)) return "—";
  const abs = Math.abs(n);
  if (abs >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `$${(n / 1e3).toFixed(1)}K`;
  return `$${n.toFixed(0)}`;
}

/**
 * Prices of new tokens are tiny, so we use the "subscript zeros" trick from trading
 * terminals: 0.000002499 -> $0.0₅2499 (five zeros after the decimal point).
 */
export function formatPrice(p: number | null | undefined): string {
  if (p == null || !isFinite(p) || p <= 0) return "—";
  if (p >= 1) return `$${p.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
  if (p >= 0.0001) return `$${Number(p.toPrecision(4))}`;
  // p = mantissa × 10^exp, e.g. 2.499 × 10^-6 → five zeros after the decimal point.
  let exp = Math.floor(Math.log10(p));
  let sig = Math.round((p / 10 ** exp) * 1000); // 4 significant digits, e.g. 2499
  if (sig >= 10000) {
    // 9.9999… rounded up to 10.00 → it's really 1.000 × 10^(exp+1)
    exp += 1;
    sig = 1000;
  }
  const zeros = -exp - 1;
  const digits = String(sig).replace(/0+$/, "") || "0";
  const sub = String(zeros).split("").map((d) => SUB[Number(d)]).join("");
  return `$0.0${sub}${digits}`;
}

export function formatChange(c: number | null | undefined): string | null {
  if (c == null || !isFinite(c)) return null;
  const s = Math.abs(c) >= 100 ? c.toFixed(0) : c.toFixed(1);
  return `${c > 0 ? "+" : ""}${s}%`;
}

/** 512 -> "8m 32s", 4000 -> "1h 6m" */
export function formatDuration(sec: number | null | undefined): string {
  if (sec == null || !isFinite(sec)) return "—";
  const s = Math.max(0, Math.round(sec));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}

/** +212% -> "+212%", plus the multiple: "3.1x" */
export function formatGain(pct: number | null | undefined): string {
  if (pct == null || !isFinite(pct)) return "—";
  return `${pct >= 0 ? "+" : ""}${Math.round(pct).toLocaleString()}%`;
}

export function formatMultiple(pct: number | null | undefined): string {
  if (pct == null || !isFinite(pct)) return "—";
  const x = 1 + pct / 100;
  return `${x >= 10 ? x.toFixed(0) : x.toFixed(1)}x`;
}
