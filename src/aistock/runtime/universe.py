from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from aistock.core.config import Settings
from aistock.integrations.market.base import MarketDataProvider

_NASDAQ_LIST_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt"
_GITHUB_TICKERS_URL = "https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/all/all_tickers.txt"
_AUTO_FALLBACK_SYMBOLS = [
    "JPM", "XOM", "UNH", "JNJ", "PG", "HD", "CVX", "MA", "V", "LLY",
    "BAC", "KO", "PEP", "ABBV", "MRK", "COST", "WMT", "ADBE", "CRM", "NFLX",
    "AMD", "INTC", "CSCO", "QCOM", "ORCL", "AVGO", "TXN", "AMAT", "NOW", "PANW",
    "SPY", "QQQ", "IWM", "DIA", "XLF", "XLK", "XLE", "XLV", "XLI", "XLP",
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "SHOP", "UBER", "PLTR",
]


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

    # Prefer scanning outside the core universe in auto mode.
    core_universe = set(settings.universe_symbols())
    non_core_symbols = [s for s in symbols if s not in core_universe]
    if non_core_symbols:
        symbols = non_core_symbols

    universe_state_path = data_dir / "universe_state.json"
    cursor = 0
    if universe_state_path.exists():
        try:
            payload = json.loads(universe_state_path.read_text(encoding="utf-8"))
            cursor = int(payload.get("cursor", 0))
        except (ValueError, TypeError, json.JSONDecodeError):
            cursor = 0

    batch_size = max(1, settings.auto_universe_batch_size)
    # Probe multiple candidate windows per cycle so a weak/invalid first batch
    # does not immediately force a fallback to the fixed universe.
    max_candidates = min(len(symbols), batch_size * 5)
    selected = _rotate_batch(symbols, cursor, max_candidates)
    selected_batch = selected[:batch_size]
    next_cursor = (cursor + max_candidates) % len(symbols)
    universe_state_path.write_text(json.dumps({"cursor": next_cursor}, indent=2), encoding="utf-8")

    filtered: list[str] = []
    for symbol in selected:
        try:
            px = market.latest_price(symbol)
        except Exception:
            continue
        if settings.auto_universe_min_price <= px <= settings.auto_universe_max_price:
            filtered.append(symbol)
            if len(filtered) >= batch_size:
                break

    # If filtered set is smaller than the desired batch_size but not empty,
    # top up from the selected_batch so the cycle scans up to `batch_size`
    # symbols. This avoids very-small scans when many symbols fail price
    # checks transiently.
    if filtered:
        if len(filtered) < batch_size and selected_batch:
            to_add = [s for s in selected_batch if s not in filtered][: max(0, batch_size - len(filtered))]
            filtered.extend(to_add)
        return filtered

    return selected_batch


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
                    sanitized = _sanitize_symbols([str(s).upper() for s in cached])
                    if sanitized:
                        return sanitized[:max_symbols]
        except (ValueError, TypeError, json.JSONDecodeError):
            pass

    try:
        symbols = _fetch_us_listed_symbols()[:max_symbols]
    except requests.RequestException:
        # Use stale cache as best-effort fallback when refresh fails.
        if cache_path.exists():
            try:
                payload = json.loads(cache_path.read_text(encoding="utf-8"))
                cached = payload.get("symbols", [])
                if isinstance(cached, list):
                    sanitized = _sanitize_symbols([str(s).upper() for s in cached])
                    if sanitized:
                        return sanitized[:max_symbols]
            except (ValueError, TypeError, json.JSONDecodeError):
                pass
        return _sanitize_symbols(_AUTO_FALLBACK_SYMBOLS)[:max_symbols]

    if not symbols:
        return _sanitize_symbols(_AUTO_FALLBACK_SYMBOLS)[:max_symbols]

    cache_path.write_text(
        json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "symbols": symbols}, indent=2),
        encoding="utf-8",
    )
    return symbols


def _fetch_us_listed_symbols() -> list[str]:
    symbols: list[str] = []
    errors: list[Exception] = []

    # Try primary + fallback sources in order so auto-universe can still build
    # a broad symbol list when one upstream feed is unavailable.
    for source_url in (_NASDAQ_LIST_URL, _GITHUB_TICKERS_URL):
        try:
            resp = requests.get(source_url, timeout=20)
            resp.raise_for_status()
        except requests.RequestException as exc:
            errors.append(exc)
            continue

        symbols.extend(_parse_symbol_source_payload(resp.text))
        if symbols:
            break

    if not symbols and errors:
        raise errors[-1]
    return _sanitize_symbols(symbols)


def _parse_symbol_source_payload(payload: str) -> list[str]:
    """Parse either nasdaqtraded.txt rows or plain one-ticker-per-line payloads."""
    symbols: list[str] = []
    lines = payload.splitlines()
    if not lines:
        return symbols

    looks_like_nasdaq_txt = lines[0].startswith("Symbol|") or any("|" in line for line in lines[:3])
    if looks_like_nasdaq_txt:
        for line in lines:
            if not line or line.startswith("File Creation Time") or line.startswith("Symbol|"):
                continue
            parts = line.split("|")
            if len(parts) < 7:
                continue
            symbol = parts[0].strip().upper()
            test_issue = parts[6].strip().upper()
            if not symbol or test_issue == "Y":
                continue
            symbols.append(symbol)
        return symbols

    for line in lines:
        symbol = line.strip().upper()
        if not symbol or symbol in {"SYMBOL", "TICKER"}:
            continue
        symbols.append(symbol)
    return symbols


def _sanitize_symbols(symbols: list[str]) -> list[str]:
    clean: list[str] = []
    seen: set[str] = set()
    for raw in symbols:
        symbol = str(raw).strip().upper()
        if not symbol:
            continue
        if symbol in seen:
            continue
        if not symbol.isalpha() or len(symbol) < 2 or len(symbol) > 5:
            continue
        if any(ch in symbol for ch in ("$", "^", "/", ".")):
            continue
        seen.add(symbol)
        clean.append(symbol)
    return clean
