from __future__ import annotations

import json
import tempfile
from pathlib import Path
import unittest

from aistock.core.types import AiSignal, Fill, PortfolioSnapshot, Position, SignalSnapshot, TradeDecision
from aistock.runtime.reporting import write_cycle_report


class ReportingTests(unittest.TestCase):
    def test_write_cycle_report_includes_new_dashboard_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            report = write_cycle_report(
                data_dir=data_dir,
                symbols_scanned=["AAPL", "MSFT"],
                decisions=[
                    TradeDecision(
                        symbol="MSFT",
                        action="BUY",
                        confidence=0.91,
                        quantity=4,
                        reason="structured decision",
                        signals=[SignalSnapshot(family="ai", action="BUY", confidence=0.95, details="beat")],
                        is_hidden_gem=True,
                        hidden_gem_reason="High-confidence BUY outside the core universe",
                    )
                ],
                fills=[Fill(symbol="MSFT", action="BUY", quantity=4, fill_price=100.0, fee=1.0)],
                portfolio=PortfolioSnapshot(
                    cash=500.0,
                    equity=900.0,
                    positions=[Position(symbol="AAPL", quantity=2, avg_cost=50.0), Position(symbol="MSFT", quantity=4, avg_cost=100.0)],
                ),
                ai_output=[AiSignal(symbol="MSFT", action="BUY", confidence=0.95, rationale="Strong earnings momentum")],
                ai_raw_output=[
                    {
                        "symbol": "MSFT",
                        "status": "ok",
                        "http_status": 200,
                        "raw_response": '{"action":"BUY","confidence":0.95,"rationale":"Strong earnings momentum"}',
                        "extracted_content": '{"action":"BUY","confidence":0.95,"rationale":"Strong earnings momentum"}',
                        "parsed": {"action": "BUY"},
                        "error": None,
                    }
                ],
                market_prices={"AAPL": 55.0, "MSFT": 110.0},
                previous_equity=850.0,
                previous_positions=[Position(symbol="AAPL", quantity=2, avg_cost=50.0)],
                news_status={
                    "ok": False,
                    "fallback_used": True,
                    "cache_fallback_used": True,
                    "error": "JSONDecodeError: bad payload",
                    "provider": "hackclub",
                    "error_counts": {"rate_limited": 1, "error": 1},
                    "raw_output": [
                        {
                            "symbol": "MSFT",
                            "status": "error",
                            "http_status": 500,
                            "error": "boom",
                            "raw_response": '{"error":"boom"}',
                        }
                    ],
                },
                ai_status={"ok": False, "error": "HTTP 401", "provider": "hackclub"},
                execution_diagnostics={
                    "sized_zero_reasons": {"insufficient_budget": 3},
                    "executable_orders": 0,
                    "failed_orders": [],
                },
                signal_policy={"ai_weight": 0.6, "conventional_weight": 0.4, "disabled": []},
                debug_issues=["No fills were executed"],
                history_limit=10,
            )

            self.assertEqual(report["position_changes"]["new_buys"], [{"symbol": "MSFT", "quantity": 4, "avg_cost": 100.0}])
            self.assertEqual(report["position_changes"]["carried_positions"], [{"symbol": "AAPL", "quantity": 2, "avg_cost": 50.0}])
            self.assertEqual(report["hidden_gem_candidates"][0]["symbol"], "MSFT")
            self.assertEqual(report["news_status"]["ok"], False)

            latest = json.loads((data_dir / "latest_cycle.json").read_text(encoding="utf-8"))
            self.assertEqual(latest["ai_output_count"], 1)
            self.assertEqual(latest["ai_raw_output_count"], 1)
            self.assertEqual(latest["news_raw_output_count"], 1)
            self.assertEqual(latest["news_error_counts"]["rate_limited"], 1)
            self.assertEqual(latest["ai_status"]["ok"], False)
            self.assertEqual(latest["execution_diagnostics"]["executable_orders"], 0)
            self.assertIn("signal_performance", latest)
            self.assertIn("symbols_scanned", latest)

            dashboard = (data_dir / "dashboard.html").read_text(encoding="utf-8")
            self.assertIn("AI Output From Last Cycle", dashboard)
            self.assertIn("Raw AI Provider Output", dashboard)
            self.assertIn("Debug Issues", dashboard)
            self.assertIn("Symbols Scanned This Cycle", dashboard)
            self.assertIn("Hidden-Gem Candidates", dashboard)
            self.assertIn("News feed failing or degraded", dashboard)
            self.assertIn("Provider Diagnostics", dashboard)
            self.assertIn("Raw News Responses", dashboard)
            self.assertIn("Execution Diagnostics", dashboard)
            self.assertIn("Cache fallback used", dashboard)
            self.assertIn("Closed Positions (Sells)", dashboard)
            self.assertIn("Recent Fills (Buys & Sells)", dashboard)
            self.assertIn("Conventional Method Stratification", dashboard)
            self.assertIn("{&quot;error&quot;:&quot;boom&quot;}", dashboard)

    def test_sells_are_logged_and_shown_in_dashboard(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            fills = [
                Fill(symbol="AAPL", action="BUY", quantity=1, fill_price=10.0, fee=0.1),
                Fill(symbol="AAPL", action="SELL", quantity=1, fill_price=12.0, fee=0.1),
            ]
            report = write_cycle_report(
                data_dir=data_dir,
                symbols_scanned=["AAPL"],
                decisions=[],
                fills=fills,
                portfolio=PortfolioSnapshot(cash=100.0, equity=112.0, positions=[]),
                ai_output=[],
                ai_raw_output=[],
                market_prices={"AAPL": 12.0},
                previous_equity=100.0,
                previous_positions=[],
                news_status={"ok": True},
                history_limit=5,
            )

            purchase_log_path = data_dir / "purchase_log.jsonl"
            self.assertTrue(purchase_log_path.exists())
            entries = [json.loads(l) for l in purchase_log_path.read_text(encoding="utf-8").splitlines() if l.strip()]
            # Expect at least one SELL entry recorded
            self.assertTrue(any(e.get("side") == "SELL" for e in entries))

            latest = json.loads((data_dir / "latest_cycle.json").read_text(encoding="utf-8"))
            self.assertIn("purchase_log", latest)
            self.assertTrue(any(e.get("side") == "SELL" for e in latest.get("purchase_log", [])))

            dashboard = (data_dir / "dashboard.html").read_text(encoding="utf-8")
            # dashboard should include a styled action cell for sell
            self.assertIn("action-sell", dashboard)

if __name__ == "__main__":
    unittest.main()
