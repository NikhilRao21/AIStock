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
        self.last_rejection_reason: str | None = None

    def buy(self, symbol: str, quantity: int, price: float) -> Fill | None:
        if quantity <= 0:
            self.last_rejection_reason = "quantity_zero"
            return None
        if price <= 0:
            self.last_rejection_reason = "invalid_price"
            return None
        gross = quantity * price
        fee = gross * (self.fee_bps / 10_000)
        cost = gross + fee
        if cost > self.cash:
            self.last_rejection_reason = "insufficient_cash"
            return None

        self.cash -= cost
        old = self._positions.get(symbol)
        if old is None:
            self._positions[symbol] = _Holding(quantity=quantity, avg_cost=price)
        else:
            new_qty = old.quantity + quantity
            old_cost = old.avg_cost * old.quantity
            self._positions[symbol] = _Holding(quantity=new_qty, avg_cost=(old_cost + gross) / new_qty)
        self.last_rejection_reason = None
        return Fill(symbol=symbol, action="BUY", quantity=quantity, fill_price=price, fee=fee)

    def sell(self, symbol: str, quantity: int, price: float) -> Fill | None:
        if quantity <= 0:
            self.last_rejection_reason = "quantity_zero"
            return None
        if price <= 0:
            self.last_rejection_reason = "invalid_price"
            return None
        old = self._positions.get(symbol)
        if old is None or old.quantity <= 0:
            self.last_rejection_reason = "no_position"
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

        self.last_rejection_reason = None
        return Fill(symbol=symbol, action="SELL", quantity=qty, fill_price=price, fee=fee)

    def snapshot(self, market_prices: dict[str, float]) -> PortfolioSnapshot:
        positions: list[Position] = []
        equity = self.cash
        for symbol, h in self._positions.items():
            positions.append(Position(symbol=symbol, quantity=h.quantity, avg_cost=h.avg_cost))
            equity += h.quantity * market_prices.get(symbol, h.avg_cost)
        return PortfolioSnapshot(cash=self.cash, equity=equity, positions=positions)

    def export_state(self) -> dict:
        return {
            "cash": self.cash,
            "fee_bps": self.fee_bps,
            "positions": {
                symbol: {"quantity": h.quantity, "avg_cost": h.avg_cost}
                for symbol, h in self._positions.items()
            },
        }

    @classmethod
    def from_state(cls, state: dict, fallback_starting_cash: float) -> "PaperBroker":
        broker = cls(
            starting_cash=float(state.get("cash", fallback_starting_cash)),
            fee_bps=float(state.get("fee_bps", 5.0)),
        )
        positions = state.get("positions", {})
        if isinstance(positions, dict):
            for symbol, payload in positions.items():
                if not isinstance(payload, dict):
                    continue
                qty = int(payload.get("quantity", 0))
                avg_cost = float(payload.get("avg_cost", 0.0))
                if qty > 0 and avg_cost >= 0:
                    broker._positions[symbol] = _Holding(quantity=qty, avg_cost=avg_cost)
        return broker
