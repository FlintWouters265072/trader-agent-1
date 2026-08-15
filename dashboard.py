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

ACCENT = "#2196f3"
STATUS_GOOD = "#4caf50"
STATUS_CRITICAL = "#ef5350"
STATUS_WARN = "#ffc107"
STATUS_MUTED = "#6b7280"

ACTION_COLOR = {"buy": STATUS_GOOD, "sell": STATUS_CRITICAL, "hold": STATUS_WARN}

AMSTERDAM_TZ = ZoneInfo("Europe/Amsterdam")


def format_amsterdam_time(timestamp: str) -> str:
    """Parses a stored ISO UTC timestamp into Amsterdam local time, e.g. '13-8-2026 18:03'."""
    if not timestamp:
        return ""
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
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


def format_signed(value, currency: str = "") -> str:
    sign = "+" if value >= 0 else ""
    text = f"{sign}{value:,.2f}"
    return f"{text} {currency}".strip()


def ring_counter(value, label: str, color: str) -> str:
    return f"""
    <div class="ring">
      <svg viewBox="0 0 48 48" aria-hidden="true">
        <circle cx="24" cy="24" r="20" fill="none" stroke="{color}" stroke-width="3" opacity="0.9" />
      </svg>
      <div class="ring-num" style="color:{color}">{html.escape(str(value))}</div>
      <div class="ring-label">{html.escape(label)}</div>
    </div>"""


def render_decisions_card(stats: dict) -> str:
    total = stats["total"]
    executed_pct = (stats["executed"] / total * 100) if total else 0.0
    # Semicircle gauge: radius 50 → arc length ≈ 157.
    arc_len = 157.0
    offset = arc_len * (1 - executed_pct / 100)
    rings = "".join([
        ring_counter(stats["buy"], "Buy", STATUS_GOOD),
        ring_counter(stats["sell"], "Sell", STATUS_CRITICAL),
        ring_counter(stats["hold"], "Hold", STATUS_WARN),
        ring_counter(stats["executed"], "Executed", ACCENT),
        ring_counter(stats["dry_run"], "Dry-run", STATUS_MUTED),
    ])
    return f"""
    <div class="perf-grid">
      <div class="perf-nums">
        <div class="perf-big" style="color:{ACCENT}">{total}</div>
        <div class="perf-sub">decisions logged</div>
      </div>
      <div class="gauge-wrap">
        <svg viewBox="0 0 120 70" class="gauge-svg" role="img" aria-label="Share of decisions executed">
          <path d="M 10 60 A 50 50 0 0 1 110 60" fill="none" stroke="var(--border)" stroke-width="7" stroke-linecap="round" />
          <path d="M 10 60 A 50 50 0 0 1 110 60" fill="none" stroke="{ACCENT}" stroke-width="7" stroke-linecap="round"
                stroke-dasharray="{arc_len:.0f}" stroke-dashoffset="{offset:.1f}" />
          <text x="60" y="52" class="gauge-pct">{executed_pct:.1f}%</text>
        </svg>
        <div class="gauge-caption">executed</div>
      </div>
      <div class="rings">{rings}</div>
    </div>"""


def render_account_summary(snapshot: dict | None) -> str:
    if not snapshot or not snapshot.get("account"):
        return (
            '<div class="empty">Live account data unavailable (missing/invalid ALPACA_API_KEY_ID '
            "or ALPACA_API_SECRET_KEY, or the account request failed).</div>"
        )
    account = snapshot["account"]
    positions = snapshot.get("positions") or []
    currency = account.get("currency", "USD")
    unrealized = sum(float(p.get("unrealized_pl", 0) or 0) for p in positions)
    total_value = float(account.get("portfolio_value", 0) or 0)
    cash_balance = float(account.get("cash", 0) or 0)
    pl_class = "pos" if unrealized >= 0 else "neg"
    return f"""
    <div class="kv-rows">
      <div class="kv"><span>Account Balance</span><span class="kv-val pos">${total_value:,.2f}</span></div>
      <div class="kv"><span>Cash</span><span class="kv-val">${cash_balance:,.2f}</span></div>
      <div class="kv"><span>Unrealized P&amp;L</span><span class="kv-val {pl_class}">{html.escape(format_signed(unrealized))}</span></div>
      <div class="kv"><span>Currency</span><span class="kv-val">{html.escape(currency)}</span></div>
      <div class="kv"><span>Account ID</span><span class="kv-val kv-dim">{html.escape(str(account.get("account_number", "—")))}</span></div>
      <div class="kv"><span>Open Positions</span><span class="kv-val">{len(positions)}</span></div>
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

    width, height, pad = 1200, 110, 40
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
            f'<circle cx="{x:.1f}" cy="{height / 2:.1f}" r="5" fill="{color}" '
            f'stroke="var(--card)" stroke-width="2" class="dot-mark" '
            f'data-tooltip="{tooltip}"><title>{tooltip}</title></circle>'
        )

    axis_label_start = html.escape(t_min.strftime("%Y-%m-%d"))
    axis_label_end = html.escape(t_max.strftime("%Y-%m-%d"))

    return f"""
    <svg viewBox="0 0 {width} {height}" class="timeline-svg" role="img" aria-label="Decision timeline">
      <line x1="{pad}" y1="{height / 2}" x2="{width - pad}" y2="{height / 2}" class="baseline" />
      {"".join(dots)}
      <text x="{pad}" y="{height - 8}" class="axis-label">{axis_label_start}</text>
      <text x="{width - pad}" y="{height - 8}" class="axis-label" text-anchor="end">{axis_label_end}</text>
    </svg>"""


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
    pl_min -= pl_range * 0.12
    pl_max += pl_range * 0.12
    pl_range = pl_max - pl_min

    width, height = 900, 260
    pad_l, pad_r, pad_t, pad_b = 76, 24, 18, 36
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b

    def x_for(t):
        frac = (t - t_min).total_seconds() / span
        return pad_l + frac * plot_w

    def y_for(pl):
        frac = (pl - pl_min) / pl_range
        return pad_t + plot_h - frac * plot_h

    # Horizontal gridlines with dollar labels, Trading Vault style.
    gridlines = []
    ticks = 4
    for i in range(ticks + 1):
        v = pl_min + (pl_range * i / ticks)
        y = y_for(v)
        gridlines.append(
            f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width - pad_r}" y2="{y:.1f}" class="gridline" />'
            f'<text x="{pad_l - 10}" y="{y + 4:.1f}" class="axis-label" text-anchor="end">{format_signed(v)}</text>'
        )

    zero_y = y_for(0)
    latest_pl = paired[-1][1]
    latest_currency = history[-1].get("currency", "")

    points = [(x_for(t), y_for(pl)) for t, pl in paired]
    polyline_points = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)

    dots = []
    for (t, pl), (x, y) in zip(paired, points):
        tooltip = html.escape(f"{t.strftime('%Y-%m-%d %H:%M UTC')} · {format_signed(pl, latest_currency)}")
        dots.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{ACCENT}" '
            f'stroke="var(--card)" stroke-width="2" class="dot-mark" '
            f'data-tooltip="{tooltip}"><title>{tooltip}</title></circle>'
        )

    end_x, end_y = points[-1]
    start_x = points[0][0]
    bottom_y = pad_t + plot_h
    end_label = html.escape(format_signed(latest_pl, latest_currency))
    axis_label_start = html.escape(t_min.strftime("%b %d %H:%M"))
    axis_label_end = html.escape(t_max.strftime("%b %d %H:%M"))

    return f"""
    <svg viewBox="0 0 {width} {height}" class="timeline-svg" role="img" aria-label="Unrealized profit and loss over time">
      <defs>
        <linearGradient id="chartGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="{ACCENT}" stop-opacity="0.35"/>
          <stop offset="100%" stop-color="{ACCENT}" stop-opacity="0.02"/>
        </linearGradient>
      </defs>
      {"".join(gridlines)}
      <line x1="{pad_l}" y1="{zero_y:.1f}" x2="{width - pad_r}" y2="{zero_y:.1f}" class="baseline" />
      <polygon points="{polyline_points} {end_x:.1f},{bottom_y:.1f} {start_x:.1f},{bottom_y:.1f}" fill="url(#chartGrad)" />
      <polyline points="{polyline_points}" fill="none" stroke="{ACCENT}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />
      {"".join(dots)}
      <text x="{end_x:.1f}" y="{end_y - 12:.1f}" class="axis-label pl-end-label" text-anchor="end">{end_label}</text>
      <text x="{pad_l}" y="{height - 8}" class="axis-label">{axis_label_start}</text>
      <text x="{width - pad_r}" y="{height - 8}" class="axis-label" text-anchor="end">{axis_label_end}</text>
    </svg>"""


def side_pill(side: str) -> str:
    side = (side or "").lower()
    cls = "pill-long" if side in ("buy", "long") else "pill-short"
    return f'<span class="pill {cls}">{html.escape(side.upper() or "—")}</span>'


def render_positions(snapshot: dict | None) -> str:
    if not snapshot:
        return '<div class="empty">Live account data unavailable (missing/invalid Alpaca API keys, or request failed).</div>'

    positions_data = snapshot.get("positions") or []
    if not positions_data:
        return '<div class="empty">No open positions.</div>'

    rows = []
    for p in positions_data:
        pl = p.get("unrealized_pl")
        pl = float(pl) if pl is not None else None
        pl_html = (
            f'<div class="trade-pl {"pos" if pl >= 0 else "neg"}">{html.escape(format_signed(pl))}</div>'
            if pl is not None
            else '<div class="trade-pl">—</div>'
        )
        qty = html.escape(str(p.get("qty", "")))
        entry = html.escape(str(p.get("avg_entry_price", "")))
        current = html.escape(str(p.get("current_price", "—")))
        rows.append(f"""
        <div class="trade-row">
          <div>
            <div class="trade-sym">{html.escape(str(p.get("symbol", "")))} {side_pill(p.get("side", ""))}</div>
            <div class="trade-sub">{qty} @ ${entry}</div>
          </div>
          <div class="trade-right">
            <div class="trade-price">${current}</div>
            {pl_html}
          </div>
        </div>""")
    return f'<div class="trade-list">{"".join(rows)}</div>'


def render_open_orders(snapshot: dict | None) -> str:
    if not snapshot:
        return '<div class="empty">Live account data unavailable — can\'t show open orders.</div>'

    orders = snapshot.get("orders") or []
    if not orders:
        return '<div class="empty">No open orders.</div>'

    rows = []
    for o in orders:
        status = html.escape(str(o.get("status", "")))
        qty = html.escape(str(o.get("qty", "")))
        filled = html.escape(str(o.get("filled_qty", "0")))
        submitted = html.escape(format_amsterdam_time(str(o.get("submitted_at", ""))))
        rows.append(f"""
        <div class="trade-row">
          <div>
            <div class="trade-sym">{html.escape(str(o.get("symbol", "")))} {side_pill(o.get("side", ""))}</div>
            <div class="trade-sub">{submitted} · {filled}/{qty} filled</div>
          </div>
          <div class="trade-right">
            <span class="badge badge-dry">{status}</span>
          </div>
        </div>""")
    return f'<div class="trade-list">{"".join(rows)}</div>'


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
          <td><span class="action-cell" style="color:{color}">{html.escape(action.upper())}</span></td>
          <td class="sym-cell">{html.escape(dec.get("symbol", ""))}</td>
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


def build_content(decisions: list[dict], stats: dict, snapshot: dict | None, equity_history: list[dict]) -> str:
    return f"""
    <div class="grid">
      <div class="card g-8">
        <h2>Decisions</h2>
        {render_decisions_card(stats)}
      </div>

      <div class="card g-4">
        <h2>Account Balance</h2>
        {render_account_summary(snapshot)}
      </div>

      <div class="card g-8">
        <h2>Unrealized P&amp;L</h2>
        {render_pl_chart(equity_history)}
      </div>

      <div class="card g-4">
        <h2>Open Positions</h2>
        {render_positions(snapshot)}
        <h2 class="section-gap">Open Orders</h2>
        {render_open_orders(snapshot)}
      </div>

      <div class="card g-12">
        <h2>Decision Timeline</h2>
        {render_timeline(decisions)}
        <div class="legend">
          <span><span class="dot" style="background:{STATUS_GOOD}"></span>Buy</span>
          <span><span class="dot" style="background:{STATUS_CRITICAL}"></span>Sell</span>
          <span><span class="dot" style="background:{STATUS_WARN}"></span>Hold</span>
        </div>
      </div>

      <div class="card g-12">
        <details id="decision-log-details" class="log-details">
          <summary>
            <span class="summary-title">Decision Log</span>
            <span class="summary-meta">{len(decisions)} decisions</span>
            <svg class="chevron" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
              <path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </summary>
          {render_table(decisions) or '<div class="empty">No decisions logged yet.</div>'}
        </details>
      </div>
    </div>"""


STYLE = """
  :root {
    --bg: #0a0b0d;
    --card: #131519;
    --card-2: #1a1d23;
    --border: #23262d;
    --accent: #2196f3;
    --accent-soft: rgba(33, 150, 243, 0.12);
    --green: #4caf50;
    --red: #ef5350;
    --amber: #ffc107;
    --muted: #6b7280;
    --text-primary: #e8eaed;
    --text-secondary: #9aa0a8;
    --text-muted: #5c6370;
    --gridline: #1e2127;
    /* Legacy aliases kept for the server-rendered page */
    --surface-1: #131519;
    --cyan: #2196f3;
    --cyan-dim: rgba(33, 150, 243, 0.25);
    --cyan-glow: rgba(33, 150, 243, 0.4);
    --void: #0a0b0d;
  }

  * { box-sizing: border-box; }
  html, body { background: var(--bg); min-height: 100vh; }
  body {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    color: var(--text-primary);
    font-size: 14px;
    -webkit-font-smoothing: antialiased;
  }

  .viz-root { position: relative; }
  .wrap { max-width: 1500px; margin: 0 auto; padding: 20px 20px 60px; }

  header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 18px;
    padding: 14px 4px;
    border-bottom: 1px solid var(--border);
  }
  .hdr-title h1 {
    margin: 0;
    font-size: 20px;
    font-weight: 600;
    letter-spacing: 0.01em;
    color: var(--text-primary);
  }
  .hdr-sub { font-size: 12px; color: var(--text-secondary); margin-top: 3px; }
  .hdr-status { text-align: right; }
  .meta { color: var(--text-secondary); font-size: 12px; }
  .clock { font-size: 14px; color: var(--text-secondary); margin-top: 4px; font-variant-numeric: tabular-nums; }

  .live-dot {
    display: inline-block; width: 8px; height: 8px; border-radius: 50%;
    background: var(--green); margin-right: 8px;
  }
  .live-dot.stale { background: var(--red); }

  /* Card grid, Trading Vault style: tight gaps, rounded dark cards */
  .grid { display: grid; grid-template-columns: repeat(12, 1fr); gap: 14px; }
  .g-4 { grid-column: span 4; }
  .g-8 { grid-column: span 8; }
  .g-12 { grid-column: span 12; }
  @media (max-width: 980px) { .g-4, .g-8 { grid-column: span 12; } }

  .card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 18px 20px;
    min-width: 0;
  }
  #risk-panel .card { margin-top: 14px; }

  .card h2 {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary);
    margin: 0 0 16px;
    letter-spacing: 0.02em;
  }
  .section-gap { margin-top: 22px !important; padding-top: 16px; border-top: 1px solid var(--border); }

  /* Decisions performance card */
  .perf-grid { display: flex; align-items: center; gap: 34px; flex-wrap: wrap; }
  .perf-big { font-size: 40px; font-weight: 600; line-height: 1; font-variant-numeric: tabular-nums; }
  .perf-sub { font-size: 12px; color: var(--text-secondary); margin-top: 6px; }
  .gauge-wrap { text-align: center; }
  .gauge-svg { width: 130px; height: 76px; }
  .gauge-pct { fill: var(--text-primary); font-size: 17px; font-weight: 600; text-anchor: middle; font-variant-numeric: tabular-nums; }
  .gauge-caption { font-size: 11px; color: var(--text-secondary); margin-top: 2px; }

  .rings { display: flex; gap: 18px; flex-wrap: wrap; }
  .ring { position: relative; width: 52px; text-align: center; }
  .ring svg { width: 48px; height: 48px; display: block; margin: 0 auto; }
  .ring-num {
    position: absolute; top: 13px; left: 0; right: 0;
    font-size: 14px; font-weight: 600; font-variant-numeric: tabular-nums;
  }
  .ring-label { font-size: 10px; color: var(--text-secondary); margin-top: 5px; }

  /* Account summary key-value rows */
  .kv-rows { display: flex; flex-direction: column; }
  .kv {
    display: flex; justify-content: space-between; align-items: baseline;
    padding: 9px 0; border-bottom: 1px solid var(--gridline); font-size: 13px;
    color: var(--text-secondary);
  }
  .kv:last-child { border-bottom: none; }
  .kv-val { color: var(--text-primary); font-weight: 600; font-variant-numeric: tabular-nums; }
  .kv-dim { color: var(--text-secondary); font-weight: 400; font-size: 12px; }
  .pos { color: var(--green) !important; }
  .neg { color: var(--red) !important; }

  /* Trades list (positions / open orders) */
  .trade-list { display: flex; flex-direction: column; }
  .trade-row {
    display: flex; justify-content: space-between; align-items: center;
    padding: 10px 0; border-bottom: 1px solid var(--gridline);
  }
  .trade-row:last-child { border-bottom: none; }
  .trade-sym { font-size: 14px; font-weight: 600; display: flex; align-items: center; gap: 8px; }
  .trade-sub { font-size: 11px; color: var(--text-secondary); margin-top: 3px; font-variant-numeric: tabular-nums; }
  .trade-right { text-align: right; }
  .trade-price { font-size: 13px; font-variant-numeric: tabular-nums; }
  .trade-pl { font-size: 12px; font-weight: 600; font-variant-numeric: tabular-nums; margin-top: 2px; }

  .pill {
    font-size: 9px; font-weight: 600; letter-spacing: 0.08em; padding: 2px 7px;
    border-radius: 3px; text-transform: uppercase;
  }
  .pill-long { background: rgba(76, 175, 80, 0.15); color: var(--green); }
  .pill-short { background: rgba(239, 83, 80, 0.15); color: var(--red); }

  /* SVG charts */
  .timeline-svg { width: 100%; height: auto; overflow: visible; }
  .baseline { stroke: var(--text-muted); stroke-width: 1; stroke-dasharray: 4 5; }
  .gridline { stroke: var(--gridline); stroke-width: 1; }
  .axis-label { fill: var(--text-secondary); font-size: 11px; font-family: inherit; }
  .pl-end-label { fill: var(--accent); font-size: 13px; font-weight: 600; }
  .dot-mark { cursor: pointer; transition: r 0.15s; }
  .dot-mark:hover { r: 7; }

  .legend { display: flex; gap: 20px; font-size: 12px; color: var(--text-secondary); margin-top: 12px; }
  .legend span { display: inline-flex; align-items: center; gap: 7px; }
  .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; }

  /* Tables */
  table.log-table { width: 100%; border-collapse: collapse; font-size: 13px; }
  .log-table th {
    text-align: left; color: var(--text-secondary); font-weight: 500; font-size: 11px;
    text-transform: uppercase; letter-spacing: 0.06em; padding: 10px 14px;
    border-bottom: 1px solid var(--border);
  }
  .log-table td { padding: 11px 14px; border-bottom: 1px solid var(--gridline); vertical-align: middle; }
  .log-table tr:hover td { background: var(--card-2); }
  .mono { font-variant-numeric: tabular-nums; }
  .rationale { color: var(--text-secondary); max-width: 480px; line-height: 1.45; font-size: 12px; }
  .action-cell { font-weight: 600; font-size: 12px; letter-spacing: 0.04em; }
  .sym-cell { font-weight: 600; }

  .badge {
    font-size: 10px; font-weight: 600; padding: 3px 9px; border-radius: 3px;
    text-transform: uppercase; letter-spacing: 0.06em;
  }
  .badge-executed { background: var(--accent-soft); color: var(--accent); }
  .badge-dry { background: rgba(107, 114, 128, 0.18); color: var(--text-secondary); }

  .empty {
    color: var(--text-muted); font-size: 13px; padding: 18px 0; text-align: center;
  }
  .empty code { color: var(--text-secondary); }

  /* Collapsible decision log */
  .log-details summary {
    display: flex; align-items: center; gap: 10px;
    cursor: pointer; list-style: none; user-select: none;
  }
  .log-details summary::-webkit-details-marker { display: none; }
  .summary-title { font-size: 13px; font-weight: 600; letter-spacing: 0.02em; }
  .summary-meta { font-size: 12px; color: var(--text-secondary); }
  .chevron { color: var(--text-secondary); margin-left: auto; transition: transform 0.2s; }
  .log-details[open] .chevron { transform: rotate(180deg); }
  .log-details[open] summary { margin-bottom: 14px; }
  .log-details summary:hover .summary-title { color: var(--accent); }

  /* Risk settings form */
  .risk-form { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 16px; margin-bottom: 16px; }
  .risk-field { display: flex; flex-direction: column; gap: 6px; }
  .risk-field-label { font-size: 11px; color: var(--text-secondary); display: flex; align-items: center; gap: 8px; }
  .risk-hint { font-size: 10px; color: var(--text-muted); }
  .risk-form input[type="number"], .risk-form select {
    background: var(--card-2); border: 1px solid var(--border); border-radius: 5px;
    color: var(--text-primary); font-family: inherit; font-size: 13px;
    padding: 9px 11px; outline: none; transition: border-color 0.15s;
  }
  .risk-form input[type="number"]:focus, .risk-form select:focus { border-color: var(--accent); }
  .risk-actions { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 6px; }
  .risk-error {
    color: var(--red); font-size: 13px; margin-bottom: 14px; padding: 10px 14px;
    border: 1px solid rgba(239, 83, 80, 0.4); border-radius: 6px; background: rgba(239, 83, 80, 0.08);
  }

  button {
    background: var(--accent); border: none; border-radius: 5px; color: #fff;
    font-family: inherit; font-size: 13px; font-weight: 600;
    padding: 9px 20px; cursor: pointer; transition: opacity 0.15s;
  }
  button:hover { opacity: 0.85; }
  button[formaction] {
    background: transparent; border: 1px solid var(--border); color: var(--text-secondary);
  }
  button[formaction]:hover { border-color: var(--text-secondary); color: var(--text-primary); }
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

// Keep the decision-log dropdown's open/closed state across the live page's
// periodic #content swaps (and static-page meta refreshes) via localStorage.
const LOG_STATE_KEY = 'decisionLogOpen';
document.addEventListener('toggle', (e) => {
  if (e.target && e.target.id === 'decision-log-details') {
    localStorage.setItem(LOG_STATE_KEY, e.target.open ? '1' : '0');
  }
}, true);
function applyLogState() {
  const el = document.getElementById('decision-log-details');
  if (el && localStorage.getItem(LOG_STATE_KEY) === '1' && !el.open) el.open = true;
}
applyLogState();
const contentEl = document.getElementById('content');
if (contentEl) new MutationObserver(applyLogState).observe(contentEl, { childList: true });
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
