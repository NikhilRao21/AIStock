from __future__ import annotations

import unittest

from aistock.signals.conventional import conventional_signal


class ConventionalSignalsTests(unittest.TestCase):
    def test_momentum_and_ma_trigger_buy(self) -> None:
        # Construct a rising series
        closes = [100 + i for i in range(30)]
        sig = conventional_signal("MOCK", closes)
        self.assertIn(sig.action, {"BUY", "HOLD"})
        self.assertGreaterEqual(sig.confidence, 0.0)
        self.assertIsInstance(sig.details, dict)

    def test_downtrend_triggers_sell(self) -> None:
        closes = [200 - i for i in range(30)]
        sig = conventional_signal("MOCK", closes)
        self.assertIn(sig.action, {"SELL", "HOLD"})


if __name__ == "__main__":
    unittest.main()
