import re

with open("dashboard.py", "r") as f:
    content = f.read()

# Replace STATUS_GOOD, CRITICAL, MUTED
content = re.sub(r'STATUS_GOOD = "#33ffb0"', 'STATUS_GOOD = "#00ff88"', content)
content = re.sub(r'STATUS_CRITICAL = "#ff4d6d"', 'STATUS_CRITICAL = "#ff2d55"', content)
content = re.sub(r'STATUS_MUTED = "#5b7c92"', 'STATUS_MUTED = "#5b8a9a"', content)

STYLE_NEW = '''
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
'''

CLOCK_SCRIPT_NEW = '''
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
'''

# Update STYLE and CLOCK_SCRIPT
import re
content = re.sub(r'STYLE = f"""[\s\S]*?(?=\nCLOCK_SCRIPT = )', f'STYLE = f"""{STYLE_NEW}"""\n', content)
content = re.sub(r'CLOCK_SCRIPT = """[\s\S]*?(?=\n\ndef build_html)', f'CLOCK_SCRIPT = """{CLOCK_SCRIPT_NEW}"""\n', content)


# Now update render_profit_tracker to include the new SVG gauge and layout
profit_tracker_old = r'''def render_profit_tracker\(snapshot: dict \| None, history: list\[dict\]\) -> str:[\s\S]*?return f'<div class="tiles">\{tiles\}</div>\{render_pl_chart\(history\)\}\''''

profit_tracker_new = '''def render_profit_tracker(snapshot: dict | None, history: list[dict]) -> str:
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
'''
content = re.sub(profit_tracker_old, profit_tracker_new, content)

# update render_pl_chart to add gradient fill under the line
pl_chart_old = r'''<polyline points="\{polyline_points\}" fill="none" stroke="\{line_color\}" stroke-width="2" \\\nstroke-linejoin="round" stroke-linecap="round" />'''
pl_chart_new = '''<defs>
        <linearGradient id="chartGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="{line_color}" stop-opacity="0.3"/>
          <stop offset="100%" stop-color="{line_color}" stop-opacity="0.0"/>
        </linearGradient>
      </defs>
      <polygon points="{polyline_points} {end_x:.1f},{zero_y:.1f} {pad:.1f},{zero_y:.1f}" fill="url(#chartGrad)" />
      <polyline points="{polyline_points}" fill="none" stroke="{line_color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />'''
content = content.replace(pl_chart_old, pl_chart_new)

with open("dashboard.py", "w") as f:
    f.write(content)
