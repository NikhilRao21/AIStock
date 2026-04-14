from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from aistock.core.config import Settings
from aistock.integrations.market.base import MarketDataProvider

_NASDAQ_LIST_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt"


def resolve_symbols(
    settings: Settings,
    market: MarketDataProvider,
    data_dir: Path,
) -> list[str]:
    if settings.universe_mode.lower() != "auto":
        return settings.universe_symbols()

    symbols = _load_or_refresh_universe(data_dir, settings.auto_universe_max_symbols)
    if not symbols:
        return settings.universe_symbols()

    universe_state_path = data_dir / "universe_state.json"
    cursor = 0
    if universe_state_path.exists():
        try:
            payload = json.loads(universe_state_path.read_text(encoding="utf-8"))
            cursor = int(payload.get("cursor", 0))
        except (ValueError, TypeError, json.JSONDecodeError):
            cursor = 0

    batch_size = max(1, settings.auto_universe_batch_size)
    selected = _rotate_batch(symbols, cursor, batch_size)
    next_cursor = (cursor + batch_size) % len(symbols)
    universe_state_path.write_text(json.dumps({"cursor": next_cursor}, indent=2), encoding="utf-8")

    filtered: list[str] = []
    for symbol in selected:
        try:
            px = market.latest_price(symbol)
        except Exception:
            continue
        if settings.auto_universe_min_price <= px <= settings.auto_universe_max_price:
            filtered.append(symbol)

    return filtered or settings.universe_symbols()


def _rotate_batch(symbols: list[str], cursor: int, batch_size: int) -> list[str]:
    n = len(symbols)
    if n == 0:
        return []
    out: list[str] = []
    for i in range(min(batch_size, n)):
        out.append(symbols[(cursor + i) % n])
    return out


def _load_or_refresh_universe(data_dir: Path, max_symbols: int) -> list[str]:
    data_dir.mkdir(parents=True, exist_ok=True)
    cache_path = data_dir / "universe_cache.json"

    if cache_path.exists():
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            ts = datetime.fromisoformat(payload.get("generated_at"))
            if datetime.now(timezone.utc) - ts < timedelta(hours=24):
                cached = payload.get("symbols", [])
                if isinstance(cached, list):
                    return [str(s).upper() for s in cached[:max_symbols]]
        except (ValueError, TypeError, json.JSONDecodeError):
            pass

    symbols = _fetch_us_listed_symbols()[:max_symbols]
    cache_path.write_text(
        json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "symbols": symbols}, indent=2),
        encoding="utf-8",
    )
    return symbols


def _fetch_us_listed_symbols() -> list[str]:
    resp = requests.get(_NASDAQ_LIST_URL, timeout=20)
    resp.raise_for_status()

    symbols: list[str] = []
    for line in resp.text.splitlines():
        if not line or line.startswith("File Creation Time"):
            continue
        if line.startswith("Symbol|"):
            continue

        parts = line.split("|")
        if len(parts) < 7:
            continue

        symbol = parts[0].strip().upper()
        test_issue = parts[6].strip().upper()
        if not symbol or test_issue == "Y":
            continue
        if any(ch in symbol for ch in ("$", "^", "/")):
            continue

        symbols.append(symbol)

    # Keep deterministic ordering while deduplicating.
    deduped = list(dict.fromkeys(symbols))
    return deduped
