from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from aistock.core.types import Fill, PortfolioSnapshot, TradeDecision


def write_cycle_report(
    data_dir: Path,
    symbols_scanned: list[str],
    decisions: list[TradeDecision],
    fills: list[Fill],
    portfolio: PortfolioSnapshot,
    previous_equity: float | None,
    history_limit: int,
) -> dict:
    data_dir.mkdir(parents=True, exist_ok=True)

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbols_scanned": symbols_scanned,
        "decision_count": len(decisions),
        "fill_count": len(fills),
        "equity": round(portfolio.equity, 2),
        "cash": round(portfolio.cash, 2),
        "equity_delta": None if previous_equity is None else round(portfolio.equity - previous_equity, 2),
        "positions": [
            {"symbol": p.symbol, "quantity": p.quantity, "avg_cost": round(p.avg_cost, 4)}
            for p in portfolio.positions
        ],
        "fills": [
            {
                "timestamp": f.timestamp.isoformat(),
                "symbol": f.symbol,
                "action": f.action,
                "quantity": f.quantity,
                "fill_price": round(f.fill_price, 4),
                "fee": round(f.fee, 4),
            }
            for f in fills
        ],
        "decisions": [
            {
                "symbol": d.symbol,
                "action": d.action,
                "quantity": d.quantity,
                "confidence": round(d.confidence, 4),
                "reason": d.reason,
            }
            for d in decisions
        ],
    }

    reports_path = data_dir / "cycle_reports.jsonl"
    with reports_path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(report) + "\n")

    latest_path = data_dir / "latest_cycle.json"
    latest_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    history = read_recent_reports(data_dir, history_limit)
    _write_dashboard_html(data_dir, report, history)
    return report


def read_recent_reports(data_dir: Path, limit: int) -> list[dict]:
    reports_path = data_dir / "cycle_reports.jsonl"
    if not reports_path.exists():
        return []

    out: list[dict] = []
    with reports_path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    return out[-max(1, limit) :]


def _write_dashboard_html(data_dir: Path, latest: dict, history: list[dict]) -> None:
    latest_positions = "".join(
        f"<tr><td>{p['symbol']}</td><td>{p['quantity']}</td><td>{p['avg_cost']}</td></tr>"
        for p in latest.get("positions", [])
    )
    recent_rows = "".join(
        f"<tr><td>{r.get('timestamp','')}</td><td>{r.get('equity','')}</td><td>{r.get('equity_delta','')}</td><td>{r.get('fill_count','')}</td></tr>"
        for r in reversed(history[-30:])
    )

    html = f"""<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>AIStock Dashboard</title>
  <style>
    :root {{ --bg:#0f172a; --card:#111827; --text:#e5e7eb; --muted:#9ca3af; --ok:#22c55e; --bad:#ef4444; }}
    body {{ margin:0; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif; background: radial-gradient(circle at top, #1f2937, #020617 60%); color:var(--text); }}
    .wrap {{ max-width: 1100px; margin: 0 auto; padding: 24px; }}
    .grid {{ display:grid; grid-template-columns: repeat(auto-fit,minmax(220px,1fr)); gap:12px; }}
    .card {{ background:rgba(17,24,39,.9); border:1px solid #374151; border-radius:14px; padding:14px; }}
    .label {{ color:var(--muted); font-size:12px; }}
    .value {{ font-size:22px; font-weight:700; }}
    table {{ width:100%; border-collapse: collapse; }}
    th, td {{ border-bottom:1px solid #374151; text-align:left; padding:8px; font-size:13px; }}
    th {{ color:#93c5fd; }}
  </style>
</head>
<body>
  <div class=\"wrap\">
    <h1>AIStock Cycle Dashboard</h1>
    <p>Updated: {latest.get('timestamp','')}</p>
    <div class=\"grid\">
      <div class=\"card\"><div class=\"label\">Portfolio Equity</div><div class=\"value\">${latest.get('equity','')}</div></div>
      <div class=\"card\"><div class=\"label\">Cash</div><div class=\"value\">${latest.get('cash','')}</div></div>
      <div class=\"card\"><div class=\"label\">Equity Change</div><div class=\"value\">{latest.get('equity_delta','N/A')}</div></div>
      <div class=\"card\"><div class=\"label\">Symbols Scanned</div><div class=\"value\">{len(latest.get('symbols_scanned', []))}</div></div>
    </div>

    <h2>Current Positions</h2>
    <div class=\"card\">
      <table>
        <thead><tr><th>Symbol</th><th>Qty</th><th>Avg Cost</th></tr></thead>
        <tbody>{latest_positions or '<tr><td colspan="3">No positions</td></tr>'}</tbody>
      </table>
    </div>

    <h2>Recent Cycles</h2>
    <div class=\"card\">
      <table>
        <thead><tr><th>Timestamp</th><th>Equity</th><th>Delta</th><th>Fills</th></tr></thead>
        <tbody>{recent_rows or '<tr><td colspan="4">No cycles yet</td></tr>'}</tbody>
      </table>
    </div>
  </div>
</body>
</html>
"""

    (data_dir / "dashboard.html").write_text(html, encoding="utf-8")
