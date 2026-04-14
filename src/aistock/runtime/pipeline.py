from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path

from aistock.broker.paper_broker import PaperBroker
from aistock.core.config import settings
from aistock.core.types import AiSignal, TradeDecision
from aistock.integrations.ai.hackclub import HackclubAiProvider
from aistock.integrations.ai.mock import MockAiProvider
from aistock.integrations.market.yfinance_provider import YFinanceProvider
from aistock.integrations.news.hackclub import HackclubSearchNewsProvider
from aistock.integrations.news.mock import MockNewsProvider
from aistock.risk.engine import size_trade
from aistock.runtime.reporting import read_recent_reports, write_cycle_report
from aistock.runtime.universe import resolve_symbols
from aistock.signals.conventional import conventional_signal
from aistock.signals.ensemble import combine_signals


def _build_ai_provider():
    if settings.ai_provider == "hackclub":
        return HackclubAiProvider()
    return MockAiProvider()


def _build_news_provider():
    if settings.news_provider == "hackclub":
        return HackclubSearchNewsProvider()
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


def run_one_cycle(broker: PaperBroker | None = None) -> dict:
    data_dir = Path(settings.data_dir)
    broker_state_path = data_dir / "broker_state.json"
    broker = broker or _load_broker_state(broker_state_path)

    ai_provider = _build_ai_provider()
    news_provider = _build_news_provider()
    market = YFinanceProvider()

    symbols = resolve_symbols(settings=settings, market=market, data_dir=data_dir)
    try:
        news = news_provider.fetch_news(symbols)
    except Exception:
        news = MockNewsProvider().fetch_news(symbols)

    ai_signals = ai_provider.score_news(news)

    ai_by_symbol: dict[str, AiSignal] = {s.symbol: s for s in ai_signals}
    decisions: list[TradeDecision] = []
    prices: dict[str, float] = {}

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
            ai_weight=settings.ai_weight,
            conventional_weight=settings.conventional_weight,
        )

        prices[symbol] = px
        sized = size_trade(
            decision=decision,
            latest_price=px,
            cash=broker.cash,
            max_allocation_per_trade=settings.max_allocation_per_trade,
        )
        decisions.append(sized)

    fills = []
    held_quantities = defaultdict(int)
    snapshot = broker.snapshot(prices)
    for pos in snapshot.positions:
        held_quantities[pos.symbol] = pos.quantity

    for d in decisions:
        if d.action == "BUY":
            fill = broker.buy(d.symbol, d.quantity, prices[d.symbol])
            if fill:
                fills.append(fill)
        elif d.action == "SELL":
            qty = held_quantities[d.symbol]
            if qty > 0:
                fill = broker.sell(d.symbol, qty, prices[d.symbol])
                if fill:
                    fills.append(fill)

    ending = broker.snapshot(prices)

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
        previous_equity=previous_equity,
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
