"""
Technical indicators used by the strategy.
Uses TA-Lib for calculations.
"""

import numpy as np
import pandas as pd
import talib


def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return pd.Series(talib.EMA(series.values, timeperiod=period), index=series.index)


def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index."""
    return pd.Series(talib.RSI(series.values, timeperiod=period), index=series.index)


def calculate_macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """MACD line, signal line, and histogram."""
    macd, macd_signal, macd_hist = talib.MACD(
        series.values, fastperiod=fast, slowperiod=slow, signalperiod=signal
    )
    return (
        pd.Series(macd, index=series.index),
        pd.Series(macd_signal, index=series.index),
        pd.Series(macd_hist, index=series.index),
    )


def calculate_bollinger_bands(series: pd.Series, period: int = 20, std: float = 2.0):
    """Bollinger Bands: upper, middle, lower."""
    upper, middle, lower = talib.BBANDS(
        series.values, timeperiod=period, nbdevup=std, nbdevdn=std, matype=0
    )
    return (
        pd.Series(upper, index=series.index),
        pd.Series(middle, index=series.index),
        pd.Series(lower, index=series.index),
    )


def calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average True Range."""
    return pd.Series(
        talib.ATR(high.values, low.values, close.values, timeperiod=period),
        index=high.index,
    )


def calculate_obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume."""
    return pd.Series(talib.OBV(close.values, volume.values), index=close.index)


def calculate_volume_ratio(volume: pd.Series, period: int = 20) -> pd.Series:
    """Volume relative to its moving average."""
    avg_vol = volume.rolling(window=period).mean()
    return volume / avg_vol


def calculate_atr_percentile(atr: pd.Series, lookback: int = 100) -> pd.Series:
    """Rolling percentile rank of ATR for volatility regime detection."""
    def percentile_rank(window):
        if len(window) < 2:
            return 50.0
        current = window.iloc[-1]
        return (window < current).sum() / (len(window) - 1) * 100

    return atr.rolling(window=lookback).apply(percentile_rank, raw=False)


def add_all_indicators(df: pd.DataFrame, config) -> pd.DataFrame:
    """Add all technical indicators to a DataFrame with OHLCV columns."""
    df = df.copy()

    # EMAs
    df["ema_fast"] = calculate_ema(df["close"], config.EMA_FAST)
    df["ema_slow"] = calculate_ema(df["close"], config.EMA_SLOW)
    df["ema_50"] = calculate_ema(df["close"], 50)
    df["ema_200"] = calculate_ema(df["close"], 200)

    # RSI
    df["rsi"] = calculate_rsi(df["close"], config.RSI_PERIOD)

    # MACD
    df["macd"], df["macd_signal"], df["macd_hist"] = calculate_macd(
        df["close"], config.MACD_FAST, config.MACD_SLOW, config.MACD_SIGNAL
    )

    # Bollinger Bands
    df["bb_upper"], df["bb_middle"], df["bb_lower"] = calculate_bollinger_bands(
        df["close"], config.BB_PERIOD, config.BB_STD
    )

    # ATR
    df["atr"] = calculate_atr(df["high"], df["low"], df["close"], config.ATR_PERIOD)

    # Volatility regime
    df["atr_percentile"] = calculate_atr_percentile(df["atr"])

    # Volume
    df["obv"] = calculate_obv(df["close"], df["volume"])
    df["volume_ratio"] = calculate_volume_ratio(df["volume"])

    return df


def detect_volatility_regime(atr_percentile: float, config) -> str:
    """Classify current volatility regime."""
    if pd.isna(atr_percentile):
        return "MEDIUM"
    if atr_percentile <= config.VOL_LOW:
        return "LOW"
    elif atr_percentile <= config.VOL_MEDIUM:
        return "MEDIUM"
    elif atr_percentile <= config.VOL_HIGH:
        return "HIGH"
    else:
        return "EXTREME"
