"""
Signal Generator — Quant Strategist + Market Analyst agent logic.
Generates trading signals from technical indicators.
"""

from dataclasses import dataclass
from enum import Enum

import pandas as pd

from utils.indicators import add_all_indicators, detect_volatility_regime


class SignalType(Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


@dataclass
class TradingSignal:
    signal_type: SignalType
    symbol: str
    entry_price: float
    stop_loss: float
    take_profit: float
    confidence: float          # 0.0 – 1.0
    leverage: int
    volatility_regime: str
    reason: str
    timestamp: pd.Timestamp


class SignalGenerator:
    """
    Implements the Quant Strategist's signal generation logic:
    - EMA crossover momentum
    - RSI confirmation
    - MACD histogram direction
    - Volume confirmation
    - Volatility regime adjustment
    """

    def __init__(self, config):
        self.config = config

    def generate_signals(self, df: pd.DataFrame, symbol: str) -> list[TradingSignal]:
        """
        Analyze a DataFrame of OHLCV data and return trading signals.
        The DataFrame should already have indicators added.
        """
        if len(df) < 200:
            return []

        df = add_all_indicators(df, self.config)
        signals = []

        # Iterate over the last portion of the data (simulating real-time)
        for i in range(200, len(df)):
            row = df.iloc[i]
            prev = df.iloc[i - 1]

            signal = self._evaluate_bar(row, prev, symbol, df, i)
            if signal is not None:
                signals.append(signal)

        return signals

    def evaluate_current(self, df: pd.DataFrame, symbol: str, global_idx: int | None = None) -> TradingSignal | None:
        """
        Evaluate the most recent bar for a signal.
        Used in live/paper trading mode.
        global_idx: the actual bar index in the full dataset (for cooldown tracking).
        """
        if len(df) < 200:
            return None

        df = add_all_indicators(df, self.config)
        row = df.iloc[-1]
        prev = df.iloc[-2]
        idx = global_idx if global_idx is not None else len(df) - 1
        return self._evaluate_bar(row, prev, symbol, df, idx)

    def _evaluate_bar(
        self, row: pd.Series, prev: pd.Series, symbol: str, df: pd.DataFrame, idx: int
    ) -> TradingSignal | None:
        """Evaluate a single bar for entry signals."""
        # Skip if any indicator is NaN
        required = ["ema_fast", "ema_slow", "ema_50", "rsi", "macd_hist", "atr",
                     "atr_percentile", "volume_ratio", "bb_upper", "bb_middle", "bb_lower"]
        for col in required:
            if pd.isna(row.get(col)):
                return None

        vol_regime = detect_volatility_regime(row["atr_percentile"], self.config)

        # In extreme volatility, go flat
        if vol_regime == "EXTREME":
            return None

        # Cooldown: skip if we traded this symbol recently
        cooldown = getattr(self.config, 'SIGNAL_COOLDOWN_BARS', 4)
        last_bar = getattr(self, '_last_signal_bar', {})
        if symbol in last_bar and (idx - last_bar[symbol]) < cooldown:
            return None

        long_signal = self._check_long(row, prev)

        signal = None
        if long_signal:
            signal = self._build_signal(SignalType.LONG, row, symbol, vol_regime, long_signal)

        if signal is not None:
            if not hasattr(self, '_last_signal_bar'):
                self._last_signal_bar = {}
            self._last_signal_bar[symbol] = idx

        return signal

    def _check_long(self, row: pd.Series, prev: pd.Series) -> str | None:
        """Check for long entry conditions. Returns reason string or None."""
        conditions = []
        score = 0

        # Hard filter: price must be above EMA 50 (trend alignment)
        if row["close"] < row["ema_50"]:
            return None

        # EMA crossover (or continuation)
        if row["ema_fast"] > row["ema_slow"]:
            conditions.append("EMA_BULL")
            score += 1
            if prev["ema_fast"] <= prev["ema_slow"]:
                conditions.append("EMA_CROSS_UP")
                score += 1

        # RSI confirmation — bullish momentum but not overbought
        if row["rsi"] > self.config.RSI_LONG_THRESHOLD and row["rsi"] < self.config.RSI_OVERBOUGHT:
            conditions.append(f"RSI={row['rsi']:.0f}")
            score += 1

        # MACD histogram positive
        if row["macd_hist"] > 0:
            conditions.append("MACD+")
            score += 1
            if prev["macd_hist"] <= 0:
                conditions.append("MACD_CROSS_UP")
                score += 1

        # Volume confirmation
        if row["volume_ratio"] > self.config.VOLUME_THRESHOLD:
            conditions.append(f"VOL={row['volume_ratio']:.1f}x")
            score += 1

        # BB momentum: price above middle band confirms uptrend
        bb_mid = row.get("bb_middle")
        if bb_mid is not None and not pd.isna(bb_mid) and row["close"] > bb_mid:
            conditions.append("BB_MID+")
            score += 1

        # Need at least 2 confirmations (EMA50 trend filter is the quality gate)
        if score >= 2:
            return " | ".join(conditions)
        return None

    def _check_short(self, row: pd.Series, prev: pd.Series) -> str | None:
        """Check for short entry conditions. Returns reason string or None."""
        conditions = []
        score = 0

        # Hard filter: price must be below EMA 50 (trend alignment)
        if row["close"] > row["ema_50"]:
            return None

        if row["ema_fast"] < row["ema_slow"]:
            conditions.append("EMA_BEAR")
            score += 1
            if prev["ema_fast"] >= prev["ema_slow"]:
                conditions.append("EMA_CROSS_DOWN")
                score += 1

        if row["rsi"] < self.config.RSI_SHORT_THRESHOLD and row["rsi"] > self.config.RSI_OVERSOLD:
            conditions.append(f"RSI={row['rsi']:.0f}")
            score += 1

        if row["macd_hist"] < 0:
            conditions.append("MACD-")
            score += 1
            if prev["macd_hist"] >= 0:
                conditions.append("MACD_CROSS_DOWN")
                score += 1

        if row["volume_ratio"] > self.config.VOLUME_THRESHOLD:
            conditions.append(f"VOL={row['volume_ratio']:.1f}x")
            score += 1

        # BB momentum: price below middle band confirms downtrend
        bb_mid = row.get("bb_middle")
        if bb_mid is not None and not pd.isna(bb_mid) and row["close"] < bb_mid:
            conditions.append("BB_MID-")
            score += 1

        if score >= 3:
            return " | ".join(conditions)
        return None

    def _build_signal(
        self,
        signal_type: SignalType,
        row: pd.Series,
        symbol: str,
        vol_regime: str,
        reason: str,
    ) -> TradingSignal:
        """Build a complete TradingSignal with SL/TP levels."""
        entry = row["close"]
        atr = row["atr"]

        # Scale ATR multiplier by volatility regime — wider stops in volatile markets
        vol_sl_scale = {"LOW": 1.0, "MEDIUM": 1.2, "HIGH": 1.5, "EXTREME": 2.0}
        sl_mult = self.config.ATR_SL_MULTIPLIER * vol_sl_scale.get(vol_regime, 1.2)

        if signal_type == SignalType.LONG:
            sl = entry - atr * sl_mult
            tp = entry + atr * sl_mult * self.config.REWARD_RISK_RATIO
        else:
            sl = entry + atr * sl_mult
            tp = entry - atr * sl_mult * self.config.REWARD_RISK_RATIO

        # Confidence: base 0.5 at 2 confirmations, +0.1 per extra
        reason_parts = reason.split(" | ")
        extra = max(0, len(reason_parts) - 2)
        confidence = min(1.0, 0.5 + extra * 0.1)

        # Leverage from vol regime — balanced for small account growth
        leverage_map = {"LOW": 15, "MEDIUM": 10, "HIGH": 7, "EXTREME": 3}
        leverage = leverage_map.get(vol_regime, 10)

        return TradingSignal(
            signal_type=signal_type,
            symbol=symbol,
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp,
            confidence=confidence,
            leverage=leverage,
            volatility_regime=vol_regime,
            reason=reason,
            timestamp=row.get("timestamp", pd.Timestamp.now("UTC")),
        )

    def get_market_summary(self, df: pd.DataFrame) -> dict:
        """
        Market Analyst agent: produce a summary of current market state.
        """
        if len(df) < 50:
            return {"state": "INSUFFICIENT_DATA"}

        df = add_all_indicators(df, self.config)
        row = df.iloc[-1]

        trend = "BULLISH" if row["ema_fast"] > row["ema_slow"] else "BEARISH"
        if abs(row["ema_fast"] - row["ema_slow"]) / row["close"] < 0.001:
            trend = "NEUTRAL"

        vol_regime = detect_volatility_regime(row["atr_percentile"], self.config)

        rsi_state = "NEUTRAL"
        if row["rsi"] > self.config.RSI_OVERBOUGHT:
            rsi_state = "OVERBOUGHT"
        elif row["rsi"] < self.config.RSI_OVERSOLD:
            rsi_state = "OVERSOLD"

        return {
            "state": trend,
            "rsi": round(row["rsi"], 1),
            "rsi_state": rsi_state,
            "macd_hist": round(row["macd_hist"], 4),
            "macd_direction": "POSITIVE" if row["macd_hist"] > 0 else "NEGATIVE",
            "volatility_regime": vol_regime,
            "atr": round(row["atr"], 2),
            "volume_ratio": round(row["volume_ratio"], 2),
            "ema_fast": round(row["ema_fast"], 2),
            "ema_slow": round(row["ema_slow"], 2),
            "bb_upper": round(row["bb_upper"], 2),
            "bb_lower": round(row["bb_lower"], 2),
            "close": round(row["close"], 2),
        }
