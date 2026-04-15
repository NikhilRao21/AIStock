from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Any

Action = Literal["BUY", "SELL", "HOLD"]


@dataclass(slots=True)
class NewsItem:
    symbol: str
    headline: str
    source: str
    published_at: datetime
    summary: str | None = None
    url: str | None = None


@dataclass(slots=True)
class AiSignal:
    symbol: str
    action: Action
    confidence: float
    rationale: str


@dataclass(slots=True)
class ConventionalSignal:
    symbol: str
    action: Action
    confidence: float
    momentum_5d: float
    momentum_20d: float
    details: Any = field(default_factory=dict)


@dataclass(slots=True)
class SignalSnapshot:
    family: str
    action: Action
    confidence: float
    details: Any = ""


@dataclass(slots=True)
class TradeDecision:
    symbol: str
    action: Action
    confidence: float
    quantity: float
    reason: str
    signals: list[SignalSnapshot] = field(default_factory=list)
    is_hidden_gem: bool = False
    hidden_gem_reason: str | None = None


@dataclass(slots=True)
class Position:
    symbol: str
    quantity: float
    avg_cost: float


@dataclass(slots=True)
class Fill:
    symbol: str
    action: Action
    quantity: float
    fill_price: float
    fee: float
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass(slots=True)
class PortfolioSnapshot:
    cash: float
    equity: float
    positions: list[Position]
    timestamp: datetime = field(default_factory=datetime.utcnow)
