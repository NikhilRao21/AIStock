from __future__ import annotations

from datetime import datetime
from json import JSONDecodeError

import requests

from aistock.core.config import settings
from aistock.core.types import NewsItem
from aistock.integrations.news.base import NewsProvider


class HackclubSearchNewsProvider(NewsProvider):
    """Pulls news-like results from Hack Club Search.

    The API shape may evolve, so this parser is intentionally defensive.
    """

    def __init__(self, timeout_seconds: int = 15) -> None:
        self._timeout = timeout_seconds

    def fetch_news(self, symbols: list[str], per_symbol: int = 5) -> list[NewsItem]:
        items: list[NewsItem] = []
        headers = {}
        if settings.search_hackclub_api_key:
            headers["Authorization"] = f"Bearer {settings.search_hackclub_api_key}"

        for symbol in symbols:
            query = f"{symbol} stock news"
            try:
                resp = requests.get(
                    settings.search_hackclub_base_url,
                    params={"q": query, "limit": per_symbol},
                    headers=headers,
                    timeout=self._timeout,
                )
                resp.raise_for_status()
                payload = resp.json()
            except (requests.RequestException, JSONDecodeError, ValueError):
                # Ignore bad upstream responses for this symbol and continue processing.
                continue

            results = payload.get("results", payload if isinstance(payload, list) else [])
            if not isinstance(results, list):
                continue

            now = datetime.utcnow()
            for obj in results[:per_symbol]:
                if not isinstance(obj, dict):
                    continue
                headline = str(obj.get("title") or obj.get("headline") or f"News for {symbol}")
                source = str(obj.get("source") or obj.get("domain") or "hackclub-search")
                summary = obj.get("snippet") or obj.get("description")
                items.append(
                    NewsItem(
                        symbol=symbol,
                        headline=headline,
                        source=source,
                        summary=str(summary) if summary else None,
                        published_at=now,
                    )
                )
        return items
