from __future__ import annotations

import unittest

from aistock.core.config import settings
from aistock.runtime import pipeline
from aistock.integrations.news.rss_provider import RSSNewsProvider


class ProviderSwitchingTests(unittest.TestCase):
    def test_switching_to_rss_provider(self) -> None:
        orig = settings.news_provider
        settings.news_provider = "rss"
        try:
            provider = pipeline._build_news_provider()
            self.assertIsInstance(provider, RSSNewsProvider)
        finally:
            settings.news_provider = orig


if __name__ == "__main__":
    unittest.main()
