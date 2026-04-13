from __future__ import annotations

from collections import defaultdict

from aistock.broker.paper_broker import PaperBroker
from aistock.core.config import settings
from aistock.core.types import AiSignal, TradeDecision
from aistock.integrations.ai.hackclub import HackclubAiProvider
from aistock.integrations.ai.mock import MockAiProvider
from aistock.integrations.market.yfinance_provider import YFinanceProvider
from aistock.integrations.news.hackclub import HackclubSearchNewsProvider
from aistock.integrations.news.mock import MockNewsProvider
from aistock.risk.engine import size_trade
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


def run_one_cycle(broker: PaperBroker | None = None) -> dict:
    broker = broker or PaperBroker(starting_cash=settings.starting_cash)

    ai_provider = _build_ai_provider()
    news_provider = _build_news_provider()
    market = YFinanceProvider()

    symbols = settings.universe_symbols()
    news = news_provider.fetch_news(symbols)
    ai_signals = ai_provider.score_news(news)

    ai_by_symbol: dict[str, AiSignal] = {s.symbol: s for s in ai_signals}
    decisions: list[TradeDecision] = []
    prices: dict[str, float] = {}

    for symbol in symbols:
        closes = market.closes(symbol, days=30)
        conventional = conventional_signal(symbol, closes)
        ai = ai_by_symbol.get(symbol, AiSignal(symbol=symbol, action="HOLD", confidence=0.5, rationale="No AI signal"))
        decision = combine_signals(
            ai=ai,
            conventional=conventional,
            ai_weight=settings.ai_weight,
            conventional_weight=settings.conventional_weight,
        )

        px = market.latest_price(symbol)
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
    return {
        "decisions": decisions,
        "fills": fills,
        "portfolio": ending,
        "prices": prices,
    }
