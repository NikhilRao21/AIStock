from __future__ import annotations

import unittest

from aistock.broker.paper_broker import PaperBroker


class SellFlowTests(unittest.TestCase):
    def test_partial_and_full_sell_updates_positions_and_cash(self) -> None:
        # start with a position of 2 shares at avg cost 50 and $100 cash
        state = {"cash": 100.0, "fee_bps": 0.0, "positions": {"AAPL": {"quantity": 2.0, "avg_cost": 50.0}}}
        broker = PaperBroker.from_state(state, fallback_starting_cash=100.0)

        # partial sell 1 share at price 60 -> cash increases by 60
        fill = broker.sell("AAPL", 1.0, 60.0)
        self.assertIsNotNone(fill)
        self.assertEqual(fill.action, "SELL")
        self.assertAlmostEqual(broker.cash, 160.0)
        # remaining position should be 1 share
        remaining = getattr(broker, "_positions", {}).get("AAPL")
        self.assertIsNotNone(remaining)
        self.assertAlmostEqual(remaining.quantity, 1.0)

        # sell remaining share -> position removed
        fill2 = broker.sell("AAPL", 1.0, 55.0)
        self.assertIsNotNone(fill2)
        self.assertAlmostEqual(broker.cash, 215.0)
        remaining2 = getattr(broker, "_positions", {}).get("AAPL")
        self.assertIsNone(remaining2)


if __name__ == "__main__":
    unittest.main()
