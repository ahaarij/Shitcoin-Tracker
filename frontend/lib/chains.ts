import type { ChainKey, Source } from "./types";

export interface ChainMeta {
  key: ChainKey;
  label: string;
  short: string;
  color: string; // brand-ish accent
  explorer: (address: string) => string;
}

const enc = encodeURIComponent;

export const CHAINS: ChainMeta[] = [
  { key: "solana", label: "Solana", short: "SOL", color: "#14F195", explorer: (a) => `https://solscan.io/token/${enc(a)}` },
  { key: "ethereum", label: "Ethereum", short: "ETH", color: "#8A9BFF", explorer: (a) => `https://etherscan.io/token/${enc(a)}` },
  { key: "bnb", label: "BNB Chain", short: "BNB", color: "#F0B90B", explorer: (a) => `https://bscscan.com/token/${enc(a)}` },
  { key: "base", label: "Base", short: "BASE", color: "#3D7BFF", explorer: (a) => `https://basescan.org/token/${enc(a)}` },
  { key: "arbitrum", label: "Arbitrum", short: "ARB", color: "#28A0F0", explorer: (a) => `https://arbiscan.io/token/${enc(a)}` },
  { key: "polygon", label: "Polygon", short: "POL", color: "#A47CFF", explorer: (a) => `https://polygonscan.com/token/${enc(a)}` },
  { key: "optimism", label: "Optimism", short: "OP", color: "#FF4D5E", explorer: (a) => `https://optimistic.etherscan.io/token/${enc(a)}` },
  { key: "avalanche", label: "Avalanche", short: "AVAX", color: "#E84142", explorer: (a) => `https://snowtrace.io/token/${enc(a)}` },
];

export const CHAIN_BY_KEY = Object.fromEntries(CHAINS.map((c) => [c.key, c])) as Record<ChainKey, ChainMeta>;

export function chainMeta(key: string): ChainMeta {
  return (
    CHAIN_BY_KEY[key as ChainKey] ?? {
      key: key as ChainKey,
      label: key,
      short: key.slice(0, 4).toUpperCase(),
      color: "#9AA4B2",
      explorer: () => "#",
    }
  );
}

const SOURCE_LABELS: Record<string, string> = {
  pumpfun: "Pump.fun",
  "uniswap-v2": "V2 pair",
  "uniswap-v3": "V3 pool",
  "uniswap-v4": "V4 pool",
  aerodrome: "Aerodrome",
};

export function sourceLabel(source: Source): string {
  return SOURCE_LABELS[source] ?? source;
}
