"""Fetch fresh Schwab 1m history and replay without Telegram or a live stream.

Example:
    pipenv run python -m vwap_wave.replay --symbol /ES --output replay.csv

Each completed minute is replayed at its close; ticks within that minute cannot
be recreated. The current unclosed minute is excluded. Candle output includes
forming hourly candles, and OUTPUT_STEM_alerts.csv records sweep alerts.
Use matching historical coverage and Opus lookback when comparing with Pine.
"""

import argparse
import asyncio
import csv
from pathlib import Path

import pandas as pd

from ..engine import Engine
from ..indicators import OpusIndicator, default_indicators
from ..alerts import ALERT_CONDITIONS, DEFAULT_CONDITIONS
from ..resampling import OHLCV


async def fetch_minutes(symbol):
    from ..schwab.client import SchwabClient

    return await SchwabClient().get_historical_1m(symbol)


def replay_minutes(app, symbol, frame, history=None):
    """Process historical bars through the same engine used by live input.

    Optional history seeds the engine without alerts and must precede the replay.
    """
    if symbol not in app.symbols:
        raise ValueError("Symbol is not configured in this engine: " + symbol)
    if history is not None:
        if not frame.empty:
            for seed in history.values():
                if seed is not None and not seed.empty and seed.index.max() >= frame.index.min():
                    raise ValueError("Warmup history must precede replay bars")
        app.warmup(history)
    for timestamp, row in frame.sort_index().iterrows():
        app.process_bar({"symbol": symbol, "datetime": timestamp, **row.to_dict()})
        yield timestamp


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", required=True, help="Configured futures symbol, e.g. /ES")
    parser.add_argument("--output", type=Path, default=Path("replay.csv"))
    parser.add_argument("--alerts-output", type=Path, help="Defaults to OUTPUT_STEM_alerts.csv")
    parser.add_argument("--opus-lookback", type=int, default=2000,
                        help="Higher-timeframe candles used by Opus (Pine default: 2000)")
    parser.add_argument("--conditions", nargs="*", choices=ALERT_CONDITIONS, default=DEFAULT_CONDITIONS)
    args = parser.parse_args()
    alerts_output = args.alerts_output or args.output.with_name(args.output.stem + "_alerts.csv")
    if args.output.resolve() == alerts_output.resolve():
        parser.error("Candle output and alert output must be different files")
    indicators = default_indicators()
    indicators["opus"] = OpusIndicator(lookback=args.opus_lookback)
    app = Engine(symbols=[args.symbol], indicators=indicators, alert_conditions=args.conditions)
    # Capture the cutoff before fetching so every replayed minute is complete.
    cutoff = pd.Timestamp.now(tz="UTC").floor("min")
    print(f"Fetching fresh 1m history for {args.symbol}...")
    frame = app.candles_to_df(asyncio.run(fetch_minutes(args.symbol)))
    frame = frame.loc[frame.index < cutoff]
    if frame.empty:
        parser.error("Schwab returned no completed 1m candles to replay")
    print(f"Replaying {len(frame)} minutes: {frame.index[0]} through {frame.index[-1]}")
    fields = ["available_at", "symbol", "timeframe", "candle_start", *OHLCV,
              "trend_direction", "change_level", "sweep_level", "sweep_alert"]
    alert_fields = ["available_at", "source_minute", "symbol", "timeframe",
                    "candle_start", "trend_direction", "change_level", "sweep_level"]
    alert_count = 0
    with args.output.open("w", newline="") as output, alerts_output.open("w", newline="") as alerts:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        alert_writer = csv.DictWriter(alerts, fieldnames=alert_fields)
        alert_writer.writeheader()
        for timestamp in replay_minutes(app, args.symbol, frame):
            available_at = (timestamp + pd.Timedelta(minutes=1)).isoformat()
            for event in app.recent_sweep_alerts:
                alert_writer.writerow({"available_at": available_at, **event})
                alert_count += 1
            for timeframe, candles in app.resampled_frames[args.symbol].items():
                trend = app.opus_trends.get(args.symbol, {}).get(timeframe)
                writer.writerow({
                    "available_at": available_at,
                    "symbol": args.symbol,
                    "timeframe": timeframe,
                    "candle_start": candles.index[-1].isoformat(),
                    **candles.iloc[-1].to_dict(),
                    "trend_direction": ("UP" if trend.dir == 1 else "DOWN") if trend else "",
                    "change_level": trend.change_level if trend else None,
                    "sweep_level": trend.sweep_level if trend else None,
                    "sweep_alert": any(e["timeframe"] == timeframe for e in app.recent_sweep_alerts),
                })
    print(f"Replayed {len(frame)} minutes for {args.symbol}; wrote {args.output}")
    print(f"Recorded {alert_count} sweep alerts in {alerts_output}; Telegram disabled")


if __name__ == "__main__":
    main()
