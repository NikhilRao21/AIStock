from __future__ import annotations

from statistics import mean, pstdev
from typing import Dict

from aistock.core.types import ConventionalSignal


def _rsi_from_closes(closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains = []
    losses = []
    for i in range(-period, 0):
        delta = closes[i] - closes[i - 1]
        if delta > 0:
            gains.append(delta)
        else:
            losses.append(abs(delta))
    avg_gain = mean(gains) if gains else 0.0
    avg_loss = mean(losses) if losses else 0.0
    if avg_loss == 0 and avg_gain == 0:
        return 50.0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi


def _clip01(x: float) -> float:
    if x > 1:
        return 1.0
    if x < -1:
        return -1.0
    return x


def _ema(closes: list[float], period: int) -> float:
    if not closes:
        return 0.0
    alpha = 2.0 / (period + 1.0)
    value = closes[0]
    for close in closes[1:]:
        value = (alpha * close) + ((1.0 - alpha) * value)
    return value


def conventional_signal(symbol: str, closes: list[float]) -> ConventionalSignal:
    # require at least 21 closes like before
    if len(closes) < 21:
        raise ValueError(f"Need at least 21 closes for {symbol}")

    last = closes[-1]
    mom_5 = (last / closes[-6]) - 1.0
    mom_20 = (last / closes[-21]) - 1.0

    # moving averages
    ma5 = mean(closes[-5:])
    ma20 = mean(closes[-20:])
    ma_diff = (ma5 - ma20) / ma20 if ma20 != 0 else 0.0

    # RSI
    rsi14 = _rsi_from_closes(closes, period=14)

    # Bollinger-style z (20-day)
    try:
        std20 = pstdev(closes[-20:]) if len(closes[-20:]) >= 2 else 0.0
    except Exception:
        std20 = 0.0
    band_z = (last - ma20) / std20 if std20 > 0 else 0.0

    # per-method scores in [-1,1]
    scores: Dict[str, float] = {}
    # momentum scaled: assume 5% move is strong
    scores["momentum_5"] = _clip01(mom_5 / 0.05)
    scores["momentum_20"] = _clip01(mom_20 / 0.10)
    # ma crossover score
    scores["ma_crossover"] = _clip01(ma_diff / 0.02)
    # RSI: low -> buy positive, high -> sell negative
    if rsi14 < 35:
        scores["rsi"] = _clip01((35 - rsi14) / 35)
    elif rsi14 > 65:
        scores["rsi"] = _clip01(-((rsi14 - 65) / 35))
    else:
        scores["rsi"] = 0.0
    # bollinger/mean reversion score
    if band_z < -1.0:
        scores["bollinger"] = _clip01(min(1.0, (-1.0 - band_z) / 3.0))
    elif band_z > 1.0:
        scores["bollinger"] = _clip01(max(-1.0, -((band_z - 1.0) / 3.0)))
    else:
        scores["bollinger"] = 0.0

    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    macd_line = ema12 - ema26
    # Scale MACD relative to price level so it can be blended with other
    # normalized method scores in the same [-1, 1] range.
    macd_scale = abs(ma20) * 0.01 if ma20 else max(1e-6, abs(last) * 0.01)
    scores["macd"] = _clip01(macd_line / macd_scale) if macd_scale > 0 else 0.0

    lookback_20 = closes[-20:]
    low_20 = min(lookback_20)
    high_20 = max(lookback_20)
    range_20 = high_20 - low_20
    breakout_20 = 0.0 if range_20 <= 0 else (((last - low_20) / range_20) * 2.0) - 1.0
    scores["breakout_20"] = _clip01(breakout_20)

    # weights
    weights = {
        "momentum_5": 0.18,
        "momentum_20": 0.16,
        "ma_crossover": 0.16,
        "rsi": 0.16,
        "bollinger": 0.12,
        "macd": 0.12,
        "breakout_20": 0.10,
    }
    total_weight = sum(weights.values())
    combined = 0.0
    for k, w in weights.items():
        combined += scores.get(k, 0.0) * (w / total_weight)

    # thresholds: small positive/negative biases.
    if combined > 0.02:
        action = "BUY"
    elif combined < -0.02:
        action = "SELL"
    else:
        action = "HOLD"

    confidence = min(1.0, max(0.0, 0.4 + abs(combined) * 0.6))

    details = {
        "momentum_5d": mom_5,
        "momentum_20d": mom_20,
        "ma5": ma5,
        "ma20": ma20,
        "ma_diff": ma_diff,
        "rsi14": rsi14,
        "bollinger_z": band_z,
        "ema12": ema12,
        "ema26": ema26,
        "macd_line": macd_line,
        "breakout_20": breakout_20,
        "per_method_scores": scores,
    }

    return ConventionalSignal(
        symbol=symbol,
        action=action,
        confidence=confidence,
        momentum_5d=mom_5,
        momentum_20d=mom_20,
        details=details,
    )
