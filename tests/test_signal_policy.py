from __future__ import annotations

import unittest

from aistock.core.config import settings
from aistock.core.types import SignalSnapshot, TradeDecision
from aistock.runtime.pipeline import (
    _apply_buy_quality_guard,
    _collect_debug_issues,
    _expected_buy_edge,
    _signal_weights_from_history,
)
from aistock.runtime.reporting import _build_signal_performance


class SignalPolicyTests(unittest.TestCase):
    def test_expected_buy_edge_accounts_for_reward_risk_and_fees(self) -> None:
        edge = _expected_buy_edge(
            confidence=0.6,
            take_profit_pct=0.06,
            stop_loss_pct=0.03,
            fee_bps=5.0,
        )
        self.assertGreater(edge, 0.0)

    def test_signal_performance_rollup_marks_underperformers(self) -> None:
        history = [
            {
                "decisions": [
                    {
                        "symbol": "AAPL",
                        "action": "BUY",
                        "quantity": 1,
                        "signals": [
                            {"family": "ai", "action": "BUY", "confidence": 0.9, "details": ""},
                            {"family": "conventional", "action": "BUY", "confidence": 0.8, "details": ""},
                        ],
                    }
                ],
                "fills": [{"symbol": "AAPL", "action": "BUY", "quantity": 1, "fill_price": 100.0}],
            },
            {
                "decisions": [
                    {
                        "symbol": "AAPL",
                        "action": "BUY",
                        "quantity": 1,
                        "signals": [
                            {"family": "ai", "action": "BUY", "confidence": 0.9, "details": ""},
                            {"family": "conventional", "action": "BUY", "confidence": 0.8, "details": ""},
                        ],
                    }
                ],
                "fills": [{"symbol": "AAPL", "action": "BUY", "quantity": 1, "fill_price": 100.0}],
            },
            {
                "decisions": [
                    {
                        "symbol": "AAPL",
                        "action": "BUY",
                        "quantity": 1,
                        "signals": [
                            {"family": "ai", "action": "BUY", "confidence": 0.9, "details": ""},
                            {"family": "conventional", "action": "BUY", "confidence": 0.8, "details": ""},
                        ],
                    }
                ],
                "fills": [{"symbol": "AAPL", "action": "BUY", "quantity": 1, "fill_price": 100.0}],
            },
            {
                "decisions": [
                    {
                        "symbol": "AAPL",
                        "action": "BUY",
                        "quantity": 1,
                        "signals": [
                            {"family": "ai", "action": "BUY", "confidence": 0.9, "details": ""},
                            {"family": "conventional", "action": "BUY", "confidence": 0.8, "details": ""},
                        ],
                    }
                ],
                "fills": [{"symbol": "AAPL", "action": "BUY", "quantity": 1, "fill_price": 100.0}],
            },
            {
                "decisions": [
                    {
                        "symbol": "AAPL",
                        "action": "BUY",
                        "quantity": 1,
                        "signals": [
                            {"family": "ai", "action": "BUY", "confidence": 0.9, "details": ""},
                            {"family": "conventional", "action": "BUY", "confidence": 0.8, "details": ""},
                        ],
                    }
                ],
                "fills": [{"symbol": "AAPL", "action": "BUY", "quantity": 1, "fill_price": 100.0}],
            },
        ]

        performance = _build_signal_performance(history, {"AAPL": 90.0})
        self.assertEqual(performance["families"]["ai"]["status"], "underperforming")
        self.assertEqual(performance["families"]["conventional"]["status"], "underperforming")
        self.assertGreaterEqual(performance["families"]["ai"]["trades"], 5)

    def test_history_can_disable_underperforming_signals(self) -> None:
        policy = _signal_weights_from_history(
            [
                {
                    "signal_performance": {
                        "families": {
                            "ai": {"status": "underperforming"},
                            "conventional": {"status": "active"},
                        }
                    }
                }
            ]
        )

        self.assertEqual(policy["ai_weight"], 0.0)
        self.assertEqual(policy["conventional_weight"], 1.0)
        self.assertIn("ai", policy["disabled"])

    def test_collect_debug_issues_marks_no_fills_informational_when_no_executable_orders(self) -> None:
        decisions = [
            TradeDecision(
                symbol="AAPL",
                action="HOLD",
                confidence=0.5,
                quantity=0,
                reason="No strong signal",
                signals=[SignalSnapshot(family="ai", action="HOLD", confidence=0.5, details="")],
            )
        ]
        issues = _collect_debug_issues(
            news_count=0,
            ai_signal_count=0,
            news_debug=[],
            ai_debug=[{"status": "empty_input"}],
            decisions=decisions,
            fills=[],
            news_failure=None,
            ai_failure=None,
            execution_diagnostics={"sized_zero_reasons": {"non_buy_action": 1}, "executable_orders": 0},
        )

        self.assertIn("No fills were executed (informational: no executable orders)", issues)
        self.assertIn("All sized quantities were 0 (non_buy_action=1)", issues)

    def test_buy_quality_guard_rejects_negative_expectancy_buy(self) -> None:
        original_stop_loss = settings.stop_loss_pct
        original_take_profit = settings.take_profit_pct
        try:
            settings.stop_loss_pct = 0.08
            settings.take_profit_pct = 0.02
            guarded = _apply_buy_quality_guard(
                TradeDecision(
                    symbol="AAPL",
                    action="BUY",
                    confidence=0.55,
                    quantity=1,
                    reason="BUY signal",
                    signals=[SignalSnapshot(family="ai", action="BUY", confidence=0.55, details="")],
                ),
                fee_bps=5.0,
            )
        finally:
            settings.stop_loss_pct = original_stop_loss
            settings.take_profit_pct = original_take_profit

        self.assertEqual(guarded.action, "HOLD")
        self.assertEqual(guarded.quantity, 0.0)
        self.assertIn("negative expectancy", guarded.reason)


if __name__ == "__main__":
    unittest.main()
