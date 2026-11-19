# 🔭 New Token Radar

A live, real-time feed of brand-new crypto tokens launching across many blockchains.

| Chain | How new tokens are detected |
|---|---|
| **Solana** | Every new Pump.fun token, via the free PumpPortal and pumpdev.io WebSockets (both at once, de-duplicated) |
| **Ethereum, BNB Chain, Base, Arbitrum, Polygon, Optimism, Avalanche** | Every token that gets its first pool on Uniswap v2/v3/v4 or a fork (PancakeSwap, SushiSwap, Aerodrome, Velodrome…), via free publicnode.com RPC nodes |

Each token shows its **market cap, price, 5-minute change and liquidity**, refreshed about every
30 s from DexScreener's free API. Brand-new Solana tokens show their launch market cap (in SOL)
until DexScreener has indexed them, which usually takes a minute or two.

A second page, **Runners** (`/runners`), lists every token whose market cap rose **+200% or more
within 30 minutes of launch** *and* whose snipers (wallets that bought in the first seconds) hold
**10% or less** of the supply, with full details: launch / hit / peak / current market cap, how fast
it got there, a market-cap chart since launch, 2x–21x milestones, price, liquidity, volume,
buys vs sells, dev buy, creator, socials, warning signs, and every useful link. Each runner keeps
updating for 6 hours. Optional chime and browser notification for new runners.

**100% free. No API keys needed.**

```
┌──────────────────────────────┐         ┌─────────────────────────────┐
│  Railway (backend/)          │  HTTPS  │  Vercel (frontend/)         │
│  FastAPI + uvicorn           │ ◀────── │  Next.js app in the browser │
│  • 8 chain listeners running │  WSS    │  • live feed, filters,      │
│    24/7 as asyncio tasks     │ ──────▶ │    search, pause, alerts    │
│  • /ws pushes every token    │         │                             │
└──────────────────────────────┘         └─────────────────────────────┘
```

The backend has to run on Railway (or any always-on server) because it keeps WebSocket connections
open forever. Vercel's serverless functions can't do that, so Vercel only hosts the website.

> ⚠️ **Most brand-new tokens are high-risk or outright scams** (honeypots, rug pulls). This is a
> discovery tool, not financial advice.

---

## Project layout

```
backend/                 Python service → deploy to Railway
  app/main.py            FastAPI app: /health, /api/recent, /api/status, /ws
  app/hub.py             shared state: ring buffer, dedupe, chain status, client broadcast
  app/config.py          every setting, read from environment variables
  app/listeners/solana.py  Pump.fun feed
  app/listeners/evm.py     EVM pool-creation listener (one task per chain)
  app/market.py          live prices from DexScreener + runner detection, pushed to browsers
  Dockerfile, railway.json, requirements.txt, .env.example
frontend/                Next.js (App Router, TypeScript, Tailwind) → deploy to Vercel
  app/page.tsx           "/"         live feed      (components/FeedPage.tsx)
  app/runners/page.tsx   "/runners"  runners page   (components/RunnersPage.tsx, RunnerCard.tsx, McChart.tsx)
  components/RadarProvider.tsx  one shared live connection + settings for both pages
  lib/useRadar.ts        WebSocket connection, reconnect, batching, pause buffer
  lib/useSettings.ts     filters/settings saved in localStorage
  .env.example
scripts/new_tokens_all_chains.py   the original command-line script (still works on its own)
```

---

## 1. Run it on your computer

You need **Python 3.10+** and **Node.js 20+**. Check with `python3 --version` and `node --version`.

### Backend (terminal #1)

```bash
cd backend
python3 -m venv .venv                 # create an isolated Python environment
source .venv/bin/activate             # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Within a few seconds you should see lines like `solana -> connected`, `base -> connected`.
Open <http://localhost:8000/api/status> to see per-chain status, or
<http://localhost:8000/api/recent?limit=5> to see the latest tokens.

### Frontend (terminal #2)

```bash
cd frontend
npm install
cp .env.example .env.local            # contains NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
npm run dev
```

Open <http://localhost:3000>. Tokens start appearing at the top as they launch.

---

## 2. Put the code on GitHub

Railway and Vercel both deploy straight from a GitHub repository.

1. Create a new **empty** repository on <https://github.com/new> (e.g. `new-token-radar`).
2. In this folder:
   ```bash
   git init
   git add .
   git commit -m "New Token Radar"
   git branch -M main
   git remote add origin https://github.com/<your-username>/new-token-radar.git
   git push -u origin main
   ```
   The `.gitignore` already keeps `node_modules`, `.venv` and `.env` files out of the repo.

---

## 3. Deploy the backend to Railway

1. Go to <https://railway.com> and sign in with GitHub.
2. Click **New Project** → **Deploy from GitHub repo** → pick `new-token-radar`.
   (If it's not listed, click **Configure GitHub App** and give Railway access to the repo.)
3. Railway creates a service. Click it, then open the **Settings** tab:
   - **Source → Root Directory:** type `/backend` and press Enter.
     Railway now finds `backend/Dockerfile` and `backend/railway.json` automatically.
   - **Networking → Public Networking:** click **Generate Domain**. If asked for a port, use the
     one Railway suggests (the app listens on Railway's `$PORT` automatically).
     You'll get a URL like `https://new-token-radar-production.up.railway.app`. **Copy it.**
4. Open the **Variables** tab and add (optional for now — the defaults work):
   | Variable | Value |
   |---|---|
   | `ALLOWED_ORIGINS` | `*` for now (we'll lock it to your Vercel URL in step 5) |
   | `ENABLED_CHAINS` | `all` (or e.g. `solana,base,bnb`) |

   Do **not** set `PORT` — Railway sets it for you.
5. Railway redeploys automatically. Go to **Deployments → View Logs**: you should see each chain
   connect. Then visit `https://<your-railway-url>/health` in your browser; it should show
   `"ok": true` and each chain's state.

> 💡 **Optional: keep runners across redeploys.** Runners live in memory, so a redeploy clears them.
> To keep them: in your Railway service, click **+ New → Volume** (or right-click the service →
> **Attach Volume**), set the mount path to `/data`, then add the variable
> `RUNNERS_FILE=/data/runners.json`. They're saved every minute. Volumes may cost a little on
> paid plans.

> 💡 Railway's free trial gives you a one-time credit; after that the Hobby plan is about $5/month.
> This service is light (well under 256 MB RAM). Keep **one replica**. Each replica has its own
> in-memory feed.

---

## 4. Deploy the frontend to Vercel

1. Go to <https://vercel.com> and sign in with GitHub.
2. Click **Add New… → Project** → **Import** your `new-token-radar` repo.
3. On the configure screen:
   - **Root Directory:** click **Edit**, choose `frontend`, click **Continue**.
     Framework Preset should switch to **Next.js** automatically.
   - **Environment Variables:** add
     - Name: `NEXT_PUBLIC_BACKEND_URL`
     - Value: your Railway URL from step 3, e.g. `https://new-token-radar-production.up.railway.app`
       (no trailing slash; the app derives `wss://…/ws` from it automatically)
4. Click **Deploy**. After about a minute you get a URL like `https://new-token-radar.vercel.app`.

> If you change `NEXT_PUBLIC_BACKEND_URL` later, you must **redeploy** on Vercel
> (Deployments → ⋯ → Redeploy). It gets baked in at build time.

---

## 5. Lock the backend to your Vercel site

1. Back in Railway → your service → **Variables**.
2. Set `ALLOWED_ORIGINS` to your Vercel URL, exactly as it appears in the browser address bar:
   ```
   https://new-token-radar.vercel.app
   ```
   Several sites? Separate them with commas: `https://a.vercel.app,https://radar.mydomain.com`
3. Optional, to also allow Vercel **preview** deployments, add:
   ```
   ALLOWED_ORIGIN_REGEX=https://new-token-radar-.*\.vercel\.app
   ```
4. Railway redeploys. Open your Vercel site; the header should say **LIVE** with green dots.

The backend checks the browser's `Origin` both for normal API requests (CORS) and for the
WebSocket. Browsers don't apply CORS to WebSockets, so the backend does this check itself.

---

## The Runners page

A token becomes a **runner** when both are true:

1. its market cap is at least **+200% (3×)** above its starting value while it is **less than 30 minutes old**, and
2. its **snipers hold 10% or less** of the supply right now.

A token that passes rule 1 but not rule 2 is re-checked every 45 seconds until its 30-minute
window closes (snipers often dump quickly, so it can still qualify).

**What's a sniper?** Any wallet, other than the creator, that bought in the first ~4 seconds
after launch (Solana: the first 10 slots; EVM: the first few blocks after the pool was created).
The backend finds them by reading the token's earliest transactions from free public nodes,
then checks how much they still hold.
- On Pump.fun, wallets that receive tokens *inside* the creation transaction itself (the bonding
  curve, "Mayhem mode" agent vaults) are protocol accounts, not snipers.
- Percentages are of circulating supply.
- Holdings are re-checked every minute, and on Solana they also update instantly whenever a
  sniper or the dev trades.
- Limitation: a sniper who moves tokens to a different wallet looks like they sold.

- **Starting value on Solana / Pump.fun:** the real launch market cap (Pump.fun reports it in SOL,
  converted at the live SOL price; usually about $2K).
- **Starting value on EVM chains:** there's no launch price in the data, so it's the first market
  cap DexScreener reports, typically within a minute of launch.
- Prices are checked about every 30 seconds until a token qualifies on gain, so a spike shorter
  than that can be missed and the "hit" time can be up to ~30 s late.
- **Real-time charts:** once a Solana token qualifies on gain, the backend subscribes to its live
  trades, so its chart and numbers update on every trade (pushed at most once a second; a green
  **LIVE** badge shows on the chart). EVM runners refresh every ~10 seconds.
- EVM pumps in pools with under $1,000 liquidity are ignored (they're almost always noise).

What you'll see on each runner:
- **Big green number:** the peak gain, and how many times its launch value that is.
  **"hit +238% in 10m 0s"** shows when it qualified.
- **Launch / When it hit / Peak / Now:** market cap at each point. "pk" is how far it has fallen from its peak.
- **Chart:** market cap since launch. The dashed lines are the launch value and the +200% line;
  the yellow dot is where it qualified. Hover or touch for exact values.
- **Snipers panel:** how much the snipers hold now vs the 10% limit, how many wallets, how many
  are still in, how much they bought and sold, dev bought / dev holds, and an expandable list of
  sniper wallets with links.
- **Milestones:** when it first reached 2×, 3×, 4×, 6×, 11× and 21×.
- **Buys vs sells:** transaction counts for 5 min, 1 h and 24 h.
- **Warning chips:** e.g. "Down 60% from peak", "More sells than buys", "Thin liquidity",
  "Still on bonding curve" (Pump.fun tokens that haven't graduated to a real pool yet).
- **Links:** DexScreener, Pump.fun, block explorer, plus the token's own website / X / Telegram when
  it has them. These come from the creator and are **unverified**.

Controls: chain filter, search, minimum peak (+200 / +300 / +500 / +1000%), sort (newest, biggest
peak, highest now, fastest), **Still up only** (hides tokens that already dumped back below the
threshold), and **Alert me** (chime + notification for each new runner, on either page).

> Most runners spike in the first minute or two (snipers and bots buying at launch) and many dump
> just as fast. A runner is not a buy signal.

## Using the app

- **Chain chips**: click to show/hide a chain. **Shift-click** shows only that chain (shift-click again to show all).
- **Search**: matches name, `$symbol` or address.
- **Pause**: freezes the list; new tokens are buffered and shown as "N new tokens waiting". Click to resume.
- **Sound / Notify**: a short beep and/or a browser notification for tokens that match your current filters (throttled during bursts).
- **Show**: how many tokens to keep on screen (50–1000).
- Your filters and settings are saved in your browser.
- Header: connection state, a status dot per chain (green = connected, yellow = connecting/reconnecting,
  red = failing repeatedly, grey = disabled/unknown), total tokens seen since the backend started, and tokens per minute.

---

## Backend API

| Endpoint | Description |
|---|---|
| `GET /health` | `{ ok: true, chains: { solana: { state, endpoint, lastError }, … } }` (used by Railway's health check) |
| `GET /api/recent?limit=200` | `{ tokens: [...] }` newest first, from an in-memory ring buffer (1000 by default) |
| `GET /api/runners?limit=100` | `{ rules, runners: [...] }` newest first (see `Runner` in `frontend/lib/types.ts`) |
| `GET /api/status` | totals, tokens/minute, and per-chain `state`, `lastEventAt`, `tokensPerMinute`, `lastError` |
| `WS /ws` | First message: `{type:"snapshot", data:{tokens, status}}` (100 newest). Then live `{type:"token", data}`, `{type:"status", data}` every 5 s and on changes, `{type:"market", data:[{id, market}]}` price updates, `{type:"runners", data:[...]}` new/updated runners, `{type:"tick", data:[...]}` live chart updates for runners (≤1/s each), and `{type:"ping"}` heartbeats every 20 s. Slow or dead clients get dropped. |

Every token has the same shape:

```json
{
  "id": "solana:EZ2dTB5…pump",
  "chain": "solana",
  "name": "GTAINU",
  "symbol": "INU",
  "address": "EZ2dTB5…pump",
  "detectedAt": "2026-11-18T13:12:48.975Z",
  "source": "pumpfun",
  "dexscreenerUrl": "https://dexscreener.com/solana/EZ2dTB5…pump",
  "extra": { "devBuySol": 0.0593, "pumpUrl": "https://pump.fun/coin/…", "marketCapSol": 28.07, "txHash": "…", "creator": "…" }
}
```

Once DexScreener has indexed a token, it also gets a `market` field:
`{ priceUsd, marketCapUsd, liquidityUsd, volume1hUsd, change5m, change1h, dex, updatedAt }`.
The backend refreshes prices for tokens up to 1 hour old, using about 50 of DexScreener's
300 requests/minute free limit, no matter how many people have the site open.

`source` is one of `pumpfun`, `uniswap-v2`, `uniswap-v3`, `aerodrome`, `uniswap-v4`. Note that
`uniswap-v2` and `uniswap-v3` include forks such as PancakeSwap and SushiSwap, because they emit
the same event. EVM tokens carry `extra.txHash`.

### Backend environment variables

All are optional. See `backend/.env.example` for the full list.

| Variable | Default | Purpose |
|---|---|---|
| `ALLOWED_ORIGINS` | `*` | Comma-separated browser origins allowed |
| `ALLOWED_ORIGIN_REGEX` | none | Extra allowed origins by regex (Vercel previews) |
| `ENABLED_CHAINS` | `all` | e.g. `solana,base,bnb` |
| `ALCHEMY_API_KEY` | none | Switch all EVM chains to Alchemy endpoints |
| `<CHAIN>_WS_URL` / `<CHAIN>_HTTP_URL` | publicnode | Per-chain RPC override, e.g. `BASE_WS_URL` |
| `SOLANA_WS_URLS` | pumpportal, pumpdev | Solana feeds, all used at once and de-duplicated |
| `ENABLE_PRICES` | `true` | Fetch live prices from DexScreener (also powers Runners) |
| `RUNNER_MIN_GAIN_PCT` | `200` | Gain needed to count as a runner (200 = 3×) |
| `RUNNER_WINDOW_MINUTES` | `30` | ...within this many minutes of launch |
| `RUNNER_TRACK_HOURS` | `6` | Keep updating runners this long |
| `RUNNER_MIN_LIQUIDITY_USD` | `1000` | Ignore pumps in pools smaller than this |
| `RUNNER_MAX_SNIPER_PCT` | `10` | Max % of supply snipers may hold |
| `SNIPER_SLOTS` / `SNIPER_SECONDS` | `10` / `4` | What counts as "the first seconds" (Solana slots / EVM seconds) |
| `SOLANA_RPC_URLS` | publicnode, solana.com | Solana RPCs for sniper checks; a free Helius URL raises limits |
| `RUNNERS_FILE` | none | e.g. `/data/runners.json` to keep runners across restarts |
| `STUDY_FILE` | none | e.g. `/data/study.jsonl`: research log of runner candidates (download at `/api/study`) |
| `LAUNCH_FILE` | none | e.g. `/data/launches.jsonl.gz` (compressed): every trade in the first 10 min of every Pump.fun launch + 6 h outcome (download at `/api/launches`, progress at `/api/launches/stats`) |
| `SOLANA_LOGS_WS_URLS` | `wss://api.mainnet-beta.solana.com` | where every Pump.fun trade is read from; a free Helius WebSocket URL gives complete coverage. `off` disables it |
| `BUFFER_SIZE` / `SNAPSHOT_SIZE` | 1000 / 100 | Tokens kept in memory / sent on connect |

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Header says **OFFLINE / RETRY** | Is `NEXT_PUBLIC_BACKEND_URL` right? Did you redeploy Vercel after setting it? Does `<railway-url>/health` load? |
| Works locally but not on Vercel | `ALLOWED_ORIGINS` on Railway must exactly match your Vercel URL (`https://`, no trailing slash). Railway logs show `rejected websocket from origin …` when it doesn't. |
| One chain's dot is red | That public node is rate-limiting or down. It retries on its own with backoff. Hover the dot to see the error, or set `<CHAIN>_WS_URL` to another free RPC. |
| `CERTIFICATE_VERIFY_FAILED` locally on macOS | Already handled (the backend uses `certifi`). If you still see it, run `pip install -r requirements.txt` again. |
| Feed is empty after a restart | The buffer is in memory, so it starts empty after each deploy. Tokens appear as they launch. Solana and BNB usually show something within seconds. Polygon, Optimism and Avalanche can be quiet for minutes. |

## Known limitations

- **Run only one backend at a time per IP address.** pumpdev.io allows a single connection per IP,
  and PumpPortal also throttles. A second copy (e.g. one on your laptop while Railway is running
  from the same network) gets refused and can disturb the first. Railway and your home network
  are different IPs, so that combination is fine.

- **Established tokens can appear once.** On EVM chains a "new pool" is the signal. The first time
  the backend sees an old token used in a new pool (for example a new coin paired against
  `XAUt`), that old token can show up once. Common quote tokens (WETH, USDC, ZORA, VIRTUAL…) are
  filtered out. Add more in `QUOTE_SYMBOLS` in `backend/app/listeners/evm.py`.
- History is in memory only: it resets on redeploy, and multiple replicas would each have their own feed.
- Free public nodes can rate-limit. With an `ALCHEMY_API_KEY` or your own RPC URLs it's more reliable.
- Solana coverage is Pump.fun launches (and anything else PumpPortal tags). Raydium/Meteora launches
  aren't included because that would need a paid Solana RPC.
