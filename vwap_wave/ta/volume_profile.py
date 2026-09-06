import math
from dataclasses import dataclass

import pandas as pd


VOLUME_PROFILE_COLUMNS = ["session_poc", "session_vah", "session_val"]
REQUIRED_COLUMNS = ["open", "high", "low", "close", "volume"]


@dataclass(frozen=True)
class VolumeProfile:
    rows: pd.DataFrame
    point_of_control: float
    value_area_high: float
    value_area_low: float


def calculate_volume_profile(
    frame,
    session_start,
    bin_count=100,
    value_area_percent=0.70,
):
    """Calculate a developing volume profile for the current session.

    Bar volume is distributed among price bins in proportion to the overlap
    between each bin and the bar's high-low range. A zero-range bar assigns all
    of its volume to the bin containing its price.
    """
    _validate_inputs(frame, session_start, bin_count, value_area_percent)
    anchor = pd.Timestamp(session_start).tz_convert(frame.index.tz)
    session = frame.loc[frame.index >= anchor, REQUIRED_COLUMNS].astype(float)
    if session.empty:
        return None
    if session.isna().any().any():
        raise ValueError("Volume-profile input contains missing values")
    if (session["volume"] < 0).any():
        raise ValueError("Volume-profile input contains negative volume")
    if (session["high"] < session["low"]).any():
        raise ValueError("Volume-profile input contains a high below its low")

    profile_low = session["low"].min()
    profile_high = session["high"].max()
    if profile_high == profile_low:
        return _single_price_profile(session, profile_low)

    bin_width = (profile_high - profile_low) / bin_count
    bin_lows = [profile_low + index * bin_width for index in range(bin_count)]
    bin_highs = [price + bin_width for price in bin_lows]
    total_volume = [0.0] * bin_count
    up_volume = [0.0] * bin_count
    down_volume = [0.0] * bin_count

    for bar in session.itertuples():
        if bar.high == bar.low:
            bin_index = min(
                int((bar.high - profile_low) / bin_width),
                bin_count - 1,
            )
            allocations = [(bin_index, bar.volume)]
        else:
            first_bin = max(int((bar.low - profile_low) / bin_width), 0)
            last_bin = min(
                math.ceil((bar.high - profile_low) / bin_width) - 1,
                bin_count - 1,
            )
            overlaps = []
            for bin_index in range(first_bin, last_bin + 1):
                overlap = max(
                    0.0,
                    min(bar.high, bin_highs[bin_index])
                    - max(bar.low, bin_lows[bin_index]),
                )
                if overlap > 0:
                    overlaps.append((bin_index, overlap))

            total_overlap = sum(overlap for _, overlap in overlaps)
            allocations = [
                (bin_index, bar.volume * overlap / total_overlap)
                for bin_index, overlap in overlaps
            ]

        is_up_bar = bar.close >= bar.open
        for bin_index, allocated_volume in allocations:
            total_volume[bin_index] += allocated_volume
            if is_up_bar:
                up_volume[bin_index] += allocated_volume
            else:
                down_volume[bin_index] += allocated_volume

    rows = pd.DataFrame(
        {
            "bin_low": bin_lows,
            "bin_high": bin_highs,
            "price": [
                (low + high) / 2.0 for low, high in zip(bin_lows, bin_highs)
            ],
            "total_volume": total_volume,
            "up_volume": up_volume,
            "down_volume": down_volume,
        }
    )
    if rows["total_volume"].sum() == 0:
        return None
    return _profile_from_rows(rows, value_area_percent)


def _profile_from_rows(rows, value_area_percent):
    poc_index = int(rows["total_volume"].idxmax())
    low_index = poc_index
    high_index = poc_index
    included_volume = rows.at[poc_index, "total_volume"]
    target_volume = rows["total_volume"].sum() * value_area_percent

    while included_volume < target_volume:
        below_index = low_index - 1 if low_index > 0 else None
        above_index = high_index + 1 if high_index < len(rows) - 1 else None
        if below_index is None and above_index is None:
            break

        chosen_index = _choose_value_area_row(
            rows,
            poc_index,
            below_index,
            above_index,
        )
        included_volume += rows.at[chosen_index, "total_volume"]
        low_index = min(low_index, chosen_index)
        high_index = max(high_index, chosen_index)

    rows = rows.copy()
    rows["in_value_area"] = False
    rows.loc[low_index:high_index, "in_value_area"] = True
    return VolumeProfile(
        rows=rows,
        point_of_control=float(rows.at[poc_index, "price"]),
        value_area_high=float(rows.at[high_index, "bin_high"]),
        value_area_low=float(rows.at[low_index, "bin_low"]),
    )


def _choose_value_area_row(rows, poc_index, below_index, above_index):
    if below_index is None:
        return above_index
    if above_index is None:
        return below_index

    below_volume = rows.at[below_index, "total_volume"]
    above_volume = rows.at[above_index, "total_volume"]
    if above_volume > below_volume:
        return above_index
    if below_volume > above_volume:
        return below_index

    below_distance = poc_index - below_index
    above_distance = above_index - poc_index
    return below_index if below_distance < above_distance else above_index


def _single_price_profile(session, price):
    up_volume = session.loc[session["close"] >= session["open"], "volume"].sum()
    down_volume = session.loc[session["close"] < session["open"], "volume"].sum()
    rows = pd.DataFrame(
        {
            "bin_low": [price],
            "bin_high": [price],
            "price": [price],
            "total_volume": [up_volume + down_volume],
            "up_volume": [up_volume],
            "down_volume": [down_volume],
            "in_value_area": [True],
        }
    )
    return VolumeProfile(
        rows=rows,
        point_of_control=float(price),
        value_area_high=float(price),
        value_area_low=float(price),
    )


def _validate_inputs(frame, session_start, bin_count, value_area_percent):
    missing_columns = [
        column for column in REQUIRED_COLUMNS if column not in frame.columns
    ]
    if missing_columns:
        raise ValueError(
            "Volume profile requires columns: " + ", ".join(missing_columns)
        )
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise TypeError("Volume profile requires a DatetimeIndex")
    if frame.index.tz is None:
        raise ValueError("Volume profile requires a timezone-aware index")

    anchor = pd.Timestamp(session_start)
    if anchor.tzinfo is None:
        raise ValueError("session_start must be timezone-aware")
    if (
        isinstance(bin_count, bool)
        or not isinstance(bin_count, int)
        or bin_count <= 0
    ):
        raise ValueError("bin_count must be a positive integer")
    if not 0 < value_area_percent <= 1:
        raise ValueError("value_area_percent must be greater than 0 and at most 1")
