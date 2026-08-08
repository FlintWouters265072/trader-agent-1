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

from dotenv import load_dotenv

load_dotenv()

DECISIONS_PATH = "decisions.jsonl"
EQUITY_PATH = "equity_history.jsonl"
OUTPUT_PATH = "dashboard.html"

STATUS_GOOD = "#33ffb0"
STATUS_CRITICAL = "#ff4d6d"
STATUS_MUTED = "#5b7c92"

ACTION_COLOR = {"buy": STATUS_GOOD, "sell": STATUS_CRITICAL, "hold": STATUS_MUTED}


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
      <polyline points="{polyline_points}" fill="none" stroke="{line_color}" stroke-width="2" \
stroke-linejoin="round" stroke-linecap="round" />
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

    pl_color = None
    if unrealized is not None:
        pl_color = STATUS_GOOD if unrealized >= 0 else STATUS_CRITICAL

    tiles = "".join([
        stat_tile(
            "Unrealized P&L",
            format_signed(unrealized, currency) if unrealized is not None else "—",
            pl_color,
        ),
        stat_tile("Total account value", f"{total_value:,.2f} {currency}" if total_value is not None else "—"),
        stat_tile("Cash balance", f"{cash_balance:,.2f} {currency}" if cash_balance is not None else "—"),
    ])

    return f'<div class="tiles">{tiles}</div>{render_pl_chart(history)}'


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
          <td class="mono">{html.escape(d.get("timestamp", ""))}</td>
          <td><span class="dot" style="background:{color}"></span>{html.escape(action.upper())}</td>
          <td>{html.escape(dec.get("symbol", ""))}</td>
          <td class="mono">{html.escape(qty_display)}</td>
          <td>{executed_badge}</td>
          <td class="rationale">{html.escape(dec.get("rationale", ""))}</td>
        </tr>""")
    return f"""
    <table class="log-table">
      <thead>
        <tr><th>Time (UTC)</th><th>Action</th><th>Symbol</th><th>Qty</th><th>Status</th><th>Rationale</th></tr>
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


STYLE = f"""
  @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700;900&family=Rajdhani:wght@400;500;600;700&family=Share+Tech+Mono&display=swap');

  .viz-root {{
    color-scheme: dark;
    --void:        #04070b;
    --panel:       rgba(9, 20, 30, 0.66);
    --panel-solid: #071019;
    --cyan:        #2dd8ff;
    --cyan-dim:    rgba(45,216,255,0.35);
    --cyan-glow:   rgba(45,216,255,0.55);
    --text-primary:   #eaf7ff;
    --text-secondary: #85b4c9;
    --text-muted:     #4c6c7d;
    --gridline: rgba(45,216,255,0.14);
    --baseline: rgba(45,216,255,0.30);
    --border:   rgba(45,216,255,0.28);
    --good:     {STATUS_GOOD};
    --critical: {STATUS_CRITICAL};
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ background: var(--void); }}
  body {{
    margin: 0;
    position: relative;
    overflow-x: hidden;
    font-family: 'Rajdhani', system-ui, -apple-system, "Segoe UI", sans-serif;
    color: var(--text-primary);
    background:
      radial-gradient(ellipse 900px 500px at 15% -10%, rgba(45,216,255,0.12), transparent 60%),
      radial-gradient(ellipse 700px 500px at 105% 110%, rgba(255,176,32,0.07), transparent 60%),
      var(--void);
  }}
  body::before {{
    content: ""; position: fixed; inset: 0; z-index: 0; pointer-events: none;
    background-image:
      linear-gradient(var(--gridline) 1px, transparent 1px),
      linear-gradient(90deg, var(--gridline) 1px, transparent 1px);
    background-size: 44px 44px;
    opacity: 0.35;
    -webkit-mask-image: radial-gradient(ellipse 1000px 800px at 50% 0%, black, transparent 75%);
            mask-image: radial-gradient(ellipse 1000px 800px at 50% 0%, black, transparent 75%);
  }}
  body::after {{
    content: ""; position: fixed; inset: 0; z-index: 0; pointer-events: none;
    background-image: repeating-linear-gradient(0deg, rgba(45,216,255,0.035) 0px, rgba(45,216,255,0.035) 1px, transparent 1px, transparent 3px);
    mix-blend-mode: screen;
  }}
  .viz-root {{ position: relative; z-index: 1; }}
  .wrap {{ max-width: 1080px; margin: 0 auto; padding: 36px 24px 72px; }}
  header {{
    display: flex; justify-content: space-between; align-items: flex-end;
    margin-bottom: 28px; flex-wrap: wrap; gap: 14px;
    padding-bottom: 18px; border-bottom: 1px solid var(--border);
  }}
  .hdr-title h1 {{
    margin: 0; font-family: 'Orbitron', sans-serif; font-weight: 700;
    font-size: 25px; letter-spacing: 0.14em; text-transform: uppercase;
    color: var(--text-primary);
    text-shadow: 0 0 10px var(--cyan-glow), 0 0 28px rgba(45,216,255,0.25);
  }}
  .hdr-sub {{
    font-family: 'Share Tech Mono', monospace; font-size: 11px; letter-spacing: 0.28em;
    text-transform: uppercase; color: var(--cyan); opacity: 0.75; margin-top: 4px;
  }}
  .hdr-status {{ text-align: right; }}
  .meta {{ color: var(--text-secondary); font-size: 12.5px; font-family: 'Share Tech Mono', monospace; }}
  .clock {{
    font-family: 'Share Tech Mono', monospace; font-size: 15px; color: var(--cyan);
    text-shadow: 0 0 8px var(--cyan-glow); margin-top: 4px; letter-spacing: 0.06em;
  }}
  .card {{
    position: relative;
    border-radius: 6px;
    padding: 22px 24px;
    margin-bottom: 22px;
    background:
      linear-gradient(var(--cyan-dim), var(--cyan-dim)) top left / 16px 2px no-repeat,
      linear-gradient(var(--cyan-dim), var(--cyan-dim)) top left / 2px 16px no-repeat,
      linear-gradient(var(--cyan-dim), var(--cyan-dim)) top right / 16px 2px no-repeat,
      linear-gradient(var(--cyan-dim), var(--cyan-dim)) top right / 2px 16px no-repeat,
      linear-gradient(var(--cyan-dim), var(--cyan-dim)) bottom left / 16px 2px no-repeat,
      linear-gradient(var(--cyan-dim), var(--cyan-dim)) bottom left / 2px 16px no-repeat,
      linear-gradient(var(--cyan-dim), var(--cyan-dim)) bottom right / 16px 2px no-repeat,
      linear-gradient(var(--cyan-dim), var(--cyan-dim)) bottom right / 2px 16px no-repeat,
      var(--panel);
    border: 1px solid rgba(45,216,255,0.12);
    box-shadow: 0 0 0 1px rgba(45,216,255,0.03), 0 12px 30px rgba(0,0,0,0.45);
    backdrop-filter: blur(6px);
  }}
  .card h2 {{
    font-family: 'Orbitron', sans-serif; font-size: 12px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.16em; color: var(--cyan);
    margin: 0 0 18px; display: flex; align-items: center; gap: 10px;
  }}
  .card h2::after {{ content: ""; flex: 1; height: 1px; background: linear-gradient(90deg, var(--cyan-dim), transparent); }}
  .tiles {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 14px; }}
  .tile {{
    background: var(--panel-solid); border: 1px solid rgba(45,216,255,0.14); border-radius: 5px;
    padding: 14px 16px; position: relative; overflow: hidden;
  }}
  .tile::before {{ content: ""; position: absolute; top: 0; left: 0; width: 100%; height: 2px; background: linear-gradient(90deg, var(--cyan), transparent); opacity: 0.6; }}
  .tile-label {{
    font-family: 'Share Tech Mono', monospace; font-size: 10.5px; text-transform: uppercase;
    letter-spacing: 0.1em; color: var(--text-secondary); display: flex; align-items: center; gap: 6px; margin-bottom: 8px;
  }}
  .tile-value {{
    font-family: 'Orbitron', sans-serif; font-size: 22px; font-weight: 700; color: var(--text-primary);
    text-shadow: 0 0 12px rgba(45,216,255,0.18); font-variant-numeric: tabular-nums;
  }}
  .dot {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; box-shadow: 0 0 6px currentColor; }}
  .empty {{ color: var(--text-muted); font-size: 13px; padding: 12px 0; font-family: 'Rajdhani', sans-serif; }}
  .timeline-svg {{ width: 100%; height: auto; }}
  .baseline {{ stroke: var(--baseline); stroke-width: 1; stroke-dasharray: 2 4; }}
  .axis-label {{ fill: var(--text-muted); font-size: 11px; font-family: 'Share Tech Mono', monospace; }}
  .pl-end-label {{ fill: var(--text-primary); font-size: 13px; font-weight: 600; font-family: 'Share Tech Mono', monospace; }}
  .dot-mark {{ cursor: pointer; filter: drop-shadow(0 0 4px currentColor); }}
  .legend {{ display: flex; gap: 18px; font-size: 11.5px; color: var(--text-secondary); margin-top: 10px; font-family: 'Share Tech Mono', monospace; text-transform: uppercase; letter-spacing: 0.06em; }}
  .legend span {{ display: inline-flex; align-items: center; gap: 6px; }}
  table.log-table {{ width: 100%; border-collapse: collapse; font-size: 13px; font-family: 'Rajdhani', sans-serif; }}
  .log-table th {{
    text-align: left; color: var(--cyan); font-weight: 600; font-size: 10.5px; text-transform: uppercase;
    letter-spacing: 0.08em; padding: 9px 12px; border-bottom: 1px solid var(--border);
    font-family: 'Share Tech Mono', monospace;
  }}
  .log-table td {{ padding: 9px 12px; border-bottom: 1px solid var(--gridline); vertical-align: top; }}
  .log-table tr:hover td {{ background: rgba(45,216,255,0.05); }}
  .mono {{ font-variant-numeric: tabular-nums; font-family: 'Share Tech Mono', monospace; font-size: 12.5px; }}
  .rationale {{ color: var(--text-secondary); max-width: 420px; }}
  .badge {{
    font-family: 'Share Tech Mono', monospace; font-size: 10.5px; padding: 3px 10px; border-radius: 999px;
    text-transform: uppercase; letter-spacing: 0.05em; border: 1px solid currentColor;
  }}
  .badge-executed {{ background: rgba(51,255,176,0.10); color: {STATUS_GOOD}; }}
  .badge-dry {{ background: rgba(76,108,125,0.14); color: var(--text-secondary); border-color: rgba(76,108,125,0.5); }}
  .live-dot {{
    position: relative; display: inline-block; width: 9px; height: 9px; border-radius: 50%;
    background: var(--good); margin-right: 8px; box-shadow: 0 0 6px var(--good), 0 0 14px var(--good);
  }}
  .live-dot::after {{
    content: ""; position: absolute; inset: -6px; border-radius: 50%; border: 1px solid var(--good);
    opacity: 0.6; animation: radarping 1.8s ease-out infinite;
  }}
  .live-dot.stale {{ background: var(--critical); box-shadow: 0 0 6px var(--critical); }}
  .live-dot.stale::after {{ border-color: var(--critical); }}
  @keyframes radarping {{ 0% {{ transform: scale(0.6); opacity: 0.8; }} 100% {{ transform: scale(2.4); opacity: 0; }} }}
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
