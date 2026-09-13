import pandas as pd

from .base import Indicator, IndicatorContext, IndicatorResult
from ..ta.vwap import SESSION_VWAP_COLUMNS, calculate_session_vwap


class SessionVwapIndicator(Indicator):
    def calculate(self, context: IndicatorContext) -> IndicatorResult:
        frame = context.candles
        if frame.empty:
            return IndicatorResult(pd.DataFrame(index=frame.index, columns=SESSION_VWAP_COLUMNS, dtype=float))
        start = context.session_schedule.start_for(context.symbol, frame.index[-1])
        return IndicatorResult(calculate_session_vwap(frame, start))
