from __future__ import annotations

from aistock.core.types import AiSignal, NewsItem
from aistock.integrations.ai.base import AiProvider


class MockAiProvider(AiProvider):
    """Deterministic fallback for local testing when API is unavailable."""

    def score_news(self, news: list[NewsItem]) -> list[AiSignal]:
        scores: dict[str, float] = {}
        for item in news:
            text = f"{item.headline} {item.summary or ''}".lower()
            score = 0.0
            if any(k in text for k in ("beat", "upgrade", "growth", "profit", "record")):
                score += 0.6
            if any(k in text for k in ("miss", "downgrade", "lawsuit", "loss", "fraud")):
                score -= 0.6
            scores[item.symbol] = scores.get(item.symbol, 0.0) + score

        signals: list[AiSignal] = []
        for symbol, val in scores.items():
            if val > 0.25:
                action = "BUY"
            elif val < -0.25:
                action = "SELL"
            else:
                action = "HOLD"
            confidence = min(1.0, 0.5 + abs(val) / 2)
            signals.append(AiSignal(symbol=symbol, action=action, confidence=confidence, rationale="Mock keyword sentiment score"))
        return signals
