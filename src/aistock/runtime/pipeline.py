from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from aistock.broker.paper_broker import PaperBroker
from aistock.core.config import settings
from aistock.core.tz import is_market_open
from aistock.core.types import AiSignal, NewsItem, TradeDecision
from aistock.integrations.ai.hackclub import HackclubAiProvider
from aistock.integrations.ai.mock import MockAiProvider
from aistock.integrations.market.yfinance_provider import YFinanceProvider
from aistock.integrations.news.hackclub import HackclubSearchNewsProvider
from aistock.integrations.news.mock import MockNewsProvider
from aistock.integrations.news.rss_provider import RSSNewsProvider
from aistock.risk.engine import size_trade
from aistock.runtime.reporting import read_recent_reports, write_cycle_report
from aistock.runtime.universe import resolve_symbols
from aistock.signals.conventional import conventional_signal
from aistock.signals.ensemble import combine_signals

_HIDDEN_GEM_MIN_CONFIDENCE = 0.8


def _news_cache_path(data_dir: Path) -> Path:
    return data_dir / "news_cache.json"


def _serialize_news(items: list[NewsItem]) -> list[dict[str, Any]]:
    return [
        {
            "symbol": item.symbol,
            "headline": item.headline,
            "source": item.source,
            "summary": item.summary,
            "published_at": item.published_at.isoformat(),
        }
        for item in items
    ]


def _deserialize_news(payload: list[dict[str, Any]]) -> list[NewsItem]:
    items: list[NewsItem] = []
    for row in payload:
        try:
            items.append(
                NewsItem(
                    symbol=str(row.get("symbol", "")).upper(),
                    headline=str(row.get("headline", "")),
                    source=str(row.get("source", "unknown")),
                    summary=str(row.get("summary")) if row.get("summary") is not None else None,
                    published_at=datetime.fromisoformat(str(row.get("published_at"))),
                )
            )
        except (TypeError, ValueError):
            continue
    return items


def _read_cached_news(data_dir: Path) -> list[NewsItem]:
    cache_path = _news_cache_path(data_dir)
    if not cache_path.exists():
        return []
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError, TypeError):
        return []
    if not isinstance(payload, list):
        return []
    return _deserialize_news(payload)


def _write_cached_news(data_dir: Path, items: list[NewsItem]) -> None:
    if not items:
        return
    cache_path = _news_cache_path(data_dir)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(_serialize_news(items), indent=2), encoding="utf-8")


def _count_statuses(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status", "unknown"))
        counts[status] = counts.get(status, 0) + 1
    return counts


def _build_ai_provider():
    if settings.ai_provider == "hackclub":
        return HackclubAiProvider()
    return MockAiProvider()


def _build_news_provider():
    provider = (settings.news_provider or "").lower()
    if provider == "hackclub":
        return HackclubSearchNewsProvider()
    if provider == "rss":
        return RSSNewsProvider()
    return MockNewsProvider()


def _load_broker_state(state_path: Path) -> PaperBroker:
    if not state_path.exists():
        return PaperBroker(starting_cash=settings.starting_cash)
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError, TypeError):
        return PaperBroker(starting_cash=settings.starting_cash)
    return PaperBroker.from_state(payload, fallback_starting_cash=settings.starting_cash)


def _save_broker_state(state_path: Path, broker: PaperBroker) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(broker.export_state(), indent=2), encoding="utf-8")


def _signal_weights_from_history(history: list[dict]) -> dict[str, float]:
    ai_weight = settings.ai_weight
    conventional_weight = settings.conventional_weight
    disabled: list[str] = []

    latest_history = history[-1] if history else {}
    signal_performance = latest_history.get("signal_performance", {})
    families = signal_performance.get("families", {}) if isinstance(signal_performance, dict) else {}

    for family, weight in (("ai", ai_weight), ("conventional", conventional_weight)):
        family_summary = families.get(family, {}) if isinstance(families, dict) else {}
        status = str(family_summary.get("status", "active"))
        if status == "underperforming":
            if family == "ai":
                ai_weight = 0.0
            else:
                conventional_weight = 0.0
            disabled.append(family)

    if ai_weight + conventional_weight <= 0:
        ai_weight = settings.ai_weight
        conventional_weight = settings.conventional_weight
        disabled = []

    total = ai_weight + conventional_weight
    if total > 0:
        ai_weight /= total
        conventional_weight /= total

    return {
        "ai_weight": ai_weight,
        "conventional_weight": conventional_weight,
        "disabled": disabled,
    }


def _mark_hidden_gems(decisions: list[TradeDecision], symbols: list[str]) -> None:
    core_universe = set(settings.universe_symbols())
    if settings.universe_mode.lower() != "auto":
        return

    for decision in decisions:
        hidden = (
            decision.action == "BUY"
            and decision.confidence >= _HIDDEN_GEM_MIN_CONFIDENCE
            and decision.symbol not in core_universe
            and decision.symbol in symbols
        )
        decision.is_hidden_gem = hidden
        if hidden:
            decision.hidden_gem_reason = "High-confidence BUY outside the core universe"


def _collect_debug_issues(
    news_count: int,
    ai_signal_count: int,
    news_debug: list[dict[str, Any]],
    ai_debug: list[dict[str, Any]],
    decisions: list[TradeDecision],
    fills: list,
    news_failure: str | None,
    ai_failure: str | None,
    execution_diagnostics: dict[str, Any],
) -> list[str]:
    issues: list[str] = []

    if news_failure:
        issues.append(f"News provider failure: {news_failure}")
    if ai_failure:
        issues.append(f"AI provider failure: {ai_failure}")
    if news_count == 0:
        news_statuses = _count_statuses(news_debug)
        if news_statuses.get("rate_limited", 0) > 0:
            issues.append("No news items fetched for this cycle (rate limited)")
        else:
            issues.append("No news items fetched for this cycle")
    if ai_signal_count == 0:
        if any(str(item.get("status", "")) == "empty_input" for item in ai_debug):
            issues.append("No AI signals returned (AI input had no news items)")
        else:
            issues.append("No AI signals returned")

    news_errors = [item for item in news_debug if str(item.get("status", "")) != "ok"]
    if news_errors:
        error_counts = _count_statuses(news_errors)
        counts_str = ", ".join(f"{k}={v}" for k, v in sorted(error_counts.items()))
        issues.append(f"News provider errors for {len(news_errors)} symbol(s): {counts_str}")

    ai_errors = [item for item in ai_debug if str(item.get("status", "")) != "ok"]
    if ai_errors:
        issues.append(f"AI provider errors for {len(ai_errors)} symbol(s)")

    if decisions and all(d.action == "HOLD" for d in decisions):
        issues.append("All decisions were HOLD")
    if decisions and all(d.quantity == 0 for d in decisions):
        sized_zero_reasons = execution_diagnostics.get("sized_zero_reasons", {})
        if isinstance(sized_zero_reasons, dict) and sized_zero_reasons:
            counts_str = ", ".join(f"{k}={v}" for k, v in sorted(sized_zero_reasons.items()))
            issues.append(f"All sized quantities were 0 ({counts_str})")
        else:
            issues.append("All sized quantities were 0")
    if not fills:
        executable_orders = int(execution_diagnostics.get("executable_orders", 0) or 0)
        if executable_orders > 0:
            issues.append("No fills were executed")
        else:
            issues.append("No fills were executed (informational: no executable orders)")

    return issues


def run_one_cycle(broker: PaperBroker | None = None) -> dict:
    data_dir = Path(settings.data_dir)
    broker_state_path = data_dir / "broker_state.json"
    broker = broker or _load_broker_state(broker_state_path)

    recent_reports = read_recent_reports(data_dir, limit=settings.dashboard_history_limit)
    signal_policy = _signal_weights_from_history(recent_reports)

    ai_provider = _build_ai_provider()
    news_provider = _build_news_provider()
    market = YFinanceProvider()

    symbols = resolve_symbols(settings=settings, market=market, data_dir=data_dir)
    news_failure: str | None = None
    ai_failure: str | None = None
    news_fallback_used = False
    news_cache_fallback_used = False
    news_raw_output: list[dict[str, Any]] = []
    try:
        news = news_provider.fetch_news(symbols)
        if hasattr(news_provider, "last_debug"):
            maybe_debug = getattr(news_provider, "last_debug")
            if isinstance(maybe_debug, list):
                news_raw_output = maybe_debug
        rate_limited = any(str(item.get("status", "")) == "rate_limited" for item in news_raw_output)
        if rate_limited and not news:
            cached_news = _read_cached_news(data_dir)
            if cached_news:
                news = cached_news
                news_fallback_used = True
                news_cache_fallback_used = True
                news_raw_output.append(
                    {
                        "symbol": "*",
                        "status": "cache_fallback",
                        "http_status": None,
                        "result_count": len(cached_news),
                        "error": "Used cached news after rate limit",
                        "raw_response": None,
                    }
                )
    except Exception as exc:
        news_failure = f"{type(exc).__name__}: {exc}"
        news_fallback_used = True
        news = MockNewsProvider().fetch_news(symbols)

    if news and not news_cache_fallback_used:
        _write_cached_news(data_dir, news)

    try:
        ai_signals = ai_provider.score_news(news)
    except Exception as exc:
        ai_signals = []
        ai_failure = f"{type(exc).__name__}: {exc}"

    ai_raw_output: list[dict[str, Any]] = []
    if hasattr(ai_provider, "last_debug"):
        maybe_debug = getattr(ai_provider, "last_debug")
        if isinstance(maybe_debug, list):
            ai_raw_output = maybe_debug

    ai_by_symbol: dict[str, AiSignal] = {s.symbol: s for s in ai_signals}
    decisions: list[TradeDecision] = []
    prices: dict[str, float] = {}
    sized_zero_reasons: dict[str, int] = defaultdict(int)
    blocked_by_market_hours = 0

    for symbol in symbols:
        try:
            closes = market.closes(symbol, days=30)
            px = market.latest_price(symbol)
        except Exception:
            continue

        conventional = conventional_signal(symbol, closes)
        ai = ai_by_symbol.get(symbol, AiSignal(symbol=symbol, action="HOLD", confidence=0.5, rationale="No AI signal"))
        decision = combine_signals(
            ai=ai,
            conventional=conventional,
            ai_weight=signal_policy["ai_weight"],
            conventional_weight=signal_policy["conventional_weight"],
        )

        # Enforce stop-loss / take-profit for held positions
        try:
            holding = getattr(broker, "_positions", {}).get(symbol)
            if holding and getattr(holding, "quantity", 0) > 0:
                avg_cost = float(getattr(holding, "avg_cost", 0.0) or 0.0)
                if avg_cost > 0:
                    unrealized_pct = (px - avg_cost) / avg_cost
                    if unrealized_pct <= -settings.stop_loss_pct:
                        decision.action = "SELL"
                        decision.reason = f"stop_loss triggered ({unrealized_pct:.3f})"
                        decision.confidence = max(decision.confidence, 0.9)
                    elif unrealized_pct >= settings.take_profit_pct:
                        decision.action = "SELL"
                        decision.reason = f"take_profit triggered ({unrealized_pct:.3f})"
                        decision.confidence = max(decision.confidence, 0.75)
        except Exception:
            # best-effort; don't fail the cycle on stop-loss checks
            pass

        prices[symbol] = px
        pre_size_cash = broker.cash
        sized = size_trade(
            decision=decision,
            latest_price=px,
            cash=broker.cash,
            max_allocation_per_trade=settings.max_allocation_per_trade,
        )
        if sized.quantity == 0:
            if sized.action != "BUY":
                sized_zero_reasons["non_buy_action"] += 1
            else:
                budget = pre_size_cash * settings.max_allocation_per_trade
                if px <= 0:
                    sized_zero_reasons["invalid_price"] += 1
                elif budget < px:
                    sized_zero_reasons["insufficient_budget"] += 1
                else:
                    sized_zero_reasons["truncated_to_zero"] += 1
        decisions.append(sized)

    fills = []
    executable_orders = 0
    failed_orders: list[dict[str, Any]] = []
    held_quantities = defaultdict(int)
    snapshot = broker.snapshot(prices)
    for pos in snapshot.positions:
        held_quantities[pos.symbol] = pos.quantity

    for d in decisions:
        if d.action == "BUY":
            if d.quantity > 0:
                # If enabled, block BUYs executed outside market hours
                if settings.buy_only_during_market_hours and not is_market_open(
                    None,
                    tz_name=settings.display_timezone,
                    open_hhmm=settings.market_open_hhmm,
                    close_hhmm=settings.market_close_hhmm,
                ):
                    blocked_by_market_hours += 1
                    failed_orders.append(
                        {
                            "symbol": d.symbol,
                            "action": d.action,
                            "quantity": d.quantity,
                            "reason": "outside_market_hours",
                        }
                    )
                else:
                    executable_orders += 1
                    fill = broker.buy(d.symbol, d.quantity, prices[d.symbol])
                    if fill:
                        fills.append(fill)
                    elif d.quantity > 0:
                        failed_orders.append(
                            {
                                "symbol": d.symbol,
                                "action": d.action,
                                "quantity": d.quantity,
                                "reason": broker.last_rejection_reason or "unknown",
                            }
                        )
        elif d.action == "SELL":
            qty = held_quantities[d.symbol]
            if qty > 0:
                executable_orders += 1
                fill = broker.sell(d.symbol, qty, prices[d.symbol])
                if fill:
                    fills.append(fill)
                else:
                    failed_orders.append(
                        {
                            "symbol": d.symbol,
                            "action": d.action,
                            "quantity": qty,
                            "reason": broker.last_rejection_reason or "unknown",
                        }
                    )

    ending = broker.snapshot(prices)

    _mark_hidden_gems(decisions, symbols)
    execution_diagnostics = {
        "sized_zero_reasons": dict(sized_zero_reasons),
        "executable_orders": executable_orders,
        "failed_orders": failed_orders,
        "blocked_by_market_hours": blocked_by_market_hours,
    }
    news_error_counts = _count_statuses([item for item in news_raw_output if str(item.get("status", "")) != "ok"])
    debug_issues = _collect_debug_issues(
        news_count=len(news),
        ai_signal_count=len(ai_signals),
        news_debug=news_raw_output,
        ai_debug=ai_raw_output,
        decisions=decisions,
        fills=fills,
        news_failure=news_failure,
        ai_failure=ai_failure,
        execution_diagnostics=execution_diagnostics,
    )

    recent = read_recent_reports(data_dir, limit=1)
    previous_equity = None
    if recent:
        previous_equity = float(recent[-1].get("equity", 0.0))

    cycle_report = write_cycle_report(
        data_dir=data_dir,
        symbols_scanned=symbols,
        decisions=decisions,
        fills=fills,
        portfolio=ending,
        ai_output=ai_signals,
        ai_raw_output=ai_raw_output,
        market_prices=prices,
        previous_equity=previous_equity,
        previous_positions=snapshot.positions,
        news_status={
            "ok": news_failure is None,
            "fallback_used": news_fallback_used,
            "cache_fallback_used": news_cache_fallback_used,
            "error": news_failure,
            "provider": settings.news_provider,
            "raw_output": news_raw_output,
            "error_counts": news_error_counts,
        },
        news_items=news,
        ai_status={
            "ok": ai_failure is None,
            "error": ai_failure,
            "provider": settings.ai_provider,
        },
        execution_diagnostics=execution_diagnostics,
        signal_policy=signal_policy,
        debug_issues=debug_issues,
        history_limit=settings.dashboard_history_limit,
    )

    _save_broker_state(broker_state_path, broker)

    return {
        "symbols": symbols,
        "decisions": decisions,
        "fills": fills,
        "portfolio": ending,
        "prices": prices,
        "cycle_report": cycle_report,
    }
