from __future__ import annotations

from abc import ABC, abstractmethod

from typing import Any

from aistock.core.types import AiSignal, NewsItem


class AiProvider(ABC):
    @abstractmethod
    def score_news(self, news: list[NewsItem], trends: dict[str, dict[str, Any]] | None = None) -> list[AiSignal]:
        """Score news items and optionally use `trends` (market indicators) keyed by symbol.

        `trends` is a mapping from symbol to a small dict of computed indicators
        (e.g. ma5, ma20, momentum_5d, momentum_20d).
        """
        raise NotImplementedError
