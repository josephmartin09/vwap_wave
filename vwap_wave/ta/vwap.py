import pandas as pd


SESSION_VWAP_COLUMNS = [
    "session_vwap",
    "session_vwap_upper_1",
    "session_vwap_lower_1",
]
REQUIRED_COLUMNS = ["high", "low", "close", "volume"]


def calculate_session_vwap(frame, session_start):
    """Calculate session-anchored VWAP and one-standard-deviation bands.

    The calculation uses HLC3 as its price and population variance weighted by
    bar volume. The returned frame has the same index as ``frame``; values before
    ``session_start`` are NaN.
    """
    missing_columns = [
        column for column in REQUIRED_COLUMNS if column not in frame.columns
    ]
    if missing_columns:
        raise ValueError(
            "VWAP requires columns: " + ", ".join(missing_columns)
        )
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise TypeError("VWAP requires a DatetimeIndex")
    if frame.index.tz is None:
        raise ValueError("VWAP requires a timezone-aware index")

    anchor = pd.Timestamp(session_start)
    if anchor.tzinfo is None:
        raise ValueError("session_start must be timezone-aware")
    anchor = anchor.tz_convert(frame.index.tz)

    result = pd.DataFrame(
        index=frame.index,
        columns=SESSION_VWAP_COLUMNS,
        dtype=float,
    )
    session = frame.loc[frame.index >= anchor, REQUIRED_COLUMNS].astype(float)
    if session.empty:
        return result
    if session.isna().any().any():
        raise ValueError("VWAP input contains missing values")
    if (session["volume"] < 0).any():
        raise ValueError("VWAP input contains negative volume")

    price = (session["high"] + session["low"] + session["close"]) / 3.0
    volume = session["volume"]
    cumulative_volume = volume.cumsum().replace(0.0, float("nan"))

    vwap = (price * volume).cumsum() / cumulative_volume
    second_moment = (price.pow(2) * volume).cumsum() / cumulative_volume
    variance = (second_moment - vwap.pow(2)).clip(lower=0.0)
    standard_deviation = variance.pow(0.5)

    result.loc[session.index, "session_vwap"] = vwap
    result.loc[session.index, "session_vwap_upper_1"] = vwap + standard_deviation
    result.loc[session.index, "session_vwap_lower_1"] = vwap - standard_deviation
    return result
