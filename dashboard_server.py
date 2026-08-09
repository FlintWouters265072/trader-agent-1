"""Live-updating dashboard for the trading agent — a small local Flask server
(instead of dashboard.py's static file) so the browser tab refreshes itself
on a timer without you having to re-run anything.

Usage: python3 dashboard_server.py
Then open http://127.0.0.1:8765 (or set DASHBOARD_PORT to change the port).
"""
from __future__ import annotations

import html
import os
from datetime import datetime, timedelta, timezone

from flask import Flask, jsonify, redirect, request, url_for

from config import (
    RISK_SETTINGS,
    effective_risk_settings,
    reset_risk_overrides,
    save_risk_overrides,
    validate_risk_setting,
)
from dashboard import (
    STYLE,
    CLOCK_SCRIPT,
    build_content,
    compute_stats,
    fetch_live_snapshot,
    load_decisions,
    load_equity_history,
    record_equity_snapshot,
)

REFRESH_SECONDS = int(os.environ.get("DASHBOARD_REFRESH_SECONDS", "15"))
EQUITY_SNAPSHOT_MIN_GAP = timedelta(minutes=5)

app = Flask(__name__)


def maybe_record_equity_snapshot(snapshot: dict | None) -> None:
    """Append an equity snapshot at most once per EQUITY_SNAPSHOT_MIN_GAP, so
    polling every few seconds doesn't flood equity_history.jsonl with a line
    per request."""
    if not snapshot or not snapshot.get("account"):
        return
    history = load_equity_history()
    if history:
        last_ts = history[-1].get("timestamp", "")
        try:
            last_t = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - last_t < EQUITY_SNAPSHOT_MIN_GAP:
                return
        except ValueError:
            pass
    record_equity_snapshot(snapshot)


def render_payload() -> dict:
    decisions = load_decisions()
    stats = compute_stats(decisions)
    snapshot = fetch_live_snapshot()
    maybe_record_equity_snapshot(snapshot)
    equity_history = load_equity_history()
    content = build_content(decisions, stats, snapshot, equity_history)
    return {
        "html": content,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "live": snapshot is not None,
    }


def render_risk_settings_card(risk_settings: dict, error: str | None = None, submitted=None) -> str:
    rows = []
    for key, spec in RISK_SETTINGS.items():
        current = submitted.get(key) if submitted else risk_settings[key]["value"]
        badge = (
            '<span class="badge badge-dry">override</span>'
            if risk_settings[key]["source"] == "override"
            else '<span class="badge badge-executed">.env default</span>'
        )
        if "choices" in spec:
            options = "".join(
                f'<option value="{c}"{" selected" if str(current).lower() == c else ""}>{c.capitalize()}</option>'
                for c in spec["choices"]
            )
            field_html = f'<select name="{key}" required>{options}</select>'
        else:
            step = "1" if spec["type"] is int else "any"
            field_html = (
                f'<input type="number" name="{key}" value="{html.escape(str(current))}" '
                f'min="{spec["min"]}" max="{spec["max"]}" step="{step}" required>'
            )
        rows.append(f"""
        <label class="risk-field">
          <span class="risk-field-label">{html.escape(spec['label'])} {badge}</span>
          {field_html}
          <span class="risk-hint">.env default: {risk_settings[key]['env_default']}</span>
        </label>""")
    error_html = f'<div class="risk-error">{html.escape(error)}</div>' if error else ""
    return f"""
    <div class="card">
      <h2>Risk settings</h2>
      {error_html}
      <form method="post" action="/risk-settings" class="risk-form">
        {''.join(rows)}
        <div class="risk-actions">
          <button type="submit">Save</button>
          <button type="submit" formaction="/risk-settings/reset" formnovalidate>Reset all to .env defaults</button>
        </div>
      </form>
      <div class="empty">Saved values are written to <code>risk_overrides.json</code> (gitignored, shared with the
      trading-agent container via the same bind mount as <code>.env</code>) and take effect on the agent's next
      cycle — no restart needed. A field with no override falls back to its <code>.env</code> value.
      "Risk appetite" only steers which kinds of assets get picked — it doesn't change the dollar/count caps.</div>
    </div>"""


@app.route("/api/refresh")
def api_refresh():
    return jsonify(render_payload())


@app.route("/risk-settings", methods=["POST"])
def update_risk_settings():
    values = {}
    for key in RISK_SETTINGS:
        value, error = validate_risk_setting(key, request.form.get(key, "").strip())
        if error:
            payload = render_payload()
            risk_card = render_risk_settings_card(effective_risk_settings(), error=error, submitted=request.form)
            return render_page(payload, risk_card), 400
        values[key] = value
    save_risk_overrides(values)
    return redirect(url_for("index"))


@app.route("/risk-settings/reset", methods=["POST"])
def reset_risk_settings():
    reset_risk_overrides()
    return redirect(url_for("index"))


def render_page(payload: dict, risk_card: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
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
        <div class="meta" id="meta"><span class="live-dot" id="live-dot"></span>Updated {payload["generated_at"]} · refreshing every {REFRESH_SECONDS}s</div>
        <div class="clock" id="clock"></div>
      </div>
    </header>
    <div id="content">{payload["html"]}</div>
    <div id="risk-panel">{risk_card}</div>
  </div>
</div>
<script>{CLOCK_SCRIPT}
const REFRESH_MS = {REFRESH_SECONDS * 1000};
async function refresh() {{
  const dot = document.getElementById('live-dot');
  try {{
    const res = await fetch('/api/refresh', {{ cache: 'no-store' }});
    if (!res.ok) throw new Error('bad response');
    const data = await res.json();
    document.getElementById('content').innerHTML = data.html;
    document.getElementById('meta').innerHTML =
      '<span class="live-dot' + (data.live ? '' : ' stale') + '" id="live-dot"></span>Updated ' + data.generated_at +
      ' · refreshing every {REFRESH_SECONDS}s' + (data.live ? '' : ' · Alpaca connection unavailable, showing decision log only');
  }} catch (e) {{
    dot.classList.add('stale');
    console.error('dashboard refresh failed', e);
  }}
}}
setInterval(refresh, REFRESH_MS);
</script>
</body>
</html>"""


@app.route("/")
def index():
    payload = render_payload()
    risk_card = render_risk_settings_card(effective_risk_settings())
    return render_page(payload, risk_card)


def main():
    port = int(os.environ.get("DASHBOARD_PORT", "8765"))
    # Binds to 127.0.0.1 by default so it's never reachable beyond this machine. Inside a
    # container that loopback is the container's own, not the host's, so Docker deployments
    # set DASHBOARD_HOST=0.0.0.0 and instead restrict exposure via the host-side port mapping
    # (see docker-compose.yml, which maps 127.0.0.1:8765 on the VPS, not 0.0.0.0:8765).
    host = os.environ.get("DASHBOARD_HOST", "127.0.0.1")
    print(f"Live dashboard: http://127.0.0.1:{port}  (Ctrl+C to stop)")
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
