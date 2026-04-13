from __future__ import annotations

import json

import requests

from aistock.core.config import settings
from aistock.core.types import AiSignal, NewsItem
from aistock.integrations.ai.base import AiProvider


class HackclubAiProvider(AiProvider):
    """Uses Hack Club AI endpoint with a strict JSON output contract."""

    def __init__(self, timeout_seconds: int = 20) -> None:
        self._timeout = timeout_seconds

    def score_news(self, news: list[NewsItem]) -> list[AiSignal]:
        if not news:
            return []

        grouped: dict[str, list[NewsItem]] = {}
        for item in news:
            grouped.setdefault(item.symbol, []).append(item)

        signals: list[AiSignal] = []
        headers = {}
        if settings.ai_hackclub_api_key:
            headers["Authorization"] = f"Bearer {settings.ai_hackclub_api_key}"

        for symbol, items in grouped.items():
            prompt = self._build_prompt(symbol, items)
            payload = {
                "messages": [
                    {"role": "system", "content": "You are a strict financial news classifier."},
                    {"role": "user", "content": prompt},
                ]
            }

            response = requests.post(
                settings.ai_hackclub_base_url,
                json=payload,
                headers=headers,
                timeout=self._timeout,
            )
            response.raise_for_status()
            data = response.json()
            content = self._extract_text(data)
            parsed = json.loads(content)

            action = parsed.get("action", "HOLD")
            if action not in {"BUY", "SELL", "HOLD"}:
                action = "HOLD"
            confidence = float(parsed.get("confidence", 0.5))
            confidence = max(0.0, min(1.0, confidence))
            rationale = str(parsed.get("rationale", "No rationale provided"))
            signals.append(AiSignal(symbol=symbol, action=action, confidence=confidence, rationale=rationale))

        return signals

    @staticmethod
    def _build_prompt(symbol: str, items: list[NewsItem]) -> str:
        lines = [f"Classify these headlines for {symbol}:"]
        for idx, item in enumerate(items, start=1):
            lines.append(f"{idx}. {item.headline}")
        lines.append(
            'Return only JSON: {"action":"BUY|SELL|HOLD","confidence":0..1,"rationale":"short text"}'
        )
        return "\n".join(lines)

    @staticmethod
    def _extract_text(response_json: dict) -> str:
        if "choices" in response_json and response_json["choices"]:
            return response_json["choices"][0].get("message", {}).get("content", "{}")
        if "text" in response_json:
            return str(response_json["text"])
        return "{}"
