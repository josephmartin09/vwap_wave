from .base import Indicator, IndicatorContext, IndicatorResult
from .initial_balance import InitialBalanceIndicator
from .opus import OpusIndicator
from .volume_profile import VolumeProfileIndicator
from .vwap import SessionVwapIndicator


def default_indicators():
    """Create independent indicator instances with their constructor defaults."""
    return {
        "vwap": SessionVwapIndicator(),
        "initial_balance": InitialBalanceIndicator(),
        "volume_profile": VolumeProfileIndicator(),
        "opus": OpusIndicator(),
        "opus_15m": OpusIndicator(timeframe="15m"),
    }
