from __future__ import annotations

import json
import re
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from aistock.core.config import settings
from aistock.core.types import AiSignal, NewsItem
from aistock.integrations.ai.base import AiProvider


class HackclubAiProvider(AiProvider):
    """Uses Hack Club AI endpoint with a strict JSON output contract."""

    def __init__(self, timeout_seconds: int | None = None, max_retries: int | None = None) -> None:
        self._timeout = timeout_seconds or settings.ai_hackclub_timeout_seconds
        self._base_url = settings.ai_hackclub_base_url
        self._endpoint = settings.ai_hackclub_endpoint
        self._model = settings.ai_hackclub_model
        retries = max_retries if max_retries is not None else settings.ai_hackclub_max_retries
        self._session = requests.Session()
        retry = Retry(
            total=max(0, retries),
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(["POST"]),
        )
        adapter = HTTPAdapter(max_retries=retry)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)
        self.last_debug: list[dict[str, Any]] = []

    def _url(self) -> str:
        return f"{self._base_url.rstrip('/')}/{self._endpoint.lstrip('/')}"

    def score_news(self, news: list[NewsItem], trends: dict[str, dict[str, Any]] | None = None) -> list[AiSignal]:
        self.last_debug = []
        if not news and not (isinstance(trends, dict) and trends):
            # No actionable input (neither news nor trends) — record debug and return.
            self.last_debug.append(
                {
                    "symbol": "*",
                    "status": "empty_input",
                    "http_status": None,
                    "raw_response": None,
                    "extracted_content": None,
                    "error": "No news items or market trends were provided to AI provider",
                    "parsed": None,
                    "model": self._model,
                }
            )
            return []

        grouped: dict[str, list[NewsItem]] = {}
        for item in news:
            grouped.setdefault(item.symbol, []).append(item)

        # Build the set of symbols to score: those with news, plus those with trends
        symbols_to_score: set[str] = set(grouped.keys())
        if isinstance(trends, dict):
            symbols_to_score.update(trends.keys())

        signals: list[AiSignal] = []
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "AIStock/1.0",
        }
        if settings.ai_hackclub_api_key:
            headers["Authorization"] = f"Bearer {settings.ai_hackclub_api_key}"

        for symbol in symbols_to_score:
            items = grouped.get(symbol, [])
            trend = None
            if isinstance(trends, dict):
                trend = trends.get(symbol)
            prompt = self._build_prompt(symbol, items, trend=trend)
            payload = {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": "You are a strict financial news classifier."},
                    {"role": "user", "content": prompt},
                ],
                "response_format": {"type": "json_object"},
            }
            debug_item: dict[str, Any] = {
                "symbol": symbol,
                "prompt": prompt,
                "status": "ok",
                "http_status": None,
                "raw_response": None,
                "extracted_content": None,
                "error": None,
                "parsed": None,
                "trend": trend,
                "model": self._model,
            }

            try:
                response = self._session.post(
                    self._url(),
                    json=payload,
                    headers=headers,
                    timeout=self._timeout,
                )
                debug_item["http_status"] = response.status_code
                debug_item["raw_response"] = response.text[:5000]

                if response.status_code in {401, 403}:
                    debug_item["status"] = "auth_error"
                    debug_item["error"] = f"HTTP {response.status_code}: authorization failed"
                    raise ValueError(debug_item["error"])
                if response.status_code == 404:
                    debug_item["status"] = "not_found"
                    debug_item["error"] = "HTTP 404: endpoint not found"
                    raise ValueError(debug_item["error"])

                response.raise_for_status()

                data = response.json()
                content = self._extract_text(data)
                debug_item["extracted_content"] = content
                parsed = self._parse_json_payload(content)
                debug_item["parsed"] = parsed

                action = str(parsed.get("action", "HOLD")).upper()
                if action not in {"BUY", "SELL", "HOLD"}:
                    action = "HOLD"
                confidence = float(parsed.get("confidence", 0.5))
                confidence = max(0.0, min(1.0, confidence))
                rationale = str(parsed.get("rationale", "No rationale provided"))
                signals.append(AiSignal(symbol=symbol, action=action, confidence=confidence, rationale=rationale))
            except (requests.RequestException, ValueError, TypeError, json.JSONDecodeError) as exc:
                if debug_item["status"] == "ok":
                    debug_item["status"] = "error"
                debug_item["error"] = f"{type(exc).__name__}: {exc}"
                # Keep cycle resilient and explicit when AI parsing fails.
                signals.append(
                    AiSignal(
                        symbol=symbol,
                        action="HOLD",
                        confidence=0.0,
                        rationale=f"AI provider error: {type(exc).__name__}",
                    )
                )

            self.last_debug.append(debug_item)

        return signals

    @staticmethod
    def _build_prompt(symbol: str, items: list[NewsItem], trend: dict[str, Any] | None = None) -> str:
        lines = [f"Classify these headlines for {symbol}:"]
        for idx, item in enumerate(items, start=1):
            lines.append(f"{idx}. {item.headline}")
        if trend:
            # Add a compact market trend summary to the prompt to help the model
            trend_parts: list[str] = []
            try:
                if "ma5" in trend:
                    trend_parts.append(f"MA5={trend.get('ma5'):.2f}")
                if "ma20" in trend:
                    trend_parts.append(f"MA20={trend.get('ma20'):.2f}")
                if "momentum_5d" in trend:
                    trend_parts.append(f"mom5={trend.get('momentum_5d'):.3f}")
                if "momentum_20d" in trend:
                    trend_parts.append(f"mom20={trend.get('momentum_20d'):.3f}")
            except Exception:
                pass
            if trend_parts:
                lines.append("\nMarket trend summary: " + ", ".join(trend_parts))
        lines.append(
            'Return only JSON: {"action":"BUY|SELL|HOLD","confidence":0..1,"rationale":"short text"}'
        )
        return "\n".join(lines)

    @staticmethod
    def _extract_text(response_json: dict) -> str:
        if "choices" in response_json and response_json["choices"]:
            message = response_json["choices"][0].get("message", {})
            content = message.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = []
                for chunk in content:
                    if isinstance(chunk, dict) and isinstance(chunk.get("text"), str):
                        parts.append(chunk["text"])
                if parts:
                    return "\n".join(parts)
        if "text" in response_json:
            return str(response_json["text"])
        return "{}"

    @staticmethod
    def _parse_json_payload(content: str) -> dict[str, Any]:
        text = content.strip()
        if not text:
            raise ValueError("AI response content was empty")

        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)

        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            raise ValueError("AI response did not contain a JSON object")

        parsed = json.loads(match.group(0))
        if not isinstance(parsed, dict):
            raise ValueError("AI response JSON was not an object")
        return parsed
