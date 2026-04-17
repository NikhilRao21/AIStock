from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

from aistock.core.types import AiSignal, Fill, PortfolioSnapshot, Position, TradeDecision
from aistock.core.tz import format_iso_in_tz, format_human_in_tz
from aistock.core.config import settings

_SIGNAL_PERFORMANCE_MIN_TRADES = 5
_SIGNAL_PERFORMANCE_MIN_WIN_RATE = 0.5


def write_cycle_report(
    data_dir: Path,
    symbols_scanned: list[str],
    decisions: list[TradeDecision],
    fills: list[Fill],
    portfolio: PortfolioSnapshot,
    ai_output: list[AiSignal],
    ai_raw_output: list[dict[str, Any]],
    market_prices: dict[str, float],
    previous_equity: float | None,
    previous_positions: list[Position],
    news_status: dict[str, Any] | None,
    news_items: list | None = None,
    ai_status: dict[str, Any] | None = None,
    execution_diagnostics: dict[str, Any] | None = None,
    signal_policy: dict[str, Any] | None = None,
    debug_issues: list[str] | None = None,
    history_limit: int = 50,
) -> dict:
    data_dir.mkdir(parents=True, exist_ok=True)

    if debug_issues is None:
        debug_issues = []

    # Persist program start baseline if missing. This is the baseline equity
    # used to compute running net profit across cycles stored in `data/`.
    program_start_path = data_dir / "program_start.json"
    if program_start_path.exists():
        try:
            program_start = json.loads(program_start_path.read_text(encoding="utf-8"))
            baseline_equity = float(program_start.get("baseline_equity", round(portfolio.equity, 2)))
        except Exception:
            baseline_equity = round(portfolio.equity, 2)
            program_start = {"started_at": format_iso_in_tz(datetime.now(timezone.utc), settings.display_timezone), "baseline_equity": baseline_equity}
    else:
        baseline_equity = round(portfolio.equity, 2)
        program_start = {"started_at": format_iso_in_tz(datetime.now(timezone.utc), settings.display_timezone), "baseline_equity": baseline_equity}
        try:
            program_start_path.write_text(json.dumps(program_start, indent=2), encoding="utf-8")
        except Exception:
            # best-effort write; continue even if write fails
            pass

    history = read_recent_reports(data_dir, history_limit)
    signal_performance = _build_signal_performance(history, market_prices)

    current_positions: list[dict[str, Any]] = []
    for p in portfolio.positions:
        cp = float(market_prices.get(p.symbol, 0.0) or 0.0)
        unrealized = round((cp - p.avg_cost) * p.quantity, 2)
        unrealized_pct = None
        try:
            unrealized_pct = None if not p.avg_cost else round((cp - p.avg_cost) / p.avg_cost * 100.0, 2)
        except Exception:
            unrealized_pct = None
        current_positions.append(
            {
                "symbol": p.symbol,
                "quantity": p.quantity,
                "avg_cost": round(p.avg_cost, 4),
                "current_price": round(cp, 4),
                "unrealized": unrealized,
                "unrealized_pct": unrealized_pct,
            }
        )
    previous_position_symbols = {p.symbol for p in previous_positions}
    current_position_symbols = {p["symbol"] for p in current_positions}

    new_buys = [
        {"symbol": p["symbol"], "quantity": p["quantity"], "avg_cost": p["avg_cost"]}
        for p in current_positions
        if p["symbol"] not in previous_position_symbols
    ]
    carried_positions = [
        {"symbol": p["symbol"], "quantity": p["quantity"], "avg_cost": p["avg_cost"]}
        for p in current_positions
        if p["symbol"] in previous_position_symbols
    ]
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

    ai_raw_rows = [
        {
            "symbol": str(item.get("symbol", "")),
            "status": str(item.get("status", "unknown")),
            "http_status": item.get("http_status"),
            "error": str(item.get("error", "")) if item.get("error") else None,
            "parsed": item.get("parsed"),
            "extracted_content": str(item.get("extracted_content", "")) if item.get("extracted_content") else None,
            "raw_response": str(item.get("raw_response", ""))[:5000] if item.get("raw_response") else None,
        }
        for item in ai_raw_output
    ]

    now_utc = datetime.now(timezone.utc)
    report = {
        "timestamp": now_utc.isoformat(),
        "timestamp_et": format_iso_in_tz(now_utc, settings.display_timezone),
        "timestamp_human": format_human_in_tz(now_utc, settings.display_timezone),
        "program_start": program_start,
        "net_profit": round(portfolio.equity - baseline_equity, 2),
        "net_profit_pct": None if baseline_equity == 0 else round((portfolio.equity - baseline_equity) / baseline_equity * 100.0, 2),
        "symbols_scanned": symbols_scanned,
        "decision_count": len(decisions),
        "fill_count": len(fills),
        "equity": round(portfolio.equity, 2),
        "cash": round(portfolio.cash, 2),
        "equity_delta": None if previous_equity is None else round(portfolio.equity - previous_equity, 2),
        "ai_output": ai_output_rows,
        "ai_output_count": len(ai_output_rows),
        "ai_raw_output": ai_raw_rows,
        "ai_raw_output_count": len(ai_raw_rows),
        "market_prices": {symbol: round(price, 4) for symbol, price in market_prices.items()},
        "positions": current_positions,
        "position_changes": {
            "new_buys": new_buys,
            "carried_positions": carried_positions,
            "closed_positions": closed_positions,
        },
        "hidden_gem_candidates": hidden_gem_candidates,
        "news_status": news_status or {"ok": True, "fallback_used": False, "error": None},
        "news_raw_output_count": len(news_items) if news_items is not None else (len((news_status or {}).get("raw_output", [])) if isinstance(news_status, dict) else 0),
        "news_error_counts": (news_status or {}).get("error_counts", {}) if isinstance(news_status, dict) else {},
        "ai_status": ai_status or {"ok": True, "error": None, "provider": "unknown"},
        "execution_diagnostics": execution_diagnostics or {"sized_zero_reasons": {}, "executable_orders": 0, "failed_orders": []},
        "signal_policy": signal_policy or {"ai_weight": None, "conventional_weight": None, "disabled": []},
        "signal_performance": signal_performance,
        "debug_issues": debug_issues,
        "fills": [
            {
                "timestamp": f.timestamp.isoformat(),
                "timestamp_et": format_iso_in_tz(f.timestamp, settings.display_timezone),
                "timestamp_human": format_human_in_tz(f.timestamp, settings.display_timezone),
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
        "news_items": [
            {
                "symbol": item.symbol,
                "headline": item.headline,
                "source": item.source,
                "summary": item.summary,
                "published_at": item.published_at.isoformat(),
                "url": getattr(item, "url", None),
            }
            for item in (news_items or [])
        ],
    }

    reports_path = data_dir / "cycle_reports.jsonl"
    # Append BUY fills to a persistent purchase log (JSONL)
    purchase_log_path = data_dir / "purchase_log.jsonl"
    if fills:
        try:
            with purchase_log_path.open("a", encoding="utf-8") as plf:
                for f in fills:
                    try:
                        if str(f.action).upper() == "BUY" and (f.quantity or 0) > 0:
                            entry = {
                                "timestamp": f.timestamp.isoformat(),
                                "timestamp_et": format_iso_in_tz(f.timestamp, settings.display_timezone),
                                "symbol": f.symbol,
                                "action": f.action,
                                "quantity": f.quantity,
                                "fill_price": round(f.fill_price, 4),
                                "fee": round(f.fee, 4),
                                "equity": round(portfolio.equity, 2),
                                "timestamp_human": format_human_in_tz(f.timestamp, settings.display_timezone),
                            }
                            plf.write(json.dumps(entry) + "\n")
                    except Exception:
                        # best-effort per-fill
                        continue
        except Exception:
            # best-effort append
            pass

    with reports_path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(report) + "\n")

    latest_path = data_dir / "latest_cycle.json"
    latest_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    # Include recent purchase log entries (last 50) in the latest report
    try:
        purchases: list[dict] = []
        if purchase_log_path.exists():
            with purchase_log_path.open("r", encoding="utf-8") as plf:
                for line in plf:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        purchases.append(json.loads(line))
                    except Exception:
                        continue
        report["purchase_log"] = purchases[-50:]
        # Update latest_cycle.json with purchase_log included
        latest_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    except Exception:
        # best-effort; don't fail the cycle on logging issues
        pass

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
    method_stats: dict[str, dict[str, dict[str, float]]] = defaultdict(lambda: {})

    for idx, report in enumerate(history):
        next_report_prices = {}
        if idx + 1 < len(history):
            maybe_prices = history[idx + 1].get("market_prices")
            if isinstance(maybe_prices, dict):
                next_report_prices = maybe_prices
        fill_index: dict[tuple[str, str, int], dict[str, Any]] = {}
        for decision in report.get("decisions", []):
            fill_index[(
                str(decision.get("symbol", "")),
                str(decision.get("action", "")),
                float(decision.get("quantity", 0) or 0.0),
            )] = decision

        for fill in report.get("fills", []):
            symbol = str(fill.get("symbol", ""))
            action = str(fill.get("action", ""))
            quantity = float(fill.get("quantity", 0) or 0.0)
            fill_price = float(fill.get("fill_price", 0.0) or 0.0)
            if next_report_prices:
                current_price = float(next_report_prices.get(symbol, 0.0) or 0.0)
            else:
                current_price = latest_trade_price.get(symbol)
            if not current_price or fill_price <= 0:
                continue

            outcome = (
                (current_price - fill_price) / fill_price
                if action == "BUY"
                else (fill_price - current_price) / fill_price
            )
            if outcome == 0:
                continue

            decision = fill_index.get((symbol, action, quantity))
            if not decision:
                continue

            for signal in decision.get("signals", []):
                family = str(signal.get("family", "unknown"))
                signal_action = str(signal.get("action", "HOLD")).upper()
                if signal_action == "HOLD":
                    continue
                aligned = (
                    (signal_action == "BUY" and action == "BUY")
                    or (signal_action == "SELL" and action == "SELL")
                )
                signal_outcome = outcome if aligned else -outcome
                stats = family_stats[family]
                stats["trades"] += 1
                stats["wins"] += 1 if signal_outcome > 0 else 0
                stats["return_sum"] += signal_outcome
                stats["confidence_sum"] += float(signal.get("confidence", 0.0) or 0.0)

                # If conventional signal supplies per-method details, aggregate per-method stats
                if family == "conventional":
                    details = signal.get("details")
                    if isinstance(details, dict):
                        per_method = details.get("per_method_scores")
                        if isinstance(per_method, dict):
                            family_methods = method_stats.setdefault(family, {})
                            for method_name, raw_score in per_method.items():
                                try:
                                    method_score = float(raw_score or 0.0)
                                except (TypeError, ValueError):
                                    continue
                                if method_score == 0.0:
                                    continue

                                # Evaluate each method by the direction it implied.
                                # Methods that opposed the executed fill are
                                # attributed inverse outcome, which prevents
                                # identical win rates across all methods.
                                aligned = (
                                    (method_score > 0 and action == "BUY")
                                    or (method_score < 0 and action == "SELL")
                                )
                                method_outcome = outcome if aligned else -outcome
                                m = family_methods.get(method_name)
                                if m is None:
                                    family_methods[method_name] = {"trades": 0.0, "wins": 0.0, "return_sum": 0.0, "confidence_sum": 0.0}
                                    m = family_methods[method_name]
                                m["trades"] += 1
                                m["wins"] += 1 if method_outcome > 0 else 0
                                m["return_sum"] += method_outcome
                                m["confidence_sum"] += float(signal.get("confidence", 0.0) or 0.0)

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
        # attach per-method breakdown if available
        if family in method_stats:
            methods_summary: dict[str, dict[str, float]] = {}
            for method_name, mstats in method_stats[family].items():
                m_trades = int(mstats["trades"])
                if m_trades <= 0:
                    continue
                m_win_rate = mstats["wins"] / m_trades
                m_avg_return = mstats["return_sum"] / m_trades
                m_avg_confidence = mstats["confidence_sum"] / m_trades
                methods_summary[method_name] = {
                    "trades": m_trades,
                    "wins": int(mstats["wins"]),
                    "win_rate": round(m_win_rate, 4),
                    "avg_return": round(m_avg_return, 4),
                    "avg_confidence": round(m_avg_confidence, 4),
                }
            if methods_summary:
                families[family]["methods"] = methods_summary

    return {
        "families": families,
        "underperformers": underperformers,
        "evaluated_trades": sum(item["trades"] for item in families.values()),
    }


def _write_dashboard_html(data_dir: Path, latest: dict, history: list[dict]) -> None:
    latest_positions = latest.get("positions", [])
    position_change = latest.get("position_changes", {})
    debug_issues = latest.get("debug_issues", [])

    new_buy_rows = "".join(
        f"<tr><td>{escape(str(p['symbol']))}</td><td>{p['quantity']}</td><td>${p['avg_cost']}</td></tr>"
        for p in position_change.get("new_buys", [])
    )
    carried_rows = "".join(
        f"<tr><td>{escape(str(p['symbol']))}</td><td>{p['quantity']}</td><td>${p['avg_cost']}</td></tr>"
        for p in position_change.get("carried_positions", [])
    )
    closed_rows = "".join(
        f"<tr><td>{escape(str(p['symbol']))}</td><td>{p['quantity']}</td><td>${p['avg_cost']}</td></tr>"
        for p in position_change.get("closed_positions", [])
    )
    # compact grid for scanned symbols
    scanned_grid = "".join(f"<div class='badge'>{escape(str(symbol))}</div>" for symbol in latest.get("symbols_scanned", []))
    positions_rows = "".join(
        (
            f"<tr>"
            f"<td>{escape(str(p['symbol']))}</td>"
            f"<td class=\"js-qty\">{p['quantity']}</td>"
            f"<td class=\"js-avg\">${p['avg_cost']}</td>"
            f"<td class=\"js-price\" data-symbol=\"{escape(str(p['symbol']))}\">${p.get('current_price','')}</td>"
            f"<td class=\"js-unrealized {'pnl-positive' if (p.get('unrealized', 0) >= 0) else 'pnl-negative'}\">${p.get('unrealized','')}</td>"
            f"<td class=\"{'pnl-positive' if ((p.get('unrealized_pct') or 0) >= 0) else 'pnl-negative'}\">{(str(p.get('unrealized_pct','')) + '%') if p.get('unrealized_pct') is not None else ''}</td>"
            f"</tr>"
        )
        for p in latest_positions
    )
    hidden_rows = "".join(
        f"<tr><td>{escape(str(candidate['symbol']))}</td><td>{candidate['confidence']}</td><td>{escape(str(candidate['reason']))}</td></tr>"
        for candidate in latest.get("hidden_gem_candidates", [])
    )

    signal_rows = "".join(
        f"<tr><td>{escape(str(family))}</td><td>{summary.get('trades', 0)}</td><td>{summary.get('win_rate', 0)}</td><td>{summary.get('avg_return', 0)}</td><td>{summary.get('avg_confidence', 0)}</td><td>{escape(str(summary.get('status', '')))}</td></tr>"
        for family, summary in latest.get("signal_performance", {}).get("families", {}).items()
    )
    underperformer_rows = "".join(
        f"<tr><td>{escape(str(item['family']))}</td><td>{item['trades']}</td><td>{item['win_rate']}</td><td>{item['avg_return']}</td></tr>"
        for item in latest.get("signal_performance", {}).get("underperformers", [])
    )
    # Flatten family->methods metrics so the dashboard can stratify
    # conventional method performance in a dedicated table.
    signal_method_rows = ""
    for family, summary in latest.get("signal_performance", {}).get("families", {}).items():
        methods = summary.get("methods", {}) if isinstance(summary, dict) else {}
        for method_name, method_summary in methods.items():
            signal_method_rows += (
                f"<tr><td>{escape(str(family))}</td><td>{escape(str(method_name))}</td>"
                f"<td>{method_summary.get('trades', 0)}</td><td>{method_summary.get('win_rate', 0)}</td>"
                f"<td>{method_summary.get('avg_return', 0)}</td><td>{method_summary.get('avg_confidence', 0)}</td></tr>"
            )

    ai_output = latest.get("ai_output", [])
    ai_output_rows = "".join(
        f"<tr><td>{escape(str(item['symbol']))}</td><td>{escape(str(item['action']))}</td><td>{item['confidence']}</td><td>{escape(str(item['rationale']))}</td></tr>"
        for item in ai_output
    )

    ai_raw_output = latest.get("ai_raw_output", [])
    ai_raw_rows = "".join(
        "<tr>"
        f"<td>{escape(str(item.get('symbol', '')))}</td>"
        f"<td>{escape(str(item.get('status', '')))}</td>"
        f"<td>{escape(str(item.get('http_status', '')))}</td>"
        f"<td>{escape(str(item.get('error', '') or ''))}</td>"
        f"<td><pre>{escape(str(item.get('raw_response', '') or ''))}</pre></td>"
        "</tr>"
        for item in ai_raw_output
    )

    purchase_rows = "".join(
        f"<tr><td>{escape(str(item.get('timestamp_human', item.get('timestamp_et', item.get('timestamp', '')))))}</td><td>{escape(str(item.get('symbol', '')))}</td><td>{item.get('quantity', '')}</td><td>${item.get('fill_price', '')}</td><td>${item.get('fee', '')}</td><td>${item.get('equity', '')}</td></tr>"
        for item in latest.get('purchase_log', [])
    )
    fills_rows = "".join(
        (
            f"<tr><td>{escape(str(item.get('timestamp_human', item.get('timestamp_et', item.get('timestamp', '')))))}</td>"
            f"<td>{escape(str(item.get('symbol', '')))}</td>"
            f"<td class=\"action-{escape(str(item.get('action', '')).lower())}\">{escape(str(item.get('action', '')))}</td>"
            f"<td>{item.get('quantity', '')}</td><td>${item.get('fill_price', '')}</td><td>${item.get('fee', '')}</td></tr>"
        )
        for item in latest.get("fills", [])
    )

    recent_rows = "".join(
        f"<tr><td>{escape(str(r.get('timestamp_human', r.get('timestamp_et', r.get('timestamp', '')))))}</td><td>{r.get('equity', '')}</td><td>{r.get('equity_delta', '')}</td><td>{r.get('fill_count', '')}</td><td>{len(r.get('hidden_gem_candidates', []))}</td><td>{'fail' if not r.get('news_status', {}).get('ok', True) else 'ok'}</td></tr>"
        for r in reversed(history[-30:])
    )
    equity_history = [float(r.get("equity", 0.0) or 0.0) for r in history[-120:] if r.get("equity") is not None]
    if not equity_history and latest.get("equity") is not None:
        equity_history = [float(latest.get("equity", 0.0) or 0.0)]

    issue_rows = "".join(f"<li>{escape(str(issue))}</li>" for issue in debug_issues)

    news_status = latest.get("news_status", {})
    news_ok = bool(news_status.get("ok", True))
    news_error = news_status.get("error") or "None"
    news_raw_output = news_status.get("raw_output", []) if isinstance(news_status, dict) else []
    news_error_counts = latest.get("news_error_counts", {})
    news_error_count_rows = "".join(
        f"<li>{escape(str(k))}: {escape(str(v))}</li>" for k, v in sorted(news_error_counts.items())
    )

    execution_diagnostics = latest.get("execution_diagnostics", {})
    zero_reason_rows = "".join(
        f"<li>{escape(str(k))}: {escape(str(v))}</li>"
        for k, v in sorted((execution_diagnostics.get("sized_zero_reasons") or {}).items())
    )
    failed_order_rows = "".join(
        f"<tr><td>{escape(str(item.get('symbol', '')))}</td><td>{escape(str(item.get('action', '')))}</td><td>{escape(str(item.get('quantity', '')))}</td><td>{escape(str(item.get('reason', '')))}</td></tr>"
        for item in (execution_diagnostics.get("failed_orders") or [])
    )

    ai_status = latest.get("ai_status", {})
    ai_ok = bool(ai_status.get("ok", True))
    ai_error = ai_status.get("error") or "None"

    news_provider_rows = "".join(
        "<tr>"
        f"<td>{escape(str(item.get('symbol', '')))}</td>"
        f"<td>{escape(str(item.get('status', '')))}</td>"
        f"<td>{escape(str(item.get('http_status', '')))}</td>"
        f"<td>{escape(str(item.get('error', '') or ''))}</td>"
        f"<td><pre>{escape(str(item.get('raw_response', '') or ''))}</pre></td>"
        "</tr>"
        for item in news_raw_output
    )

    signal_policy = latest.get("signal_policy", {})
    signal_policy_rows = "".join(
        f"<li>{escape(str(key))}: {escape(str(value))}</li>"
        for key, value in signal_policy.items()
        if value not in (None, [], {})
    )

    # top news items (from news provider / cache)
    news_items = latest.get("news_items", [])
    news_items_rows = "".join(
        f"<li><strong>{escape(str(item.get('symbol','')))}</strong>: {escape(str(item.get('headline','')))} <span class='small'>({escape(str(item.get('source','')) )})</span></li>"
        for item in (news_items or [])[:50]
    )

    html = f"""<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <meta http-equiv=\"refresh\" content=\"60\" />
  <title>AIStock Dashboard</title>
  <style>
        :root {{ --bg:#071029; --card:#071025; --text:#dfeefe; --muted:#9ca3af; --ok:#22c55e; --bad:#ef4444; --accent:#60a5fa; --glass: rgba(255,255,255,0.03); }}
        body {{ margin:0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial; background: linear-gradient(180deg,#041125 0%,#021021 100%); color:var(--text); -webkit-font-smoothing:antialiased; }}
        .wrap {{ max-width:1200px; margin: 24px auto; padding: 24px; }}
        .grid {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(260px,1fr)); gap:16px; align-items:start; }}
        .card {{ background: linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0.01)); border:1px solid rgba(255,255,255,0.03); border-radius:12px; padding:16px; box-shadow:0 8px 30px rgba(2,6,23,0.6); }}
        .card-header {{ display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:8px; }}
        .label {{ color:var(--muted); font-size:12px; margin:0; }}
        .value {{ font-size:20px; font-weight:700; margin:0; }}
        .status-ok {{ color:var(--ok); background: rgba(34,197,94,0.08); padding:4px 8px; border-radius:999px; font-weight:600; border:1px solid rgba(34,197,94,0.12); display:inline-block; }}
        .status-bad {{ color:var(--bad); background: rgba(239,68,68,0.06); padding:4px 8px; border-radius:999px; font-weight:600; border:1px solid rgba(239,68,68,0.12); display:inline-block; }}
        .card table {{ width:100%; border-collapse: collapse; margin-top:8px; }}
        th, td {{ border-bottom:1px solid rgba(255,255,255,0.04); text-align:left; padding:10px; font-size:13px; vertical-align: top; }}
        th {{ color:var(--accent); font-weight:700; position:sticky; top:0; background: linear-gradient(180deg, rgba(0,0,0,0.04), rgba(0,0,0,0.02)); }}
        ul {{ margin: 8px 0 0 18px; }}
        pre {{ margin:0; white-space: pre-wrap; max-height:280px; overflow:auto; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, 'Roboto Mono', monospace; background: rgba(0,0,0,0.04); padding:8px; border-radius:8px; }}
        .badge {{ display:inline-block; padding:4px 8px; border-radius:999px; font-size:12px; background: rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.03); }}
        .symbols-grid {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(90px,1fr)); gap:8px; align-items:start; }}
        .pnl-positive {{ color:var(--ok); font-weight:700; }}
        .pnl-negative {{ color:var(--bad); font-weight:700; }}
        .action-buy {{ color:var(--ok); font-weight:700; }}
        .action-sell {{ color:var(--bad); font-weight:700; }}
        .action-hold {{ color:var(--muted); font-weight:700; }}
        .small {{ font-size:12px; color:var(--muted); }}
        #equity-chart {{ width: 100%; background: rgba(255,255,255,0.01); border-radius: 8px; }}
  </style>
</head>
<body>
  <div class=\"wrap\">
    <h1>AIStock Cycle Dashboard</h1>
    <p>Updated: {escape(str(latest.get('timestamp_human', latest.get('timestamp_et', latest.get('timestamp', '')))))}</p>

    <div class=\"grid\">
      <div class=\"card\"><div class=\"label\">Portfolio Equity</div><div class=\"value\" id=\"portfolio-equity\">${latest.get('equity', '')}</div></div>
      <div class=\"card\"><div class=\"label\">Cash</div><div class=\"value\">${latest.get('cash', '')}</div></div>
    <div class=\"card\"><div class=\"label\">Equity Change</div><div class=\"value\">{latest.get('equity_delta', 'N/A')}</div></div>
    <div class=\"card\"><div class=\"label\">Net Profit</div><div class=\"value\">${latest.get('net_profit', '')} {('('+str(latest.get('net_profit_pct'))+'%') if latest.get('net_profit_pct') is not None else ''}</div></div>
      <div class=\"card\"><div class=\"label\">Symbols Scanned</div><div class=\"value\">{len(latest.get('symbols_scanned', []))}</div></div>
      <div class=\"card\"><div class=\"label\">AI Outputs</div><div class=\"value\">{len(ai_output)}</div></div>
      <div class=\"card\"><div class=\"label\">Raw AI Responses</div><div class=\"value\">{len(ai_raw_output)}</div></div>
    <div class=\"card\"><div class=\"label\">Raw News Responses</div><div class=\"value\">{len(news_raw_output)}</div></div>
    <div class=\"card\"><div class=\"label\">News Items Matched</div><div class=\"value\">{len(latest.get('news_items', []))}</div></div>
      <div class=\"card\"><div class=\"label\">Hidden Gems</div><div class=\"value\">{len(latest.get('hidden_gem_candidates', []))}</div></div>
      <div class=\"card\"><div class=\"label\">News Status</div><div class=\"value {'status-ok' if news_ok else 'status-bad'}\">{'OK' if news_ok else 'FAIL'}</div></div>
        </div>

        <h2>Top News</h2>
        <div class="card">
            <ul>{news_items_rows or '<li class="small">No recent news items matched this cycle</li>'}</ul>
        </div>

        <h2>Debug Issues</h2>
        <div class="card">
            <ul>{issue_rows or '<li>No issues detected for this cycle</li>'}</ul>
        </div>

    <h2>Symbols Scanned This Cycle</h2>
    <div class=\"card\"><div class=\"symbols-grid\">{scanned_grid or '<div class=\"small\">No symbols scanned</div>'}</div></div>

    <h2>Portfolio Value Over Time</h2>
    <div class=\"card\">
      <canvas id=\"equity-chart\" height=\"100\"></canvas>
    </div>

    <h2>Current Positions</h2>
    <div class=\"card\">
      <table>
        <thead><tr><th>Symbol</th><th>Qty</th><th>Avg Cost</th><th>Price</th><th>P/L</th><th>P/L %</th></tr></thead>
        <tbody>{positions_rows or '<tr><td colspan="6">No positions</td></tr>'}</tbody>
      </table>
    </div>

    <h2>New Buys vs Carried Positions</h2>
    <div class=\"grid\">
      <div class=\"card\">
        <h3>New Buys</h3>
        <table><thead><tr><th>Symbol</th><th>Qty</th><th>Avg Cost</th></tr></thead><tbody>{new_buy_rows or '<tr><td colspan="3">No new buys</td></tr>'}</tbody></table>
      </div>
      <div class=\"card\">
        <h3>Carried Positions</h3>
        <table><thead><tr><th>Symbol</th><th>Qty</th><th>Avg Cost</th></tr></thead><tbody>{carried_rows or '<tr><td colspan="3">No carried positions</td></tr>'}</tbody></table>
      </div>
      <div class=\"card\">
        <h3>Closed Positions (Sells)</h3>
        <table><thead><tr><th>Symbol</th><th>Qty</th><th>Avg Cost</th></tr></thead><tbody>{closed_rows or '<tr><td colspan="3">No closed positions</td></tr>'}</tbody></table>
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
    <div class=\"card\">
      <table>
        <thead><tr><th>Symbol</th><th>Action</th><th>Confidence</th><th>Rationale</th></tr></thead>
        <tbody>{ai_output_rows or '<tr><td colspan="4">No AI outputs were produced</td></tr>'}</tbody>
      </table>
    </div>

        <h2>Raw AI Provider Output</h2>
        <div class=\"card\">
            <details>
                <summary>Raw AI Provider Output (click to expand)</summary>
                <table>
                    <thead><tr><th>Symbol</th><th>Status</th><th>HTTP</th><th>Error</th><th>Raw Response</th></tr></thead>
                    <tbody>{ai_raw_rows or '<tr><td colspan="5">No raw AI output captured</td></tr>'}</tbody>
                </table>
            </details>
        </div>

    <h2>Purchase Log</h2>
    <div class=\"card\">
      <table>
        <thead><tr><th>Time</th><th>Symbol</th><th>Qty</th><th>Price</th><th>Fee</th><th>Equity</th></tr></thead>
        <tbody>{purchase_rows or '<tr><td colspan="6">No purchases logged</td></tr>'}</tbody>
      </table>
    </div>

    <h2>Recent Fills (Buys & Sells)</h2>
    <div class=\"card\">
      <table>
        <thead><tr><th>Time</th><th>Symbol</th><th>Action</th><th>Qty</th><th>Price</th><th>Fee</th></tr></thead>
        <tbody>{fills_rows or '<tr><td colspan="6">No fills this cycle</td></tr>'}</tbody>
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
      <h3>Conventional Method Stratification</h3>
      <table>
        <thead><tr><th>Family</th><th>Method</th><th>Trades</th><th>Win Rate</th><th>Avg Return</th><th>Avg Confidence</th></tr></thead>
        <tbody>{signal_method_rows or '<tr><td colspan="6">No method-level signal stats yet</td></tr>'}</tbody>
      </table>
    </div>

    <h2>Signal Policy Used for Next Cycle</h2>
    <div class=\"card\"><ul>{signal_policy_rows or '<li>No signal policy available yet</li>'}</ul></div>

    <h2>News Health</h2>
    <div class=\"card\">
      <p class=\"{'status-ok' if news_ok else 'status-bad'}\">{'News feed healthy' if news_ok else 'News feed failing or degraded'}</p>
      <p><strong>Fallback used:</strong> {news_status.get('fallback_used', False)}</p>
            <p><strong>Cache fallback used:</strong> {news_status.get('cache_fallback_used', False)}</p>
      <p><strong>Error:</strong> {escape(str(news_error))}</p>
            <p><strong>Error Counts:</strong></p>
            <ul>{news_error_count_rows or '<li>None</li>'}</ul>
    </div>

        <h2>Execution Diagnostics</h2>
        <div class="grid">
            <div class="card">
                <p><strong>Executable orders:</strong> {execution_diagnostics.get('executable_orders', 0)}</p>
                <p><strong>Zero Quantity Reasons:</strong></p>
                <ul>{zero_reason_rows or '<li>None</li>'}</ul>
            </div>
            <div class="card">
                <h3>Failed Orders</h3>
                <table>
                    <thead><tr><th>Symbol</th><th>Action</th><th>Qty</th><th>Reason</th></tr></thead>
                    <tbody>{failed_order_rows or '<tr><td colspan="4">No failed executable orders</td></tr>'}</tbody>
                </table>
            </div>
        </div>

        <h2>Provider Diagnostics</h2>
        <div class=\"grid\">
            <div class=\"card\">
                <h3>AI Provider</h3>
                <p><strong>Provider:</strong> {escape(str(ai_status.get('provider', 'unknown')))}</p>
                <p class=\"{'status-ok' if ai_ok else 'status-bad'}\">{'Healthy' if ai_ok else 'Failing'}</p>
                <p><strong>Error:</strong> {escape(str(ai_error))}</p>
            </div>
                        <div class=\"card\"> 
                                <h3>News Provider Raw Output</h3>
                                <details>
                                    <summary>Raw News Provider Output (click to expand)</summary>
                                    <table>
                                        <thead><tr><th>Symbol</th><th>Status</th><th>HTTP</th><th>Error</th><th>Raw Response</th></tr></thead>
                                        <tbody>{news_provider_rows or '<tr><td colspan="5">No raw news output captured</td></tr>'}</tbody>
                                    </table>
                                </details>
                        </div>
        </div>

    <h2>Recent Cycles</h2>
    <div class=\"card\">
      <table>
        <thead><tr><th>Timestamp</th><th>Equity</th><th>Delta</th><th>Fills</th><th>Hidden Gems</th><th>News</th></tr></thead>
        <tbody>{recent_rows or '<tr><td colspan="6">No cycles yet</td></tr>'}</tbody>
      </table>
    </div>
  </div>
  <script>
    const equitySeries = {json.dumps(equity_history)};

    function drawEquityChart() {{
      const canvas = document.getElementById('equity-chart');
      if (!canvas || !equitySeries.length) return;
      const ctx = canvas.getContext('2d');
      const width = canvas.width = canvas.clientWidth * (window.devicePixelRatio || 1);
      const height = canvas.height = 260 * (window.devicePixelRatio || 1);
      ctx.clearRect(0, 0, width, height);
      const min = Math.min(...equitySeries);
      const max = Math.max(...equitySeries);
      const span = Math.max(1e-6, max - min);
      ctx.lineWidth = 2 * (window.devicePixelRatio || 1);
      ctx.strokeStyle = '#60a5fa';
      ctx.beginPath();
      equitySeries.forEach((value, idx) => {{
        const x = (idx / Math.max(1, equitySeries.length - 1)) * (width - 24) + 12;
        const y = height - (((value - min) / span) * (height - 24) + 12);
        if (idx === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }});
      ctx.stroke();
    }}

    function updateLivePrices() {{
      fetch('/api/live-prices')
        .then((r) => r.ok ? r.json() : Promise.reject(new Error('live price request failed')))
        .then((payload) => {{
          const prices = payload.prices || {{}};
          let liveEquity = Number(payload.cash || 0);
          document.querySelectorAll('.js-price').forEach((cell) => {{
            const symbol = cell.getAttribute('data-symbol');
            const price = Number(prices[symbol]);
            if (!Number.isFinite(price) || price <= 0) return;
            cell.textContent = '$' + price.toFixed(4);
            const row = cell.closest('tr');
            const qty = Number((row?.querySelector('.js-qty')?.textContent || '0').replace(/[^0-9.-]/g, ''));
            const avg = Number((row?.querySelector('.js-avg')?.textContent || '0').replace(/[^0-9.-]/g, ''));
            const pnlCell = row?.querySelector('.js-unrealized');
            if (Number.isFinite(qty) && Number.isFinite(avg) && pnlCell) {{
              const unrealized = (price - avg) * qty;
              pnlCell.textContent = '$' + unrealized.toFixed(2);
              pnlCell.classList.toggle('pnl-positive', unrealized >= 0);
              pnlCell.classList.toggle('pnl-negative', unrealized < 0);
              liveEquity += price * qty;
            }}
          }});
          const equityNode = document.getElementById('portfolio-equity');
          if (equityNode) {{
            equityNode.textContent = '$' + liveEquity.toFixed(2);
          }}
          if (Number.isFinite(liveEquity) && liveEquity > 0) {{
            equitySeries.push(liveEquity);
            if (equitySeries.length > 240) equitySeries.shift();
            drawEquityChart();
          }}
        }})
        .catch(() => {{}});
    }}

    drawEquityChart();
    updateLivePrices();
    setInterval(updateLivePrices, 60000);
    window.addEventListener('resize', drawEquityChart);
  </script>
</body>
</html>
"""

    (data_dir / "dashboard.html").write_text(html, encoding="utf-8")
