"""
All runtime settings, read once from environment variables.

Nothing here needs an API key. Every default points at a free public endpoint.
See backend/.env.example for a documented list of every variable.
"""

from __future__ import annotations

import os
import ssl
from dataclasses import dataclass

import certifi

# Use certifi's CA bundle everywhere so TLS works even on machines whose Python has no
# system certificates installed (common with the python.org installer on macOS).
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class EvmChain:
    key: str          # stable id used everywhere: "ethereum", "bnb", ...
    label: str        # human name
    ws_url: str       # websocket RPC (for eth_subscribe)
    http_url: str     # HTTP RPC (for batched eth_call name()/symbol())
    dexscreener: str  # DexScreener chain slug


# key: (label, publicnode subdomain, dexscreener slug, alchemy network slug)
_EVM_DEFAULTS: dict[str, tuple[str, str, str, str]] = {
    "ethereum":  ("Ethereum",  "ethereum-rpc",            "ethereum",  "eth-mainnet"),
    "bnb":       ("BNB Chain", "bsc-rpc",                 "bsc",       "bnb-mainnet"),
    "base":      ("Base",      "base-rpc",                "base",      "base-mainnet"),
    "arbitrum":  ("Arbitrum",  "arbitrum-one-rpc",        "arbitrum",  "arb-mainnet"),
    "polygon":   ("Polygon",   "polygon-bor-rpc",         "polygon",   "polygon-mainnet"),
    "optimism":  ("Optimism",  "optimism-rpc",            "optimism",  "opt-mainnet"),
    "avalanche": ("Avalanche", "avalanche-c-chain-rpc",   "avalanche", "avax-mainnet"),
}

ALL_CHAINS = ["solana", *_EVM_DEFAULTS.keys()]
CHAIN_LABELS = {"solana": "Solana", **{k: v[0] for k, v in _EVM_DEFAULTS.items()}}


def _enabled_chains() -> list[str]:
    raw = _env("ENABLED_CHAINS", "all").lower()
    if raw in ("", "all", "*"):
        return list(ALL_CHAINS)
    wanted = {c.strip() for c in raw.split(",") if c.strip()}
    return [c for c in ALL_CHAINS if c in wanted]


def _evm_chain(key: str) -> EvmChain:
    label, sub, dex, alchemy_net = _EVM_DEFAULTS[key]
    ws = f"wss://{sub}.publicnode.com"
    http = f"https://{sub}.publicnode.com"

    # Optional: an Alchemy key upgrades every EVM chain to Alchemy's endpoints.
    alchemy = _env("ALCHEMY_API_KEY")
    if alchemy:
        ws = f"wss://{alchemy_net}.g.alchemy.com/v2/{alchemy}"
        http = f"https://{alchemy_net}.g.alchemy.com/v2/{alchemy}"

    # Explicit per-chain overrides always win, e.g. BASE_WS_URL / BASE_HTTP_URL.
    ws = _env(f"{key.upper()}_WS_URL", ws)
    http = _env(f"{key.upper()}_HTTP_URL", http)
    return EvmChain(key, label, ws, http, dex)


def _origins() -> list[str]:
    raw = _env("ALLOWED_ORIGINS", "*")
    # People often paste "https://foo.vercel.app/" with a trailing slash; browsers never send one.
    return [o.strip().rstrip("/") for o in raw.split(",") if o.strip()] or ["*"]


ENABLED_CHAINS = _enabled_chains()
EVM_CHAINS = [_evm_chain(k) for k in _EVM_DEFAULTS if k in ENABLED_CHAINS]
SOLANA_ENABLED = "solana" in ENABLED_CHAINS
SOLANA_FEEDS = [
    u.strip()
    for u in _env("SOLANA_WS_URLS", "wss://pumpportal.fun/api/data,wss://pumpdev.io/ws").split(",")
    if u.strip()
]

DEXSCREENER_SLUGS = {"solana": "solana", **{k: v[2] for k, v in _EVM_DEFAULTS.items()}}
# Live price / market cap from DexScreener's free API. Set to "false" to turn it off.
ENABLE_PRICES = _env("ENABLE_PRICES", "true").lower() not in ("0", "false", "no", "off")

# Runners: tokens whose market cap rises >= RUNNER_MIN_GAIN_PCT within RUNNER_WINDOW_MINUTES of launch.
RUNNER_MIN_GAIN_PCT = _env_int("RUNNER_MIN_GAIN_PCT", 200)        # +200% = 3x the starting market cap
RUNNER_WINDOW_MINUTES = _env_int("RUNNER_WINDOW_MINUTES", 30)
RUNNER_TRACK_HOURS = _env_int("RUNNER_TRACK_HOURS", 6)            # keep updating runners this long
RUNNER_MIN_LIQUIDITY_USD = _env_int("RUNNER_MIN_LIQUIDITY_USD", 1000)  # ignore "pumps" in near-empty pools
MAX_RUNNERS = _env_int("MAX_RUNNERS", 300)
# Sniper rule: a runner's early buyers ("snipers") may hold at most this % of supply right now.
RUNNER_MAX_SNIPER_PCT = float(_env("RUNNER_MAX_SNIPER_PCT", "10") or 10)
SNIPER_SLOTS = _env_int("SNIPER_SLOTS", 10)        # Solana: buys within this many slots of launch (~0.4 s each)
SNIPER_SECONDS = _env_int("SNIPER_SECONDS", 4)     # EVM: buys within ~this many seconds of the pool (min 1 block)
# Free public Solana RPCs used for sniper analysis, tried in order. Put a free Helius URL first for higher limits:
#   SOLANA_RPC_URLS=https://mainnet.helius-rpc.com/?api-key=YOURKEY,https://solana-rpc.publicnode.com
SOLANA_RPC_URLS = [u.strip() for u in _env(
    "SOLANA_RPC_URLS", "https://solana-rpc.publicnode.com,https://api.mainnet-beta.solana.com").split(",") if u.strip()]
# Optional: save runners to a file so they survive restarts (on Railway, attach a Volume at /data
# and set RUNNERS_FILE=/data/runners.json). Empty = memory only.
RUNNERS_FILE = _env("RUNNERS_FILE")
# Optional research log (JSON lines): one line per token that hit the gain rule (runner or rejected by the
# sniper rule), with a snapshot at signal time and its outcome over RUNNER_TRACK_HOURS. Empty = off.
STUDY_FILE = _env("STUDY_FILE")

ALLOWED_ORIGINS = _origins()
ALLOWED_ORIGIN_REGEX = _env("ALLOWED_ORIGIN_REGEX") or None  # e.g. https://.*\.vercel\.app

BUFFER_SIZE = _env_int("BUFFER_SIZE", 1000)        # tokens kept in memory for /api/recent
SNAPSHOT_SIZE = _env_int("SNAPSHOT_SIZE", 100)     # tokens sent to a browser on connect
HEARTBEAT_SECONDS = _env_int("HEARTBEAT_SECONDS", 20)
STATUS_PUSH_SECONDS = _env_int("STATUS_PUSH_SECONDS", 5)
# Reconnect a chain if its socket has been totally silent this long (public nodes occasionally
# keep a socket open but stop delivering a subscription). Quiet chains get a generous window.
EVM_STALE_SECONDS = _env_int("EVM_STALE_SECONDS", 900)
SOLANA_STALE_SECONDS = _env_int("SOLANA_STALE_SECONDS", 120)
LOG_LEVEL = _env("LOG_LEVEL", "INFO").upper()
