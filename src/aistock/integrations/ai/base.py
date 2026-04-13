from __future__ import annotations

from abc import ABC, abstractmethod

from aistock.core.types import AiSignal, NewsItem


class AiProvider(ABC):
    @abstractmethod
    def score_news(self, news: list[NewsItem]) -> list[AiSignal]:
        raise NotImplementedError
