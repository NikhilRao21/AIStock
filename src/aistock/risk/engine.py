from __future__ import annotations

from aistock.core.types import TradeDecision


def size_trade(
    decision: TradeDecision,
    latest_price: float,
    cash: float,
    max_allocation_per_trade: float,
) -> TradeDecision:
    if decision.action != "BUY":
        return TradeDecision(
            symbol=decision.symbol,
            action=decision.action,
            confidence=decision.confidence,
            quantity=0,
            reason=decision.reason,
            signals=list(decision.signals),
            is_hidden_gem=decision.is_hidden_gem,
            hidden_gem_reason=decision.hidden_gem_reason,
        )

    budget = cash * max_allocation_per_trade
    qty = int(budget // latest_price)
    return TradeDecision(
        symbol=decision.symbol,
        action=decision.action,
        confidence=decision.confidence,
        quantity=max(0, qty),
        reason=decision.reason,
        signals=list(decision.signals),
        is_hidden_gem=decision.is_hidden_gem,
        hidden_gem_reason=decision.hidden_gem_reason,
    )
