import pandas as pd

from .base import Indicator, IndicatorContext, IndicatorResult
from ..ta.initial_balance import INITIAL_BALANCE_COLUMNS, calculate_initial_balance


class InitialBalanceIndicator(Indicator):
    def calculate(self, context: IndicatorContext) -> IndicatorResult:
        frame = context.candles
        if frame.empty:
            return IndicatorResult(pd.DataFrame(index=frame.index, columns=INITIAL_BALANCE_COLUMNS, dtype=float))
        start, end = context.session_schedule.initial_balance_window_for(context.symbol, frame.index[-1])
        return IndicatorResult(calculate_initial_balance(frame, start, end))
