from __future__ import annotations

from abc import ABC, abstractmethod

from aistock.core.types import NewsItem


class NewsProvider(ABC):
    @abstractmethod
    def fetch_news(self, symbols: list[str], per_symbol: int = 5) -> list[NewsItem]:
        raise NotImplementedError
