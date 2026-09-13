from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import List

UP = 1
DOWN = -1
HOAGIE_MIN_INSIDE_BARS = 2
TREND_ESTABLISHED = -100
TREND_CONTESTED = -101

@dataclass(slots=True)
class Hoagie:
    start_time: datetime
    end_time: datetime
    low: float
    high: float
    inside_bar_cnt: int = 0


@dataclass(slots=True)
class Leg:
    dir: int
    start_time: datetime
    end_time: datetime
    low: float
    high: float


@dataclass(slots=True)
class Trend:
    dir: int
    start_time: datetime
    end_time: datetime
    cont_level: float
    change_level: float
    prev_cont_level: float | None = None
    next_change_level: float | None = None
    state: int = 0
    # Pending sweep extreme; cleared when a return leg promotes it to change_level.
    sweep_level: float | None = None


@dataclass(slots=True)
class Box:
    high: float
    low: float


def calculate_bars(
    candles: List[object],
) -> tuple[list[int], list[Hoagie]]:
    if len(candles) < 2:
        first_dir = UP if candles and candles[0].open <= candles[0].close else DOWN
        return [first_dir], []

    bar_dirs: list[int] = []
    hoagies: list[Hoagie] = []
    hoagie_active = False
    curr_hoagie: Hoagie | None = None

    # Calculate the direction of the first bar
    bar_dirs.append(UP if candles[0].open <= candles[0].close else DOWN)

    for i in range(1, len(candles)):
        prev_bar = candles[i - 1]
        curr_bar = candles[i]

        if not hoagie_active:
            # Up Bar
            if (curr_bar.high > prev_bar.high) and (curr_bar.low > prev_bar.low):
                bar_dirs.append(UP)

            # Down Bar
            elif (curr_bar.low < prev_bar.low) and (curr_bar.high < prev_bar.high):
                bar_dirs.append(DOWN)

            # Inside Bar (creates hoagie)
            elif (curr_bar.high <= prev_bar.high) and (curr_bar.low >= prev_bar.low):
                bar_dirs.append(bar_dirs[-1])
                curr_hoagie = Hoagie(
                    start_time=prev_bar.time,
                    end_time=curr_bar.time,
                    low=prev_bar.low,
                    high=prev_bar.high,
                    inside_bar_cnt=1,
                )
                hoagie_active = True

            # Outside Bar
            else:
                bar_dirs.append(bar_dirs[-1])

        # Currently within a hoagie
        else:
            curr_hoagie.end_time = curr_bar.time

            # Up Bar
            if (curr_bar.high > curr_hoagie.high) and (curr_bar.low >= curr_hoagie.low):
                bar_dirs.append(UP)
                hoagie_active = False

            # Down Bar
            elif (curr_bar.low < curr_hoagie.low) and (curr_bar.high <= curr_hoagie.high):
                bar_dirs.append(DOWN)
                hoagie_active = False

            # Inside Bar
            elif (curr_bar.high <= curr_hoagie.high) and (curr_bar.low >= curr_hoagie.low):
                bar_dirs.append(bar_dirs[-1])
                curr_hoagie.inside_bar_cnt += 1

                # This is a special case: we're drawing the live/current bar.
                # inside_bar_cnt needs to be strictly greater than HOAGIE_MIN_INSIDE_BARS
                # because the last bar doesn't count toward the hoagie
                if (i == len(candles) - 1) and (curr_hoagie.inside_bar_cnt > HOAGIE_MIN_INSIDE_BARS):
                    hoagie_active = False

            # Outside Bar
            else:
                bar_dirs.append(bar_dirs[-1])
                hoagie_active = False

            if not hoagie_active and curr_hoagie:
                if curr_hoagie.inside_bar_cnt >= HOAGIE_MIN_INSIDE_BARS:
                    hoagies.append(curr_hoagie)
                curr_hoagie = None

    return bar_dirs, hoagies


def calculate_legs(candles: List[object], bar_dirs: list[int]) -> list[Leg]:
    if not candles or not bar_dirs:
        return []

    legs: list[Leg] = []

    # Determine the first leg direction by just assuming it's the direction of the bar
    first_bar = candles[0]
    curr_dir = bar_dirs[0]
    curr_leg = Leg(
        dir=curr_dir,
        start_time=first_bar.time,
        end_time=first_bar.time,
        low=first_bar.low,
        high=first_bar.high,
    )

    # Add each previous leg once a change in direction is detected
    for i in range(1, len(candles)):
        curr_bar = candles[i]
        curr_dir = bar_dirs[i]

        if curr_dir != curr_leg.dir:
            legs.append(curr_leg)
            if curr_dir == UP:
                curr_leg = Leg(
                    dir=curr_dir,
                    start_time=curr_leg.end_time,
                    end_time=curr_bar.time,
                    low=curr_leg.low,
                    high=curr_bar.high,
                )
            else:
                curr_leg = Leg(
                    dir=curr_dir,
                    start_time=curr_leg.end_time,
                    end_time=curr_bar.time,
                    low=curr_bar.high,
                    high=curr_leg.high,
                )

        if curr_dir == UP:
            if curr_bar.high > curr_leg.high:
                curr_leg.end_time = curr_bar.time
                curr_leg.high = curr_bar.high
        else:
            if curr_bar.low < curr_leg.low:
                curr_leg.end_time = curr_bar.time
                curr_leg.low = curr_bar.low

    # Add the last leg
    legs.append(curr_leg)
    return legs

def calculate_trends(legs: list[Leg]) -> list[Trend]:
    if not legs:
        return []

    trends: list[Trend] = []

    # To start the trend, we assume the first leg direction is the defining trend
    curr_leg = legs[0]
    if curr_leg.dir == UP:
        curr_trend = Trend(
            dir=UP,
            start_time=curr_leg.start_time,
            end_time=curr_leg.end_time,
            cont_level=curr_leg.high,
            change_level=curr_leg.low,
            prev_cont_level=curr_leg.high,
            next_change_level=curr_leg.low,
            state=TREND_CONTESTED
        )
    else:
        curr_trend = Trend(
            dir=DOWN,
            start_time=curr_leg.start_time,
            end_time=curr_leg.end_time,
            cont_level=curr_leg.low,
            change_level=curr_leg.high,
            prev_cont_level=curr_leg.low,
            next_change_level=curr_leg.high,
            state=TREND_CONTESTED
        )

    for i in range(1, len(legs)):
        curr_leg = legs[i]
        curr_trend.end_time = curr_leg.end_time

        if curr_trend.state == TREND_ESTABLISHED:
            if curr_trend.dir == UP:
                if curr_leg.dir == UP:
                    if curr_leg.high > curr_trend.cont_level:
                        curr_trend.prev_cont_level = curr_trend.cont_level
                        curr_trend.cont_level = curr_leg.high
                        curr_trend.change_level = curr_trend.next_change_level
                        curr_trend.next_change_level = curr_trend.cont_level
                else:  # curr_leg.dir == DOWN
                    if curr_leg.low < curr_trend.change_level:
                        curr_trend.sweep_level = curr_leg.low
                        curr_trend.next_change_level = curr_leg.low
                        curr_trend.state = TREND_CONTESTED
                    elif curr_leg.low < curr_trend.next_change_level:
                        curr_trend.next_change_level = curr_leg.low
            else:  # curr_trend.dir == DOWN
                if curr_leg.dir == DOWN:
                    if curr_leg.low < curr_trend.cont_level:
                        curr_trend.prev_cont_level = curr_trend.cont_level
                        curr_trend.cont_level = curr_leg.low
                        curr_trend.change_level = curr_trend.next_change_level
                        curr_trend.next_change_level = curr_trend.cont_level
                else:  # curr_leg.dir == UP
                    if curr_leg.high > curr_trend.change_level:
                        curr_trend.sweep_level = curr_leg.high
                        curr_trend.next_change_level = curr_leg.high
                        curr_trend.state = TREND_CONTESTED
                    elif curr_leg.high > curr_trend.next_change_level:
                        curr_trend.next_change_level = curr_leg.high

        else:  # TREND_CONTESTED
            if curr_trend.dir == UP:
                if curr_leg.dir == UP:
                    # The initial assumed trend has no sweep to promote.
                    if curr_trend.sweep_level is not None:
                        curr_trend.change_level = curr_trend.sweep_level
                        curr_trend.sweep_level = None
                    if curr_leg.high > curr_trend.cont_level:
                        curr_trend.prev_cont_level = curr_trend.cont_level
                        curr_trend.cont_level = curr_leg.high
                        curr_trend.change_level = curr_trend.next_change_level
                        curr_trend.next_change_level = curr_trend.cont_level
                        curr_trend.state = TREND_ESTABLISHED
                else:  # curr_leg.dir == DOWN
                    if curr_leg.low < curr_trend.change_level:
                        curr_trend.change_level = curr_trend.next_change_level
                        curr_trend.next_change_level = curr_leg.low
                        trends.append(curr_trend)
                        curr_trend = Trend(
                            dir=DOWN,
                            start_time=curr_leg.end_time,
                            end_time=curr_leg.end_time,
                            cont_level=curr_leg.low,
                            prev_cont_level=curr_trend.change_level,
                            change_level=curr_trend.prev_cont_level,
                            next_change_level=curr_trend.change_level,
                            state=TREND_ESTABLISHED
                        )
            else:  # curr_trend.dir == DOWN
                if curr_leg.dir == DOWN:
                    if curr_trend.sweep_level is not None:
                        curr_trend.change_level = curr_trend.sweep_level
                        curr_trend.sweep_level = None
                    if curr_leg.low < curr_trend.cont_level:
                        curr_trend.prev_cont_level = curr_trend.cont_level
                        curr_trend.cont_level = curr_leg.low
                        curr_trend.change_level = curr_trend.next_change_level
                        curr_trend.next_change_level = curr_trend.cont_level
                        curr_trend.state = TREND_ESTABLISHED
                else:  # curr_leg.dir == UP
                    if curr_leg.high > curr_trend.change_level:
                        curr_trend.change_level = curr_trend.next_change_level
                        curr_trend.next_change_level = curr_leg.high
                        trends.append(curr_trend)
                        curr_trend = Trend(
                            dir=UP,
                            start_time=curr_leg.end_time,
                            end_time=curr_leg.end_time,
                            cont_level=curr_leg.high,
                            prev_cont_level=curr_trend.change_level,
                            change_level=curr_trend.prev_cont_level,
                            next_change_level=curr_trend.change_level,
                            state=TREND_ESTABLISHED
                        )

    trends.append(curr_trend)
    return trends

def calculate_boxes(trends : list[Trend]) -> list[Box]:
    boxes = []
    for trend in trends:
        if trend.dir == UP:
            boxes.append(Box(trend.prev_cont_level, trend.change_level))
        else:
            boxes.append(Box(trend.change_level, trend.prev_cont_level))
    return boxes


def process_candles(candles):
    (bar_dirs, hoagies) = calculate_bars(candles)
    legs = calculate_legs(candles, bar_dirs)
    trends  = calculate_trends(legs)
    boxes = calculate_boxes(trends)

    return {
        "bar_dirs": bar_dirs,
        "legs": legs,
        "trends": trends,
        "boxes": boxes
    }
