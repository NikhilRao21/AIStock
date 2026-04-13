from __future__ import annotations

import yfinance as yf

from aistock.integrations.market.base import MarketDataProvider


class YFinanceProvider(MarketDataProvider):
    def latest_price(self, symbol: str) -> float:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="2d", interval="1d")
        if hist.empty:
            raise ValueError(f"No price data for {symbol}")
        return float(hist["Close"].iloc[-1])

    def closes(self, symbol: str, days: int = 30) -> list[float]:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=f"{max(days, 30)}d", interval="1d")
        closes = [float(x) for x in hist["Close"].dropna().tolist()]
        if len(closes) < 5:
            raise ValueError(f"Insufficient close data for {symbol}")
        return closes
