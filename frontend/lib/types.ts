// Shapes shared with the backend (see backend/app/hub.py and listeners/*).

export type ChainKey =
  | "solana"
  | "ethereum"
  | "bnb"
  | "base"
  | "arbitrum"
  | "polygon"
  | "optimism"
  | "avalanche";

export type Source = "pumpfun" | "uniswap-v2" | "uniswap-v3" | "aerodrome" | "uniswap-v4" | string;

/** Live market data from DexScreener, attached by the backend once the token is indexed. */
export interface Market {
  priceUsd: number | null;
  marketCapUsd: number | null;
  liquidityUsd: number | null;
  volume1hUsd: number | null;
  change5m: number | null;
  change1h: number | null;
  dex: string | null;
  updatedAt: string;
}

export interface Token {
  id: string;
  chain: ChainKey;
  name: string;
  symbol: string;
  address: string;
  detectedAt: string; // ISO timestamp
  source: Source;
  dexscreenerUrl: string;
  extra: {
    devBuySol?: number;
    pumpUrl?: string;
    marketCapSol?: number;
    txHash?: string;
    creator?: string;
  };
  market?: Market;
  /** Client-only: true if it arrived live (gets the slide-in animation). */
  _live?: boolean;
}

type Windows<T> = { m5: T; h1: T; h6: T; h24: T };

/** Early buyers ("snipers") of a token and how much they still hold. */
export interface Snipers {
  method: "solana" | "evm";
  /** e.g. "first 10 slots (~4s)" */
  window: string;
  launchTxs: number;
  count: number;
  stillHolding: number;
  /** % of circulating supply they bought in the sniper window */
  boughtPct: number;
  /** % of circulating supply they hold right now */
  holdingPct: number;
  devBoughtPct: number;
  devHoldingPct: number;
  maxAllowedPct: number;
  passes: boolean;
  wallets: { address: string; boughtPct: number; holdingPct: number }[];
  checkedAt: string;
}

/** A token whose market cap rose >= the threshold (default +200%) within 30 min of launch. */
export interface Runner {
  id: string;
  chain: ChainKey;
  name: string;
  symbol: string;
  address: string;
  source: Source;
  detectedAt: string;
  dexscreenerUrl: string;
  extra: Token["extra"];
  /** Starting market cap the gain is measured from. "launch" = true launch value (Pump.fun); "first-seen" = first DexScreener price. */
  baseline: { mcUsd: number | null; kind: "launch" | "first-seen" | null };
  /** The moment it crossed the threshold. */
  hit: { at: string; ageSec: number; mcUsd: number; gainPct: number; verifiedAt?: string; sniperPctAtVerify?: number };
  peak: { mcUsd: number | null; gainPct: number | null; at: string | null; ageSec: number | null };
  now: { mcUsd: number | null; gainPct: number | null; fromPeakPct: number | null };
  market: Market | null;
  pair: {
    address: string | null;
    url: string | null;
    dex: string | null;
    quoteSymbol: string | null;
    createdAt: string | null;
    priceNative: number | null;
    fdvUsd: number | null;
    txns: Windows<{ buys: number; sells: number }>;
    volume: Windows<number | null>;
    priceChange: Windows<number | null>;
  } | null;
  meta: {
    image: string | null;
    description: string | null;
    website: string | null;
    twitter: string | null;
    telegram: string | null;
  } | null;
  snipers: Snipers | null;
  /** true while live trades are streaming in (Solana) */
  live?: boolean;
  /** "% gain" -> seconds after launch it was first reached, e.g. {"200": 512} */
  milestones: Record<string, number>;
  /** [secondsAfterLaunch, marketCapUsd] samples */
  history: [number, number][];
  /** false once the backend stopped refreshing it (after RUNNER_TRACK_HOURS, or after a restart) */
  tracking: boolean;
  updatedAt: string;
}

export interface RunnerRules {
  minGainPct: number;
  windowMinutes: number;
  trackHours: number;
  minLiquidityUsd: number;
  maxSniperPct?: number;
}

/** Real-time update for one runner (live trades), pushed at most once a second. */
export interface RunnerTick {
  id: string;
  point: [number, number] | null;
  now: Runner["now"];
  peak: Runner["peak"];
  market: Market | null;
  milestones: Runner["milestones"];
  snipers: Snipers | null;
  live: boolean;
  updatedAt: string;
}

export type ChainState = "connecting" | "connected" | "reconnecting" | "down" | "disabled";

export interface ChainStatus {
  chain: ChainKey;
  label: string;
  state: ChainState;
  lastEventAt: string | null;
  connectedSince: string | null;
  lastError: string | null;
  tokensPerMinute: number;
  total: number;
}

export interface Status {
  startedAt: string;
  now: string;
  totalSeen: number;
  tokensPerMinute: number;
  clients: number;
  chains: ChainStatus[];
}

export type ServerMessage =
  | { type: "snapshot"; data: { tokens: Token[]; status: Status; runners?: Runner[] } }
  | { type: "runners"; data: Runner[] }
  | { type: "tick"; data: RunnerTick[] }
  | { type: "token"; data: Token }
  | { type: "status"; data: Status }
  | { type: "market"; data: { id: string; market: Market }[] }
  | { type: "ping"; t: string }
  | { type: "pong" };

export type SocketState = "connecting" | "open" | "closed";
