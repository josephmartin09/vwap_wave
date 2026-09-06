import pandas as pd


INITIAL_BALANCE_COLUMNS = ["initial_balance_high", "initial_balance_low"]
REQUIRED_COLUMNS = ["high", "low"]


def calculate_initial_balance(frame, window_start, window_end):
    """Calculate developing and completed initial-balance levels.

    The window includes ``window_start`` and excludes ``window_end``. High and
    low develop during the window and remain fixed on subsequent rows.
    """
    missing_columns = [
        column for column in REQUIRED_COLUMNS if column not in frame.columns
    ]
    if missing_columns:
        raise ValueError(
            "Initial balance requires columns: " + ", ".join(missing_columns)
        )
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise TypeError("Initial balance requires a DatetimeIndex")
    if frame.index.tz is None:
        raise ValueError("Initial balance requires a timezone-aware index")

    start = pd.Timestamp(window_start)
    end = pd.Timestamp(window_end)
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("Initial-balance window must be timezone-aware")
    start = start.tz_convert(frame.index.tz)
    end = end.tz_convert(frame.index.tz)
    if end <= start:
        raise ValueError("Initial-balance window end must follow its start")

    result = pd.DataFrame(
        index=frame.index,
        columns=INITIAL_BALANCE_COLUMNS,
        dtype=float,
    )
    in_window = (frame.index >= start) & (frame.index < end)
    window = frame.loc[in_window, REQUIRED_COLUMNS].astype(float)
    if window.empty:
        return result
    if window.isna().any().any():
        raise ValueError("Initial-balance input contains missing values")

    result.loc[window.index, "initial_balance_high"] = window["high"].cummax()
    result.loc[window.index, "initial_balance_low"] = window["low"].cummin()

    after_window = frame.index >= end
    result.loc[after_window, "initial_balance_high"] = window["high"].max()
    result.loc[after_window, "initial_balance_low"] = window["low"].min()
    return result
