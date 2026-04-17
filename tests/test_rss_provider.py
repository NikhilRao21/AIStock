from __future__ import annotations

from datetime import datetime
import unittest
from unittest.mock import MagicMock, patch

from aistock.integrations.news.rss_provider import RSSNewsProvider
from aistock.core.types import NewsItem


class RSSProviderTests(unittest.TestCase):
    def test_rss_provider_parses_feed_and_matches_symbol(self) -> None:
        provider = RSSNewsProvider()
        # Minimal RSS feed with one item mentioning AAPL
        feed = """<?xml version='1.0'?>
        <rss>
          <channel>
            <title>Test Feed</title>
            <item>
              <title>AAPL reports gains</title>
              <description>Apple ($AAPL) beats earnings</description>
              <link>http://example.com/aapl</link>
              <pubDate>Mon, 01 Jan 2024 12:00:00 GMT</pubDate>
            </item>
          </channel>
        </rss>
        """

        response = MagicMock()
        response.status_code = 200
        response.content = feed.encode("utf-8")
        response.headers = {}

        with patch.object(provider._session, "get", return_value=response) as mock_get:
            items = provider.fetch_news(["AAPL"])

        self.assertEqual(len(items), 1)
        self.assertIsInstance(items[0], NewsItem)
        self.assertIn("AAPL", items[0].headline)
        self.assertTrue(mock_get.called)

    def test_rss_provider_rate_limit_sets_debug_status(self) -> None:
        provider = RSSNewsProvider()
        response = MagicMock()
        response.status_code = 429
        response.content = b""

        with patch.object(provider._session, "get", return_value=response):
            items = provider.fetch_news(["AAPL"]) 

        self.assertEqual(items, [])
        self.assertEqual(provider.last_debug[0]["status"], "rate_limited")

    def test_rss_provider_does_not_match_partial_symbol_tokens(self) -> None:
        provider = RSSNewsProvider()
        feed = """<?xml version='1.0'?>
        <rss>
          <channel>
            <title>Test Feed</title>
            <item>
              <title>Market closes higher today</title>
              <description>Broad market update with no ticker mention</description>
              <link>http://example.com/market</link>
              <pubDate>Mon, 01 Jan 2024 12:00:00 GMT</pubDate>
            </item>
          </channel>
        </rss>
        """

        response = MagicMock()
        response.status_code = 200
        response.content = feed.encode("utf-8")
        response.headers = {}

        with patch.object(provider._session, "get", return_value=response):
            items = provider.fetch_news(["MA"])

        self.assertEqual(items, [])


if __name__ == "__main__":
    unittest.main()
