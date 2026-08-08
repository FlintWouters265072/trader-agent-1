"""Live-updating dashboard for the trading agent — a small local Flask server
(instead of dashboard.py's static file) so the browser tab refreshes itself
on a timer without you having to re-run anything.

Usage: python3 dashboard_server.py
Then open http://127.0.0.1:8765 (or set DASHBOARD_PORT to change the port).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from flask import Flask, jsonify

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


@app.route("/api/refresh")
def api_refresh():
    return jsonify(render_payload())


@app.route("/")
def index():
    payload = render_payload()
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
