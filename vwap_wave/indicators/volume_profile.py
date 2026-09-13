import pandas as pd

from .base import Indicator, IndicatorContext, IndicatorResult
from ..ta.volume_profile import VOLUME_PROFILE_COLUMNS, VolumeProfile, calculate_volume_profile


class VolumeProfileIndicator(Indicator):
    def __init__(self, bins=100, value_area_percent=0.70):
        if isinstance(bins, bool) or not isinstance(bins, int) or bins <= 0:
            raise ValueError("bins must be a positive integer")
        if not 0 < value_area_percent <= 1:
            raise ValueError("value_area_percent must be greater than 0 and at most 1")
        self.bins = bins
        self.value_area_percent = value_area_percent

    def calculate(self, context: IndicatorContext) -> IndicatorResult[VolumeProfile]:
        frame = context.candles
        levels = pd.DataFrame(index=frame.index[-1:], columns=VOLUME_PROFILE_COLUMNS, dtype=float)
        if frame.empty:
            return IndicatorResult(levels)
        start = context.session_schedule.start_for(context.symbol, frame.index[-1])
        profile = calculate_volume_profile(frame, start, self.bins, self.value_area_percent)
        if profile is not None:
            levels.iloc[-1] = [profile.point_of_control, profile.value_area_high, profile.value_area_low]
        return IndicatorResult(levels, profile)
