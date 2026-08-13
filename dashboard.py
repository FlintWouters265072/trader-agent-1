"""Generates a self-contained dashboard.html summarizing decisions.jsonl
(and, if valid Alpaca API keys are available, a live account/positions snapshot).

Usage: python dashboard.py
Then open dashboard.html in a browser (no server needed).
"""
from __future__ import annotations

import html
import json
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

DECISIONS_PATH = "decisions.jsonl"
EQUITY_PATH = "equity_history.jsonl"
OUTPUT_PATH = "dashboard.html"

STATUS_GOOD = "#00ff88"
STATUS_CRITICAL = "#ff2d55"
STATUS_MUTED = "#5b8a9a"

ACTION_COLOR = {"buy": STATUS_GOOD, "sell": STATUS_CRITICAL, "hold": STATUS_MUTED}

AMSTERDAM_TZ = ZoneInfo("Europe/Amsterdam")


def format_amsterdam_time(timestamp: str) -> str:
    """Parses a stored ISO UTC timestamp into Amsterdam local time, e.g. '13-8-2026 18:03'."""
    if not timestamp:
        return ""
    try:
        dt = datetime.fromisoformat(timestamp)
    except ValueError:
        return timestamp
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(AMSTERDAM_TZ)
    return f"{local.day}-{local.month}-{local.year} {local.strftime('%H:%M')}"


def load_decisions() -> list[dict]:
    if not os.path.exists(DECISIONS_PATH):
        return []
    entries = []
    with open(DECISIONS_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    entries.sort(key=lambda e: e.get("timestamp", ""))
    return entries


def fetch_live_snapshot() -> dict | None:
    key_id = os.environ.get("ALPACA_API_KEY_ID", "").strip()
    secret_key = os.environ.get("ALPACA_API_SECRET_KEY", "").strip()
    if not key_id or not secret_key:
        return None
    base_url = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets").rstrip("/")
    data_url = os.environ.get("ALPACA_DATA_URL", "https://data.alpaca.markets").rstrip("/")
    try:
        from alpaca_client import AlpacaClient

        client = AlpacaClient(base_url, data_url, key_id, secret_key)
        account = client.get_account()
        positions = client.get_positions()
        try:
            orders = client.get_orders(status="open")
        except Exception:
            orders = []
        return {"account": account, "positions": positions, "orders": orders}
    except Exception:
        return None


def record_equity_snapshot(snapshot: dict | None) -> None:
    if not snapshot or not snapshot.get("account"):
        return
    account = snapshot["account"]
    positions = snapshot.get("positions") or []
    unrealized_pl = sum(float(p.get("unrealized_pl", 0) or 0) for p in positions)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_value": float(account.get("portfolio_value", 0) or 0),
        "unrealized_pl": unrealized_pl,
        "cash_balance": float(account.get("cash", 0) or 0),
        "currency": account.get("currency", "USD"),
    }
    with open(EQUITY_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


def load_equity_history() -> list[dict]:
    if not os.path.exists(EQUITY_PATH):
        return []
    entries = []
    with open(EQUITY_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    entries.sort(key=lambda e: e.get("timestamp", ""))
    return entries


def compute_stats(decisions: list[dict]) -> dict:
    total = len(decisions)
    buy = sum(1 for d in decisions if d.get("decision", {}).get("action") == "buy")
    sell = sum(1 for d in decisions if d.get("decision", {}).get("action") == "sell")
    hold = sum(1 for d in decisions if d.get("decision", {}).get("action") == "hold")
    executed = sum(1 for d in decisions if d.get("executed"))
    dry_run = total - executed
    return {
        "total": total,
        "buy": buy,
        "sell": sell,
        "hold": hold,
        "executed": executed,
        "dry_run": dry_run,
    }


def stat_tile(label: str, value, dot_color: str | None = None) -> str:
    dot = f'<span class="dot" style="background:{dot_color}"></span>' if dot_color else ""
    return f"""
    <div class="tile">
      <div class="tile-label">{dot}{html.escape(label)}</div>
      <div class="tile-value">{html.escape(str(value))}</div>
    </div>"""


def render_timeline(decisions: list[dict]) -> str:
    if not decisions:
        return '<div class="empty">No decisions logged yet — run <code>python run.py</code> to generate the first one.</div>'

    times = []
    for d in decisions:
        ts = d.get("timestamp")
        try:
            times.append(datetime.fromisoformat(ts.replace("Z", "+00:00")))
        except (ValueError, AttributeError):
            times.append(None)

    valid = [t for t in times if t is not None]
    if not valid:
        return '<div class="empty">No valid timestamps to plot.</div>'

    t_min, t_max = min(valid), max(valid)
    span = (t_max - t_min).total_seconds() or 1

    width, height, pad = 900, 140, 40
    plot_w = width - 2 * pad

    dots = []
    for d, t in zip(decisions, times):
        if t is None:
            continue
        frac = (t - t_min).total_seconds() / span if span else 0.5
        x = pad + frac * plot_w
        action = d.get("decision", {}).get("action", "hold")
        color = ACTION_COLOR.get(action, STATUS_MUTED)
        symbol = html.escape(d.get("decision", {}).get("symbol", ""))
        qty = d.get("decision", {}).get("quantity", 0)
        executed = "executed" if d.get("executed") else "dry-run"
        tooltip = html.escape(f"{t.strftime('%Y-%m-%d %H:%M UTC')} · {action.upper()} {symbol} x{qty} ({executed})")
        dots.append(
            f'<circle cx="{x:.1f}" cy="{height / 2:.1f}" r="6" fill="{color}" '
            f'stroke="var(--surface-1)" stroke-width="2" class="dot-mark" '
            f'data-tooltip="{tooltip}"><title>{tooltip}</title></circle>'
        )

    axis_label_start = html.escape(t_min.strftime("%Y-%m-%d"))
    axis_label_end = html.escape(t_max.strftime("%Y-%m-%d"))

    return f"""
    <svg viewBox="0 0 {width} {height}" class="timeline-svg" role="img" aria-label="Decision timeline">
      <line x1="{pad}" y1="{height / 2}" x2="{width - pad}" y2="{height / 2}" class="baseline" />
      {"".join(dots)}
      <text x="{pad}" y="{height - 10}" class="axis-label">{axis_label_start}</text>
      <text x="{width - pad}" y="{height - 10}" class="axis-label" text-anchor="end">{axis_label_end}</text>
    </svg>"""


def format_signed(value, currency: str = "") -> str:
    sign = "+" if value >= 0 else ""
    text = f"{sign}{value:,.2f}"
    return f"{text} {currency}".strip()


def render_pl_chart(history: list[dict]) -> str:
    if not history:
        return (
            '<div class="empty">No equity snapshots yet — each time you run '
            '<code>dashboard.py</code> with valid Alpaca API keys, a snapshot is recorded here. '
            "Run it a few more times (e.g. after each <code>run.py</code> cycle) to build a trend.</div>"
        )

    paired = []
    for h in history:
        pl = h.get("unrealized_pl")
        ts = h.get("timestamp")
        if pl is None or not ts:
            continue
        try:
            t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            continue
        paired.append((t, pl))

    if len(paired) < 2:
        if paired:
            t, pl = paired[0]
            currency = history[-1].get("currency", "")
            return (
                f'<div class="empty">Only one snapshot so far: {format_signed(pl, currency)}. '
                "Run <code>python dashboard.py</code> again later (after more trading cycles) "
                "to start building a P&amp;L trend line.</div>"
            )
        return '<div class="empty">No valid equity snapshots to plot yet.</div>'

    t_min = min(t for t, _ in paired)
    t_max = max(t for t, _ in paired)
    span = (t_max - t_min).total_seconds() or 1

    pl_values = [pl for _, pl in paired]
    pl_min, pl_max = min(0, *pl_values), max(0, *pl_values)
    pl_range = (pl_max - pl_min) or 1
    pl_min -= pl_range * 0.15
    pl_max += pl_range * 0.15
    pl_range = pl_max - pl_min

    width, height, pad = 900, 180, 44
    plot_w = width - 2 * pad
    plot_h = height - 2 * pad

    def x_for(t):
        frac = (t - t_min).total_seconds() / span
        return pad + frac * plot_w

    def y_for(pl):
        frac = (pl - pl_min) / pl_range
        return pad + plot_h - frac * plot_h

    zero_y = y_for(0)
    latest_pl = paired[-1][1]
    latest_currency = history[-1].get("currency", "")
    line_color = STATUS_GOOD if latest_pl >= 0 else STATUS_CRITICAL

    points = [(x_for(t), y_for(pl)) for t, pl in paired]
    polyline_points = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)

    dots = []
    for (t, pl), (x, y) in zip(paired, points):
        tooltip = html.escape(f"{t.strftime('%Y-%m-%d %H:%M UTC')} · {format_signed(pl, latest_currency)}")
        dots.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{line_color}" '
            f'stroke="var(--surface-1)" stroke-width="2" class="dot-mark" '
            f'data-tooltip="{tooltip}"><title>{tooltip}</title></circle>'
        )

    end_x, end_y = points[-1]
    end_label = html.escape(format_signed(latest_pl, latest_currency))
    axis_label_start = html.escape(t_min.strftime("%Y-%m-%d %H:%M"))
    axis_label_end = html.escape(t_max.strftime("%Y-%m-%d %H:%M"))

    return f"""
    <svg viewBox="0 0 {width} {height}" class="timeline-svg" role="img" aria-label="Unrealized profit and loss over time">
      <line x1="{pad}" y1="{zero_y:.1f}" x2="{width - pad}" y2="{zero_y:.1f}" class="baseline" />
      <defs>
        <linearGradient id="chartGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="{line_color}" stop-opacity="0.3"/>
          <stop offset="100%" stop-color="{line_color}" stop-opacity="0.0"/>
        </linearGradient>
      </defs>
      <polygon points="{polyline_points} {end_x:.1f},{zero_y:.1f} {pad:.1f},{zero_y:.1f}" fill="url(#chartGrad)" />
      <polyline points="{polyline_points}" fill="none" stroke="{line_color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />
      {"".join(dots)}
      <text x="{end_x:.1f}" y="{end_y - 12:.1f}" class="axis-label pl-end-label" text-anchor="end">{end_label}</text>
      <text x="{pad}" y="{height - 10}" class="axis-label">{axis_label_start}</text>
      <text x="{width - pad}" y="{height - 10}" class="axis-label" text-anchor="end">{axis_label_end}</text>
    </svg>"""


def render_profit_tracker(snapshot: dict | None, history: list[dict]) -> str:
    if not snapshot or not snapshot.get("account"):
        return (
            '<div class="empty">Live account data unavailable (missing/invalid ALPACA_API_KEY_ID '
            "or ALPACA_API_SECRET_KEY, or the account request failed) — profit tracking needs a "
            "working Alpaca connection.</div>"
        )

    account = snapshot["account"]
    positions = snapshot.get("positions") or []
    currency = account.get("currency", "USD")
    unrealized = sum(float(p.get("unrealized_pl", 0) or 0) for p in positions)
    total_value = float(account.get("portfolio_value", 0) or 0)
    cash_balance = float(account.get("cash", 0) or 0)

    pl_color = STATUS_GOOD if unrealized >= 0 else STATUS_CRITICAL
    
    # Generate SVG Gauge
    # 270 degree arc for the gauge
    gauge = f"""
    <div class="gauge-container">
      <svg class="gauge-svg" viewBox="0 0 200 200">
        <path class="gauge-arc-bg" d="M 40 160 A 85 85 0 1 1 160 160" />
        <path class="gauge-arc-fg" d="M 40 160 A 85 85 0 1 1 160 160" />
        <g class="gauge-ticks">
          {"".join(f'<line x1="100" y1="15" x2="100" y2="25" stroke="var(--cyan-dim)" stroke-width="2" transform="rotate({i*15} 100 100)" />' for i in range(24))}
        </g>
        <text x="100" y="105" class="gauge-text-value">${total_value:,.0f}</text>
        <text x="100" y="125" class="gauge-text-label">{currency} BALANCE</text>
      </svg>
      <div class="pl-val" style="color: {pl_color}">P&amp;L: {format_signed(unrealized, currency)}</div>
      <div style="font-size: 12px; color: var(--text-secondary); margin-top: 5px;">CASH: {cash_balance:,.2f} {currency}</div>
    </div>
    """

    return f'<div class="profit-grid"><div>{gauge}</div><div>{render_pl_chart(history)}</div></div>'



def render_table(decisions: list[dict]) -> str:
    if not decisions:
        return ""
    rows = []
    for d in reversed(decisions):
        dec = d.get("decision", {})
        action = dec.get("action", "")
        color = ACTION_COLOR.get(action, STATUS_MUTED)
        executed_badge = (
            '<span class="badge badge-executed">executed</span>'
            if d.get("executed")
            else '<span class="badge badge-dry">dry-run</span>'
        )
        qty_display = str(dec.get("quantity", ""))
        requested = d.get("model_requested_quantity")
        if requested is not None:
            qty_display += f" (model asked for {requested})"
        rows.append(f"""
        <tr>
          <td class="mono">{html.escape(format_amsterdam_time(d.get("timestamp", "")))}</td>
          <td><span class="dot" style="background:{color}"></span>{html.escape(action.upper())}</td>
          <td>{html.escape(dec.get("symbol", ""))}</td>
          <td class="mono">{html.escape(qty_display)}</td>
          <td>{executed_badge}</td>
          <td class="rationale">{html.escape(dec.get("rationale", ""))}</td>
        </tr>""")
    return f"""
    <table class="log-table">
      <thead>
        <tr><th>Time (Amsterdam)</th><th>Action</th><th>Symbol</th><th>Qty</th><th>Status</th><th>Rationale</th></tr>
      </thead>
      <tbody>{"".join(rows)}</tbody>
    </table>"""


def render_positions(snapshot: dict | None) -> str:
    if not snapshot:
        return '<div class="empty">Live account data unavailable (missing/invalid Alpaca API keys, or request failed) — showing decision log only.</div>'

    account = snapshot.get("account", {})
    positions_data = snapshot.get("positions") or []

    tiles = (
        stat_tile("Account currency", account.get("currency", "—"))
        + stat_tile("Account ID", account.get("account_number", "—"))
        + stat_tile("Open positions", len(positions_data))
    )

    if not positions_data:
        pos_table = '<div class="empty">No open positions.</div>'
    else:
        rows = []
        for p in positions_data:
            pl = p.get("unrealized_pl")
            pl = float(pl) if pl is not None else None
            pl_cell = (
                f'<span style="color:{STATUS_GOOD if pl >= 0 else STATUS_CRITICAL}">{format_signed(pl)}</span>'
                if pl is not None
                else "—"
            )
            rows.append(f"""
            <tr>
              <td>{html.escape(str(p.get("symbol", "")))}</td>
              <td>{html.escape(str(p.get("side", "")))}</td>
              <td class="mono">{html.escape(str(p.get("qty", "")))}</td>
              <td class="mono">{html.escape(str(p.get("avg_entry_price", "")))}</td>
              <td class="mono">{html.escape(str(p.get("current_price", "—")))}</td>
              <td class="mono">{pl_cell}</td>
            </tr>""")
        pos_table = f"""
        <table class="log-table">
          <thead><tr><th>Symbol</th><th>Side</th><th>Qty</th><th>Open price</th><th>Current price</th><th>P&amp;L</th></tr></thead>
          <tbody>{"".join(rows)}</tbody>
        </table>"""

    return f'<div class="tiles">{tiles}</div>{pos_table}'


def render_open_orders(snapshot: dict | None) -> str:
    if not snapshot:
        return '<div class="empty">Live account data unavailable — can\'t show open orders.</div>'

    orders = snapshot.get("orders") or []
    if not orders:
        return '<div class="empty">No open orders.</div>'

    rows = []
    for o in orders:
        status = o.get("status", "")
        rows.append(f"""
        <tr>
          <td class="mono">{html.escape(str(o.get("submitted_at", "")))}</td>
          <td>{html.escape(str(o.get("symbol", "")))}</td>
          <td>{html.escape(str(o.get("side", "")).upper())}</td>
          <td class="mono">{html.escape(str(o.get("qty", "")))}</td>
          <td class="mono">{html.escape(str(o.get("filled_qty", "0")))}</td>
          <td><span class="badge badge-dry">{html.escape(status)}</span></td>
        </tr>""")
    note = (
        '<div class="empty">Orders sitting here (not yet filled) don\'t count toward the exposure '
        "caps in <code>risk.py</code>, which only look at settled positions — if several stack up "
        "while the market is closed, they can all fill at once.</div>"
    )
    return f"""
    <table class="log-table">
      <thead><tr><th>Submitted (UTC)</th><th>Symbol</th><th>Side</th><th>Qty</th><th>Filled</th><th>Status</th></tr></thead>
      <tbody>{"".join(rows)}</tbody>
    </table>{note}"""


def build_content(decisions: list[dict], stats: dict, snapshot: dict | None, equity_history: list[dict]) -> str:
    kpi_tiles = "".join([
        stat_tile("Total decisions", stats["total"]),
        stat_tile("Buy", stats["buy"], STATUS_GOOD),
        stat_tile("Sell", stats["sell"], STATUS_CRITICAL),
        stat_tile("Hold", stats["hold"], STATUS_MUTED),
        stat_tile("Executed", stats["executed"]),
        stat_tile("Dry-run", stats["dry_run"]),
    ])

    return f"""
    <div class="card">
      <h2>Summary</h2>
      <div class="tiles">{kpi_tiles}</div>
    </div>

    <div class="card">
      <h2>Profit tracker</h2>
      {render_profit_tracker(snapshot, equity_history)}
    </div>

    <div class="card">
      <h2>Decision timeline</h2>
      {render_timeline(decisions)}
      <div class="legend">
        <span><span class="dot" style="background:{STATUS_GOOD}"></span>Buy</span>
        <span><span class="dot" style="background:{STATUS_CRITICAL}"></span>Sell</span>
        <span><span class="dot" style="background:{STATUS_MUTED}"></span>Hold</span>
      </div>
    </div>

    <div class="card">
      <h2>Live account snapshot</h2>
      {render_positions(snapshot)}
    </div>

    <div class="card">
      <h2>Open orders</h2>
      {render_open_orders(snapshot)}
    </div>

    <div class="card">
      <h2>Decision log</h2>
      {render_table(decisions) or '<div class="empty">No decisions logged yet.</div>'}
    </div>"""


STYLE = """
  @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700;900&family=Share+Tech+Mono&display=swap');

  :root {
    --void: #0a0e1a;
    --panel: rgba(13, 21, 37, 0.75);
    --panel-solid: #0d1525;
    --cyan: #00d4ff;
    --cyan-dim: rgba(0, 212, 255, 0.25);
    --cyan-glow: rgba(0, 212, 255, 0.6);
    --green: #00ff88;
    --red: #ff2d55;
    --muted: #5b8a9a;
    --text-primary: #e8f4ff;
    --text-secondary: #7db4cc;
    --text-muted: #3d6478;
    --border: rgba(0, 212, 255, 0.2);
    --gridline: rgba(0, 212, 255, 0.08);
  }
  
  * { box-sizing: border-box; }
  html, body { background: var(--void); min-height: 100vh; }
  body {
    margin: 0;
    position: relative;
    overflow-x: hidden;
    font-family: 'Share Tech Mono', monospace;
    color: var(--text-primary);
    background: radial-gradient(circle at 50% 50%, #0d1525 0%, #0a0e1a 100%);
  }

  /* Hexagonal grid background */
  body::before {
    content: "";
    position: fixed;
    inset: 0;
    z-index: 0;
    pointer-events: none;
    opacity: 0.15;
    background-image: url("data:image/svg+xml,%3Csvg width='40' height='69.282' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M40 17.32l-20 11.547L0 17.32V0h40v17.32zm0 34.641l-20 11.547-20-11.547V34.641h40v17.32z' fill='none' stroke='%2300d4ff' stroke-width='1' opacity='0.5'/%3E%3C/svg%3E");
    background-size: 40px 69.28px;
    mask-image: radial-gradient(ellipse at center, black 10%, transparent 80%);
    -webkit-mask-image: radial-gradient(ellipse at center, black 10%, transparent 80%);
  }
  
  /* Scan lines */
  body::after {
    content: "";
    position: fixed;
    inset: 0;
    z-index: 0;
    pointer-events: none;
    background: linear-gradient(to bottom, rgba(255,255,255,0), rgba(255,255,255,0) 50%, rgba(0,0,0,0.2) 50%, rgba(0,0,0,0.2));
    background-size: 100% 4px;
    opacity: 0.3;
  }

  #particles {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    z-index: 0;
    pointer-events: none;
  }

  .viz-root { position: relative; z-index: 1; }
  .wrap { max-width: 1200px; margin: 0 auto; padding: 40px 24px 80px; }

  header {
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    margin-bottom: 40px;
    padding-bottom: 20px;
    border-bottom: 2px solid var(--border);
    position: relative;
  }
  header::after {
    content: "";
    position: absolute;
    bottom: -2px;
    left: 0;
    width: 150px;
    height: 2px;
    background: var(--cyan);
    box-shadow: 0 0 10px var(--cyan);
  }

  .hdr-title h1 {
    margin: 0;
    font-family: 'Orbitron', sans-serif;
    font-weight: 900;
    font-size: 32px;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    color: var(--text-primary);
    text-shadow: 0 0 15px var(--cyan-glow), 0 0 30px var(--cyan-dim);
  }
  .hdr-sub {
    font-size: 14px;
    letter-spacing: 0.3em;
    text-transform: uppercase;
    color: var(--cyan);
    margin-top: 8px;
    text-shadow: 0 0 5px var(--cyan-dim);
  }
  
  .hdr-status { text-align: right; }
  .meta { color: var(--text-secondary); font-size: 12px; }
  .clock {
    font-family: 'Orbitron', sans-serif;
    font-size: 18px;
    color: var(--cyan);
    text-shadow: 0 0 10px var(--cyan-glow);
    margin-top: 8px;
    letter-spacing: 0.1em;
  }

  .live-dot {
    position: relative; display: inline-block; width: 10px; height: 10px; border-radius: 50%;
    background: var(--green); margin-right: 10px; box-shadow: 0 0 8px var(--green);
  }
  .live-dot::after {
    content: ""; position: absolute; inset: -5px; border-radius: 50%; border: 1px solid var(--green);
    opacity: 0; animation: radarping 2s ease-out infinite;
  }
  .live-dot.stale { background: var(--red); box-shadow: 0 0 8px var(--red); }
  .live-dot.stale::after { border-color: var(--red); }
  @keyframes radarping { 0% { transform: scale(0.5); opacity: 1; } 100% { transform: scale(2.5); opacity: 0; } }

  .card {
    position: relative;
    padding: 24px 30px;
    margin-bottom: 30px;
    background: var(--panel);
    border: 1px solid var(--border);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    box-shadow: inset 0 0 20px rgba(0, 212, 255, 0.05), 0 10px 30px rgba(0,0,0,0.5);
  }
  /* Dramatic Corner Brackets */
  .card::before, .card::after {
    content: ""; position: absolute; width: 20px; height: 20px; border: 2px solid var(--cyan);
    pointer-events: none; transition: 0.3s;
  }
  .card::before { top: -2px; left: -2px; border-right: none; border-bottom: none; box-shadow: -2px -2px 10px var(--cyan-dim); }
  .card::after { bottom: -2px; right: -2px; border-left: none; border-top: none; box-shadow: 2px 2px 10px var(--cyan-dim); }
  .card:hover::before { width: 30px; height: 30px; box-shadow: -2px -2px 15px var(--cyan-glow); }
  .card:hover::after { width: 30px; height: 30px; box-shadow: 2px 2px 15px var(--cyan-glow); }
  
  .card h2 {
    font-family: 'Orbitron', sans-serif;
    font-size: 16px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.2em;
    color: var(--cyan);
    margin: 0 0 24px;
    display: flex;
    align-items: center;
    gap: 15px;
    text-shadow: 0 0 8px var(--cyan-glow);
  }
  .card h2::after {
    content: ""; flex: 1; height: 1px;
    background: linear-gradient(90deg, var(--cyan-glow), transparent);
  }

  .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 16px; }
  .tile {
    background: var(--panel-solid);
    border: 1px solid var(--border);
    padding: 16px;
    position: relative;
    transition: 0.2s;
  }
  .tile:hover {
    border-color: var(--cyan);
    box-shadow: 0 0 15px var(--cyan-dim);
    transform: translateY(-2px);
  }
  .tile::before {
    content: ""; position: absolute; top: 0; left: 0; width: 100%; height: 2px;
    background: var(--cyan); box-shadow: 0 0 8px var(--cyan);
  }
  .tile-label {
    font-size: 11px; text-transform: uppercase; letter-spacing: 0.15em;
    color: var(--text-secondary); display: flex; align-items: center; gap: 8px; margin-bottom: 12px;
  }
  .tile-value {
    font-family: 'Orbitron', sans-serif; font-size: 28px; font-weight: 700; color: var(--text-primary);
    text-shadow: 0 0 15px rgba(255,255,255,0.2);
  }
  .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; box-shadow: 0 0 8px currentColor; }

  /* SVG & Timeline overrides */
  .timeline-svg { width: 100%; height: auto; overflow: visible; }
  .baseline { stroke: var(--border); stroke-width: 1; stroke-dasharray: 4 6; }
  .axis-label { fill: var(--text-secondary); font-size: 11px; letter-spacing: 0.05em; }
  .pl-end-label { fill: var(--cyan); font-size: 14px; font-weight: bold; font-family: 'Orbitron', sans-serif; text-shadow: 0 0 5px var(--cyan-glow); }
  .dot-mark { cursor: pointer; transition: 0.2s; }
  .dot-mark:hover { r: 8; filter: drop-shadow(0 0 8px currentColor); stroke: var(--cyan); }
  
  .legend { display: flex; gap: 24px; font-size: 12px; color: var(--text-secondary); margin-top: 16px; text-transform: uppercase; letter-spacing: 0.1em; }
  .legend span { display: inline-flex; align-items: center; gap: 8px; }

  /* Tables */
  table.log-table { width: 100%; border-collapse: collapse; font-size: 13px; }
  .log-table th {
    text-align: left; color: var(--cyan); font-weight: normal; font-size: 11px;
    text-transform: uppercase; letter-spacing: 0.1em; padding: 12px 16px;
    border-bottom: 1px solid var(--cyan-glow);
    background: rgba(0, 212, 255, 0.05);
  }
  .log-table td { padding: 12px 16px; border-bottom: 1px solid var(--gridline); vertical-align: middle; transition: 0.15s; }
  .log-table tr:hover td { background: rgba(0, 212, 255, 0.1); text-shadow: 0 0 5px rgba(255,255,255,0.3); }
  .mono { font-variant-numeric: tabular-nums; }
  .rationale { color: var(--text-secondary); max-width: 400px; line-height: 1.4; }
  
  .badge {
    font-size: 10px; padding: 4px 10px; border-radius: 2px;
    text-transform: uppercase; letter-spacing: 0.1em; border: 1px solid currentColor;
  }
  .badge-executed { background: rgba(0, 255, 136, 0.1); color: var(--green); box-shadow: inset 0 0 5px rgba(0,255,136,0.3); }
  .badge-dry { background: rgba(91, 138, 154, 0.1); color: var(--muted); box-shadow: inset 0 0 5px rgba(91,138,154,0.3); }
  
  .empty { color: var(--text-muted); font-size: 14px; padding: 20px 0; text-align: center; border: 1px dashed var(--border); margin: 10px 0; }

  /* Form & Risk Settings */
  .risk-form { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 20px; margin-bottom: 20px; }
  .risk-field { display: flex; flex-direction: column; gap: 8px; }
  .risk-field-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: var(--cyan); display: flex; align-items: center; gap: 10px; }
  .risk-hint { font-size: 10px; color: var(--text-muted); }
  .risk-form input[type="number"], .risk-form select {
    background: rgba(0,0,0,0.5); border: 1px solid var(--border); border-radius: 0;
    color: var(--text-primary); font-family: 'Share Tech Mono', monospace; font-size: 14px;
    padding: 10px 12px; outline: none; transition: 0.2s;
  }
  .risk-form input[type="number"]:focus, .risk-form select:focus { border-color: var(--cyan); box-shadow: 0 0 10px var(--cyan-dim); background: rgba(0,212,255,0.05); }
  .risk-actions { display: flex; gap: 16px; flex-wrap: wrap; margin-top: 10px; }
  .risk-error { color: var(--red); font-size: 13px; margin-bottom: 16px; padding: 12px; border: 1px solid var(--red); background: rgba(255,45,85,0.1); text-shadow: 0 0 5px var(--red); }
  
  button {
    background: transparent; border: 1px solid var(--cyan); color: var(--cyan);
    font-family: 'Orbitron', sans-serif; font-size: 12px; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.15em; padding: 10px 24px; cursor: pointer;
    transition: 0.2s; position: relative; overflow: hidden;
  }
  button:hover {
    background: var(--cyan); color: var(--void);
    box-shadow: 0 0 15px var(--cyan-glow);
  }

  /* SVG Gauges & Centerpiece */
  .gauge-container {
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    position: relative; margin: 30px 0; padding: 20px;
  }
  .gauge-svg { width: 300px; height: 300px; filter: drop-shadow(0 0 10px var(--cyan-dim)); }
  .gauge-arc-bg { fill: none; stroke: var(--border); stroke-width: 10; stroke-linecap: round; }
  .gauge-arc-fg { fill: none; stroke: var(--cyan); stroke-width: 10; stroke-linecap: round; stroke-dasharray: 600; stroke-dashoffset: 0; animation: dash 2s ease-out forwards; }
  @keyframes dash { from { stroke-dashoffset: 600; } to { stroke-dashoffset: 150; } }
  .gauge-ticks { transform-origin: center; animation: spin 60s linear infinite; }
  @keyframes spin { 100% { transform: rotate(360deg); } }
  .gauge-text-value { fill: var(--text-primary); font-family: 'Orbitron', sans-serif; font-size: 32px; font-weight: 700; text-anchor: middle; filter: drop-shadow(0 0 5px rgba(255,255,255,0.3)); }
  .gauge-text-label { fill: var(--text-secondary); font-family: 'Share Tech Mono', monospace; font-size: 12px; letter-spacing: 0.2em; text-transform: uppercase; text-anchor: middle; }
  .pl-val { font-family: 'Share Tech Mono', monospace; font-size: 16px; font-weight: bold; margin-top: 15px; }
  
  .profit-grid { display: grid; grid-template-columns: 1fr 2fr; gap: 30px; align-items: center; }
  @media (max-width: 800px) { .profit-grid { grid-template-columns: 1fr; } }
"""

CLOCK_SCRIPT = """
function tickClock() {
  const el = document.getElementById('clock');
  if (!el) return;
  const now = new Date();
  const hh = String(now.getUTCHours()).padStart(2, '0');
  const mm = String(now.getUTCMinutes()).padStart(2, '0');
  const ss = String(now.getUTCSeconds()).padStart(2, '0');
  el.textContent = hh + ':' + mm + ':' + ss + ' UTC';
}
tickClock();
setInterval(tickClock, 1000);

// Particle system
const canvas = document.createElement('canvas');
canvas.id = 'particles';
document.body.insertBefore(canvas, document.body.firstChild);
const ctx = canvas.getContext('2d');
let w, h, particles;

function initParticles() {
  w = canvas.width = window.innerWidth;
  h = canvas.height = window.innerHeight;
  particles = [];
  for(let i=0; i<60; i++) {
    particles.push({
      x: Math.random()*w, y: Math.random()*h,
      vx: (Math.random()-0.5)*0.5, vy: (Math.random()-0.5)*0.5,
      r: Math.random()*1.5 + 0.5
    });
  }
}
initParticles();
window.addEventListener('resize', initParticles);

function drawParticles() {
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = 'rgba(0, 212, 255, 0.4)';
  ctx.strokeStyle = 'rgba(0, 212, 255, 0.1)';
  
  for(let i=0; i<particles.length; i++) {
    let p = particles[i];
    p.x += p.vx; p.y += p.vy;
    if(p.x < 0 || p.x > w) p.vx *= -1;
    if(p.y < 0 || p.y > h) p.vy *= -1;
    
    ctx.beginPath();
    ctx.arc(p.x, p.y, p.r, 0, Math.PI*2);
    ctx.fill();
    
    for(let j=i+1; j<particles.length; j++) {
      let p2 = particles[j];
      let dist = Math.hypot(p.x-p2.x, p.y-p2.y);
      if(dist < 100) {
        ctx.beginPath();
        ctx.moveTo(p.x, p.y);
        ctx.lineTo(p2.x, p2.y);
        ctx.stroke();
      }
    }
  }
  requestAnimationFrame(drawParticles);
}
drawParticles();
"""


def build_html(decisions: list[dict], stats: dict, snapshot: dict | None, equity_history: list[dict]) -> str:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    content = build_content(decisions, stats, snapshot, equity_history)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="900">
<title>Trader Agent — HUD</title>
<style>{STYLE}</style>
</head>
<body>
<div class="viz-root">
  <div class="wrap">
    <header>
      <div class="hdr-title">
        <h1>Trader Agent</h1>
        <div class="hdr-sub">Autonomous Market Interface</div>
      </div>
      <div class="hdr-status">
        <div class="meta">Generated {generated_at} · auto-refreshes every 15 min, in sync with the trading cycle</div>
        <div class="clock" id="clock"></div>
      </div>
    </header>
    {content}
  </div>
</div>
<script>{CLOCK_SCRIPT}</script>
</body>
</html>"""


def main():
    decisions = load_decisions()
    stats = compute_stats(decisions)
    snapshot = fetch_live_snapshot()
    record_equity_snapshot(snapshot)
    equity_history = load_equity_history()
    html_out = build_html(decisions, stats, snapshot, equity_history)
    with open(OUTPUT_PATH, "w") as f:
        f.write(html_out)
    print(f"Wrote {OUTPUT_PATH} ({stats['total']} decisions logged, {len(equity_history)} equity snapshots).")


if __name__ == "__main__":
    main()
