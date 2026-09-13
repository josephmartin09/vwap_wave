"""Clock-aligned futures candles, including the current forming candle."""

OHLCV = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
TIMEFRAMES = ("1h",)


def resample_candles(frame, timeframe):
    """Aggregate only supplied minutes; omit empty bins rather than filling gaps.

    Input timestamps label the start of each minute. UTC clock boundaries also
    align with Chicago's quarter hours and hours, including across DST changes.
    The final output candle may be partial, as may the first if history starts
    mid-bucket. Callers must not supply future minutes during replay.
    """
    if timeframe not in TIMEFRAMES:
        raise ValueError("Unsupported timeframe: " + timeframe)
    source = frame.loc[~frame.index.duplicated(keep="last"), list(OHLCV)].sort_index()
    return source.resample(timeframe, closed="left", label="left").agg(OHLCV).dropna(
        subset=["open", "high", "low", "close"]
    )
