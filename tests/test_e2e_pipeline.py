from __future__ import annotations

import json
from pathlib import Path

from aistock.broker.paper_broker import PaperBroker
from aistock.core.config import settings
from aistock.runtime.pipeline import run_one_cycle


class FakeMarket:
    def latest_price(self, symbol: str) -> float:
        return 70.0

    def closes(self, symbol: str, days: int = 30) -> list[float]:
        # provide 30 days of steadily rising closes to favor BUY signals
        return [50.0 + i * 0.7 for i in range(30)]


def test_end_to_end_cycle(tmp_path):
    # use isolated data dir
    settings.data_dir = str(tmp_path)
    # force mock providers
    settings.ai_provider = "mock"
    settings.news_provider = "mock"
    settings.universe = "AAPL"
    settings.universe_mode = "fixed"

    # create broker with modest cash
    broker = PaperBroker(starting_cash=100_000.0)

    # monkeypatch pipeline's YFinanceProvider by injecting FakeMarket via import
    import aistock.runtime.pipeline as pipeline

    orig_market_cls = pipeline.YFinanceProvider
    try:
        pipeline.YFinanceProvider = FakeMarket  # type: ignore[attr-defined]
        result = run_one_cycle(broker=broker)
    finally:
        pipeline.YFinanceProvider = orig_market_cls

    # basic assertions about pipeline output and artifacts
    assert isinstance(result, dict)
    assert "cycle_report" in result
    data_dir = Path(settings.data_dir)
    assert (data_dir / "latest_cycle.json").exists()
    assert (data_dir / "dashboard.html").exists()

    # report should be parseable JSON and include equity
    rpt = json.loads((data_dir / "latest_cycle.json").read_text(encoding="utf-8"))
    assert "equity" in rpt
    assert rpt.get("equity") is not None
