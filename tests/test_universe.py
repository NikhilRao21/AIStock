from __future__ import annotations

import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from aistock.core.config import Settings
from aistock.runtime.universe import _parse_symbol_source_payload, resolve_symbols


class _FakeMarket:
    def __init__(self, prices: dict[str, float], fail_symbols: set[str] | None = None) -> None:
        self._prices = prices
        self._fail = fail_symbols or set()

    def latest_price(self, symbol: str) -> float:
        if symbol in self._fail:
            raise ValueError("quote unavailable")
        return self._prices[symbol]


class UniverseTests(unittest.TestCase):
    def test_parse_symbol_source_payload_handles_plain_ticker_lines(self) -> None:
        payload = "AAPL\nMSFT\nGOOGL\n"
        out = _parse_symbol_source_payload(payload)
        self.assertEqual(out, ["AAPL", "MSFT", "GOOGL"])

    def test_auto_mode_reaches_outside_predefined_universe(self) -> None:
        settings = Settings(
            universe_mode="auto",
            universe="AAPL,MSFT,GOOGL,AMZN,NVDA",
            auto_universe_batch_size=3,
            auto_universe_max_symbols=20,
            auto_universe_min_price=3,
            auto_universe_max_price=500,
        )

        symbols = ["AAPL", "MSFT", "JPM", "XOM", "UNH"]
        market = _FakeMarket(prices={"JPM": 210.0, "XOM": 118.0, "UNH": 420.0})

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            with patch("aistock.runtime.universe._load_or_refresh_universe", return_value=symbols):
                out = resolve_symbols(settings=settings, market=market, data_dir=data_dir)

        # Auto mode should prioritize non-core symbols over the predefined universe.
        self.assertEqual(out, ["JPM", "XOM", "UNH"])

    def test_auto_mode_probes_beyond_first_batch_before_fallback(self) -> None:
        settings = Settings(
            universe_mode="auto",
            universe="AAPL,MSFT",
            auto_universe_batch_size=2,
            auto_universe_max_symbols=20,
            auto_universe_min_price=3,
            auto_universe_max_price=500,
        )

        symbols = ["BAD1", "BAD2", "GOOD1", "GOOD2", "GOOD3"]
        market = _FakeMarket(prices={"GOOD1": 10.0, "GOOD2": 20.0, "GOOD3": 30.0}, fail_symbols={"BAD1", "BAD2"})

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            with patch("aistock.runtime.universe._load_or_refresh_universe", return_value=symbols):
                out = resolve_symbols(settings=settings, market=market, data_dir=data_dir)

            self.assertEqual(out, ["GOOD1", "GOOD2"])
            state = json.loads((data_dir / "universe_state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["cursor"], 0)

    def test_auto_mode_uses_selected_batch_when_no_valid_quotes(self) -> None:
        settings = Settings(
            universe_mode="auto",
            universe="AAPL,MSFT",
            auto_universe_batch_size=3,
            auto_universe_max_symbols=20,
            auto_universe_min_price=3,
            auto_universe_max_price=500,
        )

        symbols = ["BAD1", "BAD2", "BAD3"]
        market = _FakeMarket(prices={}, fail_symbols={"BAD1", "BAD2", "BAD3"})

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            with patch("aistock.runtime.universe._load_or_refresh_universe", return_value=symbols):
                out = resolve_symbols(settings=settings, market=market, data_dir=data_dir)

        self.assertEqual(out, ["BAD1", "BAD2", "BAD3"])

    def test_auto_mode_sanitizes_cached_symbols(self) -> None:
        settings = Settings(
            universe_mode="auto",
            universe="AAPL,MSFT",
            auto_universe_batch_size=2,
            auto_universe_max_symbols=20,
            auto_universe_min_price=3,
            auto_universe_max_price=500,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            cache = {
                "generated_at": "2099-01-01T00:00:00+00:00",
                "symbols": ["$Y", "$N", "AAPL", "MSFT", "BRK.B"],
            }
            (data_dir / "universe_cache.json").write_text(json.dumps(cache), encoding="utf-8")
            market = _FakeMarket(prices={"AAPL": 100.0, "MSFT": 200.0})

            out = resolve_symbols(settings=settings, market=market, data_dir=data_dir)

        self.assertEqual(out, ["AAPL", "MSFT"])

    def test_auto_mode_tops_up_when_discovered_universe_is_too_small(self) -> None:
        settings = Settings(
            universe_mode="auto",
            universe="AAPL,MSFT",
            auto_universe_batch_size=3,
            auto_universe_max_symbols=20,
            auto_universe_min_price=3,
            auto_universe_max_price=500,
        )
        market = _FakeMarket(prices={"JPM": 200.0, "AAPL": 180.0, "MSFT": 420.0})

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            with patch("aistock.runtime.universe._load_or_refresh_universe", return_value=["JPM"]):
                out = resolve_symbols(settings=settings, market=market, data_dir=data_dir)

        self.assertEqual(len(out), 3)
        self.assertIn("JPM", out)
        self.assertIn("AAPL", out)
        self.assertIn("MSFT", out)


if __name__ == "__main__":
    unittest.main()
