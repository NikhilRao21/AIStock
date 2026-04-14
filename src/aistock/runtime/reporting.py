from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aistock.core.types import AiSignal, Fill, PortfolioSnapshot, Position, TradeDecision

_HIDDEN_GEM_MIN_CONFIDENCE = 0.8
_SIGNAL_PERFORMANCE_MIN_TRADES = 5
_SIGNAL_PERFORMANCE_MIN_WIN_RATE = 0.45


def write_cycle_report(
    data_dir: Path,
    symbols_scanned: list[str],
    decisions: list[TradeDecision],
    fills: list[Fill],
    portfolio: PortfolioSnapshot,
    ai_output: list[AiSignal],
    market_prices: dict[str, float],
    previous_equity: float | None,
    previous_positions: list[Position],
    news_status: dict[str, Any] | None,
    signal_policy: dict[str, Any] | None,
    history_limit: int,
) -> dict:
    data_dir.mkdir(parents=True, exist_ok=True)

    history = read_recent_reports(data_dir, history_limit)
    signal_performance = _build_signal_performance(history, market_prices)
    current_positions = [
        {"symbol": p.symbol, "quantity": p.quantity, "avg_cost": round(p.avg_cost, 4)}
        for p in portfolio.positions
    ]
    previous_position_symbols = {p.symbol for p in previous_positions}
    current_position_symbols = {p["symbol"] for p in current_positions}
    new_buys = [p for p in current_positions if p["symbol"] not in previous_position_symbols]
    carried_positions = [p for p in current_positions if p["symbol"] in previous_position_symbols]
    closed_positions = [
        {"symbol": p.symbol, "quantity": p.quantity, "avg_cost": round(p.avg_cost, 4)}
        for p in previous_positions
        if p.symbol not in current_position_symbols
    ]
    hidden_gem_candidates = [
        {
            "symbol": d.symbol,
            "confidence": round(d.confidence, 4),
            "reason": d.hidden_gem_reason or d.reason,
            "signals": [
                {
                    "family": signal.family,
                    "action": signal.action,
                    "confidence": round(signal.confidence, 4),
                    "details": signal.details,
                }
                for signal in d.signals
            ],
        }
        for d in decisions
        if d.is_hidden_gem
    ]
    ai_output_rows = [
        {
            "symbol": signal.symbol,
            "action": signal.action,
            "confidence": round(signal.confidence, 4),
            "rationale": signal.rationale,
        }
        for signal in ai_output
    ]

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbols_scanned": symbols_scanned,
        "decision_count": len(decisions),
        "fill_count": len(fills),
        "equity": round(portfolio.equity, 2),
        "cash": round(portfolio.cash, 2),
        "equity_delta": None if previous_equity is None else round(portfolio.equity - previous_equity, 2),
        "ai_output": ai_output_rows,
        "ai_output_count": len(ai_output_rows),
        "market_prices": {symbol: round(price, 4) for symbol, price in market_prices.items()},
        "positions": current_positions,
        "position_changes": {
          "new_buys": new_buys,
          "carried_positions": carried_positions,
          "closed_positions": closed_positions,
        },
        "hidden_gem_candidates": hidden_gem_candidates,
        "news_status": news_status or {"ok": True, "fallback_used": False, "error": None},
        "signal_policy": signal_policy or {"ai_weight": None, "conventional_weight": None, "disabled": []},
        "signal_performance": signal_performance,
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
                "confidence": round(d.confidence, 4),
                "reason": d.reason,
                "signals": [
                  {
                    "family": signal.family,
                    "action": signal.action,
                    "confidence": round(signal.confidence, 4),
                    "details": signal.details,
                  }
                  for signal in d.signals
                ],
                "is_hidden_gem": d.is_hidden_gem,
                "hidden_gem_reason": d.hidden_gem_reason,
            }
            for d in decisions
        ],
    }

    reports_path = data_dir / "cycle_reports.jsonl"
    with reports_path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(report) + "\n")

    latest_path = data_dir / "latest_cycle.json"
    latest_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    _write_dashboard_html(data_dir, report, history + [report])
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


def _build_signal_performance(history: list[dict], latest_prices: dict[str, float]) -> dict[str, Any]:
    if not history:
        return {"families": {}, "underperformers": [], "evaluated_trades": 0}

    latest_trade_price = {symbol: float(price) for symbol, price in latest_prices.items()}
    family_stats: dict[str, dict[str, float]] = defaultdict(
        lambda: {"trades": 0.0, "wins": 0.0, "return_sum": 0.0, "confidence_sum": 0.0}
    )

    for report in history:
        fill_index: dict[tuple[str, str, int], dict[str, Any]] = {}
        for decision in report.get("decisions", []):
            fill_index[(
                str(decision.get("symbol", "")),
                str(decision.get("action", "")),
                int(decision.get("quantity", 0) or 0),
            )] = decision

        for fill in report.get("fills", []):
            symbol = str(fill.get("symbol", ""))
            action = str(fill.get("action", ""))
            quantity = int(fill.get("quantity", 0) or 0)
            fill_price = float(fill.get("fill_price", 0.0) or 0.0)
            current_price = latest_trade_price.get(symbol)
            if not current_price or fill_price <= 0:
                continue

            outcome = (current_price - fill_price) / fill_price if action == "BUY" else (fill_price - current_price) / fill_price
            if outcome == 0:
                continue

            decision = fill_index.get((symbol, action, quantity))
            if not decision:
                continue

            for signal in decision.get("signals", []):
                family = str(signal.get("family", "unknown"))
                stats = family_stats[family]
                stats["trades"] += 1
                stats["wins"] += 1 if outcome > 0 else 0
                stats["return_sum"] += outcome
                stats["confidence_sum"] += float(signal.get("confidence", 0.0) or 0.0)

    families: dict[str, dict[str, Any]] = {}
    underperformers: list[dict[str, Any]] = []
    for family, stats in family_stats.items():
        trade_count = int(stats["trades"])
        if trade_count <= 0:
            continue
        win_rate = stats["wins"] / trade_count
        avg_return = stats["return_sum"] / trade_count
        avg_confidence = stats["confidence_sum"] / trade_count
        status = "active"
        if trade_count >= _SIGNAL_PERFORMANCE_MIN_TRADES and (
            win_rate < _SIGNAL_PERFORMANCE_MIN_WIN_RATE or avg_return < 0
        ):
            status = "underperforming"
            underperformers.append(
                {
                    "family": family,
                    "win_rate": round(win_rate, 4),
                    "avg_return": round(avg_return, 4),
                    "trades": trade_count,
                }
            )

        families[family] = {
            "trades": trade_count,
            "wins": int(stats["wins"]),
            "win_rate": round(win_rate, 4),
            "avg_return": round(avg_return, 4),
            "avg_confidence": round(avg_confidence, 4),
            "status": status,
        }

    return {
        "families": families,
        "underperformers": underperformers,
        "evaluated_trades": sum(item["trades"] for item in families.values()),
    }


def _write_dashboard_html(data_dir: Path, latest: dict, history: list[dict]) -> None:
    latest_positions = latest.get("positions", [])
    position_change = latest.get("position_changes", {})
    new_buy_rows = "".join(
        f"<tr><td>{p['symbol']}</td><td>{p['quantity']}</td><td>${p['avg_cost']}</td></tr>"
        for p in position_change.get("new_buys", [])
    )
    carried_rows = "".join(
        f"<tr><td>{p['symbol']}</td><td>{p['quantity']}</td><td>${p['avg_cost']}</td></tr>"
        for p in position_change.get("carried_positions", [])
    )
    closed_rows = "".join(
        f"<tr><td>{p['symbol']}</td><td>{p['quantity']}</td><td>${p['avg_cost']}</td></tr>"
        for p in position_change.get("closed_positions", [])
    )
    scanned_rows = "".join(f"<li>{symbol}</li>" for symbol in latest.get("symbols_scanned", []))
    hidden_rows = "".join(
        f"<tr><td>{candidate['symbol']}</td><td>{candidate['confidence']}</td><td>{candidate['reason']}</td></tr>"
        for candidate in latest.get("hidden_gem_candidates", [])
    )
    signal_rows = "".join(
        f"<tr><td>{family}</td><td>{summary.get('trades', 0)}</td><td>{summary.get('win_rate', 0)}</td><td>{summary.get('avg_return', 0)}</td><td>{summary.get('avg_confidence', 0)}</td><td>{summary.get('status', '')}</td></tr>"
        for family, summary in latest.get("signal_performance", {}).get("families", {}).items()
    )
    underperformer_rows = "".join(
        f"<tr><td>{item['family']}</td><td>{item['trades']}</td><td>{item['win_rate']}</td><td>{item['avg_return']}</td></tr>"
        for item in latest.get("signal_performance", {}).get("underperformers", [])
    )
    recent_rows = "".join(
        f"<tr><td>{r.get('timestamp','')}</td><td>{r.get('equity','')}</td><td>{r.get('equity_delta','')}</td><td>{r.get('fill_count','')}</td><td>{len(r.get('hidden_gem_candidates', []))}</td><td>{'fail' if not r.get('news_status', {}).get('ok', True) else 'ok'}</td></tr>"
        for r in reversed(history[-30:])
    )
    news_status = latest.get("news_status", {})
    news_ok = bool(news_status.get("ok", True))
    news_error = news_status.get("error") or "None"
    signal_policy = latest.get("signal_policy", {})
    signal_policy_rows = "".join(
        f"<li>{key}: {value}</li>" for key, value in signal_policy.items() if value not in (None, [], {})
    )
    ai_output = latest.get("ai_output", [])
    ai_output_rows = "".join(
      f"<tr><td>{item['symbol']}</td><td>{item['action']}</td><td>{item['confidence']}</td><td>{item['rationale']}</td></tr>"
      for item in ai_output
    )

    html = f"""<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>AIStock Dashboard</title>
  <style>
    :root {{ --bg:#0f172a; --card:#111827; --text:#e5e7eb; --muted:#9ca3af; --ok:#22c55e; --bad:#ef4444; --accent:#93c5fd; }}
    body {{ margin:0; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif; background: radial-gradient(circle at top, #1f2937, #020617 60%); color:var(--text); }}
    .wrap {{ max-width: 1100px; margin: 0 auto; padding: 24px; }}
    .grid {{ display:grid; grid-template-columns: repeat(auto-fit,minmax(220px,1fr)); gap:12px; }}
    .card {{ background:rgba(17,24,39,.9); border:1px solid #374151; border-radius:14px; padding:14px; }}
    .label {{ color:var(--muted); font-size:12px; }}
    .value {{ font-size:22px; font-weight:700; }}
    table {{ width:100%; border-collapse: collapse; }}
    th, td {{ border-bottom:1px solid #374151; text-align:left; padding:8px; font-size:13px; }}
    th {{ color:var(--accent); }}
    ul {{ margin: 8px 0 0 18px; }}
    .status-ok {{ color: var(--ok); }}
    .status-bad {{ color: var(--bad); }}
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
      <div class="card"><div class="label">AI Outputs</div><div class="value">{len(ai_output)}</div></div>
      <div class=\"card\"><div class=\"label\">Hidden Gems</div><div class=\"value\">{len(latest.get('hidden_gem_candidates', []))}</div></div>
      <div class=\"card\"><div class=\"label\">News Status</div><div class=\"value {'status-ok' if news_ok else 'status-bad'}\">{'OK' if news_ok else 'FAIL'}</div></div>
    </div>

    <h2>Symbols Scanned This Cycle</h2>
    <div class=\"card\">
      <ul>{scanned_rows or '<li>No symbols scanned</li>'}</ul>
    </div>

    <h2>Current Positions</h2>
    <div class=\"card\">
      <table>
        <thead><tr><th>Symbol</th><th>Qty</th><th>Avg Cost</th></tr></thead>
        <tbody>{''.join(f'<tr><td>{p["symbol"]}</td><td>{p["quantity"]}</td><td>${p["avg_cost"]}</td></tr>' for p in latest_positions) or '<tr><td colspan="3">No positions</td></tr>'}</tbody>
      </table>
    </div>

    <h2>New Buys vs Carried Positions</h2>
    <div class=\"grid\">
      <div class=\"card\">
        <h3>New Buys</h3>
        <table>
          <thead><tr><th>Symbol</th><th>Qty</th><th>Avg Cost</th></tr></thead>
          <tbody>{new_buy_rows or '<tr><td colspan="3">No new buys</td></tr>'}</tbody>
        </table>
      </div>
      <div class=\"card\">
        <h3>Carried Positions</h3>
        <table>
          <thead><tr><th>Symbol</th><th>Qty</th><th>Avg Cost</th></tr></thead>
          <tbody>{carried_rows or '<tr><td colspan="3">No carried positions</td></tr>'}</tbody>
        </table>
      </div>
    </div>

    <h2>Hidden-Gem Candidates</h2>
    <div class=\"card\">
      <table>
        <thead><tr><th>Symbol</th><th>Confidence</th><th>Reason</th></tr></thead>
        <tbody>{hidden_rows or '<tr><td colspan="3">No hidden gems this cycle</td></tr>'}</tbody>
      </table>
    </div>

    <h2>AI Output From Last Cycle</h2>
    <div class="card">
      <table>
        <thead><tr><th>Symbol</th><th>Action</th><th>Confidence</th><th>Rationale</th></tr></thead>
        <tbody>{ai_output_rows or '<tr><td colspan="4">No AI outputs were produced</td></tr>'}</tbody>
      </table>
    </div>

    <h2>Signal Performance</h2>
    <div class=\"card\">
      <table>
        <thead><tr><th>Family</th><th>Trades</th><th>Win Rate</th><th>Avg Return</th><th>Avg Confidence</th><th>Status</th></tr></thead>
        <tbody>{signal_rows or '<tr><td colspan="6">No signal history yet</td></tr>'}</tbody>
      </table>
      <h3>Underperformers</h3>
      <table>
        <thead><tr><th>Family</th><th>Trades</th><th>Win Rate</th><th>Avg Return</th></tr></thead>
        <tbody>{underperformer_rows or '<tr><td colspan="4">No signals are underperforming</td></tr>'}</tbody>
      </table>
    </div>

    <h2>Signal Policy Used for Next Cycle</h2>
    <div class=\"card\">
      <ul>{signal_policy_rows or '<li>No signal policy available yet</li>'}</ul>
    </div>

    <h2>News Health</h2>
    <div class=\"card\">
      <p class="{'status-ok' if news_ok else 'status-bad'}">{'News feed healthy' if news_ok else 'News feed failing or degraded'}</p>
      <p><strong>Fallback used:</strong> {news_status.get('fallback_used', False)}</p>
      <p><strong>Error:</strong> {news_error}</p>
    </div>

    <h2>Recent Cycles</h2>
    <div class=\"card\">
      <table>
        <thead><tr><th>Timestamp</th><th>Equity</th><th>Delta</th><th>Fills</th><th>Hidden Gems</th><th>News</th></tr></thead>
        <tbody>{recent_rows or '<tr><td colspan="6">No cycles yet</td></tr>'}</tbody>
      </table>
    </div>
  </div>
</body>
</html>
"""

    (data_dir / "dashboard.html").write_text(html, encoding="utf-8")
