from __future__ import annotations

from dataclasses import dataclass

from aistock.broker.interface import Broker
from aistock.core.types import Fill, PortfolioSnapshot, Position


@dataclass(slots=True)
class _Holding:
    quantity: int
    avg_cost: float


class PaperBroker(Broker):
    def __init__(self, starting_cash: float, fee_bps: float = 5.0) -> None:
        self.cash = starting_cash
        self.fee_bps = fee_bps
        self._positions: dict[str, _Holding] = {}

    def buy(self, symbol: str, quantity: int, price: float) -> Fill | None:
        if quantity <= 0:
            return None
        gross = quantity * price
        fee = gross * (self.fee_bps / 10_000)
        cost = gross + fee
        if cost > self.cash:
            return None

        self.cash -= cost
        old = self._positions.get(symbol)
        if old is None:
            self._positions[symbol] = _Holding(quantity=quantity, avg_cost=price)
        else:
            new_qty = old.quantity + quantity
            old_cost = old.avg_cost * old.quantity
            self._positions[symbol] = _Holding(quantity=new_qty, avg_cost=(old_cost + gross) / new_qty)
        return Fill(symbol=symbol, action="BUY", quantity=quantity, fill_price=price, fee=fee)

    def sell(self, symbol: str, quantity: int, price: float) -> Fill | None:
        if quantity <= 0:
            return None
        old = self._positions.get(symbol)
        if old is None or old.quantity <= 0:
            return None

        qty = min(quantity, old.quantity)
        gross = qty * price
        fee = gross * (self.fee_bps / 10_000)
        self.cash += gross - fee

        remain = old.quantity - qty
        if remain == 0:
            self._positions.pop(symbol, None)
        else:
            self._positions[symbol] = _Holding(quantity=remain, avg_cost=old.avg_cost)

        return Fill(symbol=symbol, action="SELL", quantity=qty, fill_price=price, fee=fee)

    def snapshot(self, market_prices: dict[str, float]) -> PortfolioSnapshot:
        positions: list[Position] = []
        equity = self.cash
        for symbol, h in self._positions.items():
            positions.append(Position(symbol=symbol, quantity=h.quantity, avg_cost=h.avg_cost))
            equity += h.quantity * market_prices.get(symbol, h.avg_cost)
        return PortfolioSnapshot(cash=self.cash, equity=equity, positions=positions)
