from __future__ import annotations

from aistock.core.types import ConventionalSignal


def conventional_signal(symbol: str, closes: list[float]) -> ConventionalSignal:
    if len(closes) < 21:
        raise ValueError(f"Need at least 21 closes for {symbol}")

    last = closes[-1]
    mom_5 = (last / closes[-6]) - 1.0
    mom_20 = (last / closes[-21]) - 1.0

    combined = 0.7 * mom_5 + 0.3 * mom_20
    if combined > 0.01:
        action = "BUY"
    elif combined < -0.01:
        action = "SELL"
    else:
        action = "HOLD"

    confidence = min(1.0, 0.5 + abs(combined) * 10)
    return ConventionalSignal(
        symbol=symbol,
        action=action,
        confidence=confidence,
        momentum_5d=mom_5,
        momentum_20d=mom_20,
    )
