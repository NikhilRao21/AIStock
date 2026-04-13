from __future__ import annotations

from abc import ABC, abstractmethod

from aistock.core.types import Fill, PortfolioSnapshot


class Broker(ABC):
    @abstractmethod
    def buy(self, symbol: str, quantity: int, price: float) -> Fill | None:
        raise NotImplementedError

    @abstractmethod
    def sell(self, symbol: str, quantity: int, price: float) -> Fill | None:
        raise NotImplementedError

    @abstractmethod
    def snapshot(self, market_prices: dict[str, float]) -> PortfolioSnapshot:
        raise NotImplementedError
