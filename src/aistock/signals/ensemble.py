from __future__ import annotations

from aistock.core.types import AiSignal, ConventionalSignal, SignalSnapshot, TradeDecision


def _score(action: str, confidence: float) -> float:
    direction = {"BUY": 1.0, "HOLD": 0.0, "SELL": -1.0}.get(action, 0.0)
    return direction * confidence


def combine_signals(
    ai: AiSignal,
    conventional: ConventionalSignal,
    ai_weight: float,
    conventional_weight: float,
) -> TradeDecision:
    total = (_score(ai.action, ai.confidence) * ai_weight) + (
        _score(conventional.action, conventional.confidence) * conventional_weight
    )

    if total > 0.2:
        action = "BUY"
    elif total < -0.2:
        action = "SELL"
    else:
        action = "HOLD"

    confidence = min(1.0, max(0.0, abs(total)))
    reason = (
        f"AI={ai.action}:{ai.confidence:.2f}, "
        f"Conventional={conventional.action}:{conventional.confidence:.2f}, "
        f"score={total:.3f}"
    )
    return TradeDecision(
        symbol=ai.symbol,
        action=action,
        confidence=confidence,
        quantity=0,
        reason=reason,
        signals=[
            SignalSnapshot(
                family="ai",
                action=ai.action,
                confidence=ai.confidence,
                details=ai.rationale,
            ),
            SignalSnapshot(
                family="conventional",
                action=conventional.action,
                confidence=conventional.confidence,
                details=f"momentum_5d={conventional.momentum_5d:.4f}, momentum_20d={conventional.momentum_20d:.4f}",
            ),
        ],
    )
