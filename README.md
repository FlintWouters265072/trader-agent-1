# Alpaca Paper Trading Agent

An LLM-assisted trading agent for Alpaca's **paper trading** environment.
Each run: fetches your paper account/positions/quotes, asks Claude for a single buy/sell/hold
decision, applies basic risk limits, and (only if you opt in) places the order.

**This is not investment advice, and it only talks to Alpaca's paper environment — no real
money is ever involved unless you rewire it to point at the live trading API, which this project
deliberately does not do.**

## 1. Set up Alpaca paper access

1. Create an account at https://alpaca.markets/ (paper trading is available immediately, no
   funding or approval needed).
2. From the dashboard, switch to **Paper Trading** and open the **API Keys** panel to generate
   an `API Key ID` / `Secret Key` pair.
3. Unlike Saxo's 24-hour SIM tokens, this key pair does **not expire** — no daily re-auth needed.
4. Confirm the paper API base URL is still `https://paper-api.alpaca.markets` and the market
   data URL is `https://data.alpaca.markets` (check Alpaca's docs — these are the current
   defaults baked into `.env.example`).

## 2. Set up Anthropic access

Get an API key from https://console.anthropic.com/settings/keys.

## 3. Configure

```bash
cd /Users/flintwouters/project/trader-agent
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env: paste ALPACA_API_KEY_ID, ALPACA_API_SECRET_KEY, ANTHROPIC_API_KEY
```

**No fixed watchlist.** The agent can buy any tradable US-listed stock/ETF ticker (e.g. `AAPL`) or
any Alpaca USD crypto pair (e.g. `BTC/USD`), and can sell/reduce anything it currently holds — it's
not limited to a preset list. Orders are placed directly by ticker symbol (no instrument/Uic lookup
step, unlike Saxo). Every symbol the model picks is validated against Alpaca's asset list before
anything is sized or placed — an unrecognized or untradable symbol is simply logged as a rejected
cycle, not an error.

Since it can now pick assets that trade at wildly different prices (a $190 stock vs. a $65,000
Bitcoin), sizing and risk caps are dollar-based instead of share/coin-based: the model proposes a
dollar amount (`amount_usd`) per trade, which gets converted to a quantity from the live price and
clamped by `MAX_ORDER_VALUE_USD` / `MAX_SYMBOL_EXPOSURE_USD` (see `.env.example`).

## 4. Run

```bash
cd /Users/flintwouters/project/trader-agent
python3 run.py           # dry run — logs the decision, does not place an order
python3 run.py --execute   # actually places the order on Alpaca paper trading (or set EXECUTE=true in .env)
```

Every run appends a line to `decisions.jsonl` with the timestamp, the model's decision, and
(if executed) the order result — use this as your audit trail.

## 5. Dashboard

```bash
python dashboard.py
open dashboard.html   # macOS; or just double-click the file
```

Generates a self-contained `dashboard.html` (no server, works offline) summarizing:
- decision counts (buy/sell/hold, executed/dry-run)
- a timeline of every decision
- **a profit tracker** — unrealized P&L, total account value (portfolio value), cash balance, and
  a P&L trend line (built from a snapshot recorded to `equity_history.jsonl` every time you run
  `dashboard.py` — the trend line needs at least 2 runs to appear)
- a live account/positions snapshot (if the Alpaca API keys are still valid), including per-position P&L
- the full decision log with rationale

Regenerate it any time after new runs to see the latest state — running it more often (e.g. after
each `run.py` cycle) builds a denser P&L trend. `dashboard.html` and `equity_history.jsonl` are
both gitignored (they can contain live account data) — only the generator script is committed.

### Live dashboard (auto-updating, no manual regeneration)

```bash
python3 dashboard_server.py
open http://127.0.0.1:8765   # or set DASHBOARD_PORT / DASHBOARD_REFRESH_SECONDS to change defaults
```

Same content as `dashboard.py`'s static page — account value, cash, P&L trend, decision log — plus
an **open orders** panel, served by a small local Flask app instead of a static file. The page
polls the server every 15s (configurable) and swaps in fresh data without a manual reload or rerun.
It talks to Alpaca directly on each poll, so it reflects fills/price moves in near real time, not
just whatever `dashboard.py` last wrote. Runs only on `127.0.0.1` — nothing is exposed beyond your
machine. Leave it running in a terminal (or `tmux`/a background process) while you work; `Ctrl+C`
stops it. Equity snapshots are still throttled to once per 5 minutes even though the page polls
every 15s, so `equity_history.jsonl` doesn't get flooded.

## 6. Automation (runs unattended, auto-executes trades)

`automate.sh` runs one full cycle (`run.py --execute` then `dashboard.py`) and appends output to
`automation.log`. A `com.traderagent.autorun.plist` is provided for macOS's `launchd` scheduler,
set to run every 15 minutes. **This means it will autonomously place real paper orders with no
human review, on a schedule, indefinitely** — that's a meaningfully bigger step than running
`run.py` yourself, so installing it is a deliberate action you take, not something done for you:

```bash
cp com.traderagent.autorun.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.traderagent.autorun.plist
```

Check `automation.log` (and `launchd_stdout.log` / `launchd_stderr.log`) periodically — nothing
alerts you if a cycle fails.

**No daily token refresh needed anymore.** Alpaca's API key pair doesn't expire the way Saxo's
24-hour SIM token did, so once configured this can run unattended indefinitely without a daily
manual step. Still worth checking `automation.log` occasionally — e.g. market data or order
requests can fail for other reasons (rate limits, market closed, key revoked).

To stop it:
```bash
launchctl unload ~/Library/LaunchAgents/com.traderagent.autorun.plist
```

### Dashboard refresh cadence

`dashboard.html` auto-refreshes itself in the browser (`<meta http-equiv="refresh" content="900">`)
every 15 minutes — matching `automate.sh`'s own cycle, since `dashboard.py` runs right after
`run.py --execute` in the same job. There's no separate faster job: the profit tracker updates
exactly when the trading cycle does, nothing in between. If you want to see the very latest state
sooner than that, just run `python3 dashboard.py` yourself, or open `dashboard.html` after checking
`automation.log` shows a fresh cycle.

Note: `equity_history.jsonl` grows by one line every time `dashboard.py` runs, so with this job
installed that's roughly one snapshot per 15 minutes — harmless for a local file, and it builds a
steady P&L trend.

## 7. Docker (for running 24/7 on a remote VPS)

`automate.sh` + launchd (§6) only runs while **this Mac** is on, awake, and you're logged in —
close the lid and it stops. To get genuine 24/7 unattended operation, run the same cycle in
Docker on an always-on VPS instead. This ships two services (`docker-compose.yml`):

- **`trader-agent`** — loops `run.py --execute` then `dashboard.py` every `CYCLE_INTERVAL_SECONDS`
  (default 900s), matching `automate.sh`'s cadence, via `docker-entrypoint.sh`.
- **`dashboard`** — runs `dashboard_server.py` (the live-updating dashboard) on port 8765.

Both bind-mount the whole project directory into the container (`.:/app`), so `decisions.jsonl`,
`equity_history.jsonl`, and `dashboard.html` persist on the VPS's disk across container restarts
— no separate data volume to manage.

```bash
# On the VPS, after copying this directory over (e.g. via scp/rsync — never through a public
# git repo, since .env holds live API keys) and installing Docker:
docker compose up -d --build
docker compose logs -f trader-agent   # watch cycles fire
```

`restart: unless-stopped` means Docker brings the containers back automatically after a crash or
a VPS reboot — no manual restart, no re-registering a scheduler.

The dashboard's Flask server still binds to `127.0.0.1` **inside** the container by default (see
`dashboard_server.py`); Docker sets `DASHBOARD_HOST=0.0.0.0` there so the container can actually
serve traffic, but the compose file maps that to `127.0.0.1:8765` on the **VPS's** side — so it's
still never exposed to the public internet. View it by tunneling:

```bash
ssh -L 8765:localhost:8765 user@your-vps-ip
# then open http://localhost:8765 on your own machine
```

Stop everything with `docker compose down`. **If you migrate to this, unload the local launchd
job first** (`launchctl unload ~/Library/LaunchAgents/com.traderagent.autorun.plist`) — otherwise
your Mac and the VPS will both be placing orders against the same account every 15 minutes.

## First-run checklist

Alpaca's API surface can change between account types and API versions. The first time you run
this, check in order:

1. `get_account()` succeeds (auth is working).
2. A full dry run (`python run.py`) produces a sensible decision on some symbol and logs it —
   check `decisions.jsonl` for the resolved `quantity`/`order_usd`, not just the model's raw ask.
3. Try a symbol the model is unlikely to ever pick (a delisted ticker, a typo) isn't a concern —
   `get_asset()` rejects anything Alpaca doesn't recognize before an order is ever built.
4. Only then try `--execute` and confirm a paper order actually appears in your Alpaca paper
   account (dashboard → Orders).

## Limitations / next steps

- **No live trading path.** Switching to Alpaca's live trading API would require your own review
  of the risk controls in `risk.py` — treat that as a deliberate, separate decision, not a config flip.
- **`run.py`/`dashboard.py` themselves are single-cycle** — `automate.sh` + the launchd job (see
  §6) is what adds scheduling on top; there's no built-in polling loop inside the Python code itself.
- **Risk controls are still basic.** `risk.py` clamps per-order dollar size and caps total open
  exposure per symbol (`MAX_SYMBOL_EXPOSURE_USD`, buy-only — selling to close is never blocked,
  and is separately capped to never exceed what's actually held) — but there's still no daily-loss
  limit and no cap on the number of *distinct* symbols/positions open at once, and the fully open
  symbol universe means a single cycle could just as easily open a new position as manage an
  existing one. Extend before trusting it with anything beyond small paper trades.
- **Market hours.** Alpaca's paper trading follows real US market hours for stocks (crypto trades
  24/7) — stock quotes and orders outside regular trading hours may be stale or rejected. `run.py`
  doesn't currently check market status before deciding.
- **No live-quote grounding for brand-new symbols.** The model picks a new symbol from its own
  knowledge (no quote is fed to it beforehand for anything it doesn't already hold) — a live quote
  is only fetched afterward, to validate tradability and size the order. It won't invent an
  untradable symbol into an actual trade, but its choice of *which* new symbol to open isn't based
  on real-time price/spread the way its management of existing positions is.
