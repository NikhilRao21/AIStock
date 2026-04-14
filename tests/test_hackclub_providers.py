from __future__ import annotations

from datetime import datetime
import unittest
from unittest.mock import MagicMock, patch

from aistock.core.config import settings
from aistock.core.types import NewsItem
from aistock.integrations.ai.hackclub import HackclubAiProvider
from aistock.integrations.news.hackclub import HackclubSearchNewsProvider


class HackclubProvidersTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_ai_base = settings.ai_hackclub_base_url
        self._orig_ai_endpoint = settings.ai_hackclub_endpoint
        self._orig_ai_model = settings.ai_hackclub_model
        self._orig_search_base = settings.search_hackclub_base_url
        self._orig_search_endpoint = settings.search_hackclub_endpoint

        settings.ai_hackclub_base_url = "https://ai.hackclub.com"
        settings.ai_hackclub_endpoint = "/proxy/v1/chat/completions"
        settings.ai_hackclub_model = "gpt-5-mini"
        settings.search_hackclub_base_url = "https://search.hackclub.com"
        settings.search_hackclub_endpoint = "/res/v1/news/search"

    def tearDown(self) -> None:
        settings.ai_hackclub_base_url = self._orig_ai_base
        settings.ai_hackclub_endpoint = self._orig_ai_endpoint
        settings.ai_hackclub_model = self._orig_ai_model
        settings.search_hackclub_base_url = self._orig_search_base
        settings.search_hackclub_endpoint = self._orig_search_endpoint

    def test_news_provider_uses_news_endpoint_and_parses_results(self) -> None:
        provider = HackclubSearchNewsProvider()
        response = MagicMock()
        response.status_code = 200
        response.text = '{"results":[{"title":"AAPL rises","source":"Reuters","snippet":"earnings beat"}]}'
        response.json.return_value = {
            "results": [
                {"title": "AAPL rises", "source": "Reuters", "snippet": "earnings beat"},
            ]
        }

        with patch.object(provider._session, "get", return_value=response) as mock_get:
            items = provider.fetch_news(["AAPL"])

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].headline, "AAPL rises")
        self.assertEqual(items[0].source, "Reuters")
        self.assertTrue(mock_get.call_args[0][0].endswith("/res/v1/news/search"))

    def test_ai_provider_uses_chat_completions_and_parses_json_content(self) -> None:
        provider = HackclubAiProvider()
        response = MagicMock()
        response.status_code = 200
        response.text = "ok"
        response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": '{"action":"BUY","confidence":0.92,"rationale":"strong sentiment"}'
                    }
                }
            ]
        }

        with patch.object(provider._session, "post", return_value=response) as mock_post:
            signals = provider.score_news(
                [
                    NewsItem(
                        symbol="AAPL",
                        headline="AAPL beats earnings",
                        source="test",
                        summary="",
                        published_at=datetime.utcnow(),
                    )
                ]
            )

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].action, "BUY")
        self.assertGreater(signals[0].confidence, 0.9)
        self.assertTrue(mock_post.call_args[0][0].endswith("/proxy/v1/chat/completions"))
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "gpt-5-mini")

    def test_ai_provider_parses_markdown_json_block(self) -> None:
        provider = HackclubAiProvider()
        response = MagicMock()
        response.status_code = 200
        response.text = "ok"
        response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "```json\n{\"action\":\"SELL\",\"confidence\":0.7,\"rationale\":\"negative\"}\n```"
                    }
                }
            ]
        }

        with patch.object(provider._session, "post", return_value=response):
            signals = provider.score_news(
                [
                    NewsItem(
                        symbol="MSFT",
                        headline="MSFT faces lawsuit",
                        source="test",
                        summary="",
                        published_at=datetime.utcnow(),
                    )
                ]
            )

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].action, "SELL")

    def test_ai_provider_auth_failure_returns_hold_and_debug_status(self) -> None:
        provider = HackclubAiProvider()
        response = MagicMock()
        response.status_code = 401
        response.text = "unauthorized"

        with patch.object(provider._session, "post", return_value=response):
            signals = provider.score_news(
                [
                    NewsItem(
                        symbol="NVDA",
                        headline="NVDA update",
                        source="test",
                        summary="",
                        published_at=datetime.utcnow(),
                    )
                ]
            )

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].action, "HOLD")
        self.assertEqual(provider.last_debug[0]["status"], "auth_error")


if __name__ == "__main__":
    unittest.main()
