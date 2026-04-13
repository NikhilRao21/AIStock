from __future__ import annotations

from abc import ABC, abstractmethod


class MarketDataProvider(ABC):
    @abstractmethod
    def latest_price(self, symbol: str) -> float:
        raise NotImplementedError

    @abstractmethod
    def closes(self, symbol: str, days: int = 30) -> list[float]:
        raise NotImplementedError
