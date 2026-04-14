from __future__ import annotations

from datetime import datetime
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from aistock.core.config import settings
from aistock.core.types import NewsItem
from aistock.integrations.news.base import NewsProvider


class HackclubSearchNewsProvider(NewsProvider):
    """Pulls news-like results from Hack Club Search.

    The API shape may evolve, so this parser is intentionally defensive.
    """

    def __init__(self, timeout_seconds: int | None = None, max_retries: int | None = None) -> None:
        self._timeout = timeout_seconds or settings.search_hackclub_timeout_seconds
        self._base_url = settings.search_hackclub_base_url
        self._endpoint = settings.search_hackclub_endpoint
        retries = max_retries if max_retries is not None else settings.search_hackclub_max_retries
        self._session = requests.Session()
        retry = Retry(
            total=max(0, retries),
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(["GET"]),
        )
        adapter = HTTPAdapter(max_retries=retry)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)
        self.last_debug: list[dict[str, Any]] = []

    def _url(self) -> str:
        return f"{self._base_url.rstrip('/')}/{self._endpoint.lstrip('/')}"

    def fetch_news(self, symbols: list[str], per_symbol: int = 5) -> list[NewsItem]:
        self.last_debug = []
        items: list[NewsItem] = []
        headers = {
            "Accept": "application/json",
            "User-Agent": "AIStock/1.0",
        }
        if settings.search_hackclub_api_key:
            headers["Authorization"] = f"Bearer {settings.search_hackclub_api_key}"

        for symbol in symbols:
            query = f"{symbol} stock news"
            debug_item: dict[str, Any] = {
                "symbol": symbol,
                "query": query,
                "status": "ok",
                "http_status": None,
                "result_count": 0,
                "error": None,
                "raw_response": None,
            }
            try:
                resp = self._session.get(
                    self._url(),
                    params={"q": query, "limit": per_symbol},
                    headers=headers,
                    timeout=self._timeout,
                )
                debug_item["http_status"] = resp.status_code
                debug_item["raw_response"] = resp.text[:4000]

                if resp.status_code in {401, 403}:
                    debug_item["status"] = "auth_error"
                    debug_item["error"] = f"HTTP {resp.status_code}: authorization failed"
                    self.last_debug.append(debug_item)
                    continue
                if resp.status_code == 404:
                    debug_item["status"] = "not_found"
                    debug_item["error"] = "HTTP 404: endpoint not found"
                    self.last_debug.append(debug_item)
                    continue

                resp.raise_for_status()
                payload = resp.json()
            except (requests.RequestException, ValueError, TypeError) as exc:
                debug_item["status"] = "error"
                debug_item["error"] = f"{type(exc).__name__}: {exc}"
                self.last_debug.append(debug_item)
                continue

            results: Any = []
            if isinstance(payload, dict):
                # Brave-compatible variants seen in search proxies.
                results = payload.get("results")
                if results is None and isinstance(payload.get("news"), dict):
                    results = payload.get("news", {}).get("results")
            elif isinstance(payload, list):
                results = payload

            if not isinstance(results, list):
                debug_item["status"] = "schema_error"
                debug_item["error"] = "Response did not contain a list of results"
                self.last_debug.append(debug_item)
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

            debug_item["result_count"] = len(results[:per_symbol])
            self.last_debug.append(debug_item)
        return items
