from __future__ import annotations

from datetime import datetime, timedelta

from aistock.core.types import NewsItem
from aistock.integrations.news.base import NewsProvider


class MockNewsProvider(NewsProvider):
    def fetch_news(self, symbols: list[str], per_symbol: int = 5) -> list[NewsItem]:
        now = datetime.utcnow()
        out: list[NewsItem] = []
        for symbol in symbols:
            out.append(
                NewsItem(
                    symbol=symbol,
                    headline=f"{symbol} reports strong quarterly growth",
                    source="mock",
                    summary=f"Synthetic positive update for {symbol}",
                    published_at=now - timedelta(minutes=5),
                )
            )
        return out
