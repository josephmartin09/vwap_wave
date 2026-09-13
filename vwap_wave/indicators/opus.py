import pandas as pd

from .base import Indicator, IndicatorContext, IndicatorResult
from ..resampling import TIMEFRAMES
from ..ta.opus import Trend, process_candles


class OpusIndicator(Indicator):
    def __init__(self, timeframe="1h", lookback=2000):
        if timeframe not in TIMEFRAMES:
            raise ValueError("Unsupported Opus timeframe: " + timeframe)
        if isinstance(lookback, bool) or not isinstance(lookback, int) or lookback < 2:
            raise ValueError("Opus lookback must be at least 2 candles")
        self.timeframe = timeframe
        self.lookback = lookback

    def calculate(self, context: IndicatorContext) -> IndicatorResult[Trend]:
        frame = context.candles
        candles = frame.tail(self.lookback).rename_axis("time").reset_index()
        result = process_candles(list(candles.itertuples(index=False)))
        trend = result["trends"][-1] if result["trends"] else None
        levels = pd.DataFrame(index=frame.index[-1:], columns=["change_level", "sweep_level"], dtype=float)
        if trend is not None and not levels.empty:
            levels.iloc[-1] = [trend.change_level, trend.sweep_level]
        return IndicatorResult(levels, trend)
