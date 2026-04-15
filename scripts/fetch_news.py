#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from aistock.core.config import settings
from aistock.integrations.news.rss_provider import RSSNewsProvider
from aistock.runtime.pipeline import _write_cached_news


def main() -> None:
    provider = RSSNewsProvider()
    symbols = settings.universe_symbols()
    items = provider.fetch_news(symbols)
    data_dir = Path(settings.data_dir)
    _write_cached_news(data_dir, items)
    print(f"Fetched {len(items)} news items and wrote cache to {data_dir / 'news_cache.json'}")


if __name__ == "__main__":
    main()
