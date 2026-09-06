import logging
import time

import pandas as pd

from . import log
from .schwab.feed import SchwabBarFeed
from .sessions import SessionSchedule
from .ta.initial_balance import INITIAL_BALANCE_COLUMNS, calculate_initial_balance
from .ta.volume_profile import VOLUME_PROFILE_COLUMNS, calculate_volume_profile
from .ta.vwap import SESSION_VWAP_COLUMNS, calculate_session_vwap

SYMBOLS = [
    "/ES",
    "/CL",
    "/GC"
]

class VwapWaveApp:
    BAR_COLUMNS = ["open", "high", "low", "close", "volume"]

    def __init__(
        self,
        symbols=None,
        reconnect_delay_seconds=5.0,
        session_schedule=None,
        volume_profile_bins=100,
        value_area_percent=0.70,
    ):
        self.symbols = list(symbols) if symbols is not None else []
        self.reconnect_delay_seconds = reconnect_delay_seconds
        self.session_schedule = (
            SessionSchedule.from_json()
            if session_schedule is None
            else session_schedule
        )
        self.volume_profile_bins = volume_profile_bins
        self.value_area_percent = value_area_percent
        self.frames = {}
        self.volume_profiles = {}
        self.logger = logging.getLogger(__name__)

    def candles_to_df(self, candles):
        if not candles:
            return pd.DataFrame(
                columns=self.BAR_COLUMNS,
                index=pd.DatetimeIndex([], name="datetime", tz="UTC"),
            )

        df = pd.DataFrame(candles)
        if df.empty:
            return df

        df["datetime"] = pd.to_datetime(df["datetime"], unit="ms", utc=True)
        df.set_index("datetime", inplace=True)
        df = df[~df.index.duplicated(keep="last")]
        df.sort_index(inplace=True)
        return df[self.BAR_COLUMNS]

    def append_live_bar(self, bar):
        symbol = bar["symbol"]
        frame = self.frames.get(symbol)
        if frame is None:
            frame = self.candles_to_df(None)
            self.frames[symbol] = frame

        timestamp = pd.Timestamp(bar["datetime"])
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize("UTC")
        else:
            timestamp = timestamp.tz_convert("UTC")

        frame.loc[timestamp, self.BAR_COLUMNS] = [
            bar[column] for column in self.BAR_COLUMNS
        ]

    def apply_indicators(self, symbol):
        frame = self.frames[symbol]
        if frame.empty:
            return

        session_start = self.session_schedule.start_for(symbol, frame.index[-1])
        frame[SESSION_VWAP_COLUMNS] = calculate_session_vwap(frame, session_start)
        initial_balance_start, initial_balance_end = (
            self.session_schedule.initial_balance_window_for(
                symbol, frame.index[-1]
            )
        )
        frame[INITIAL_BALANCE_COLUMNS] = calculate_initial_balance(
            frame,
            initial_balance_start,
            initial_balance_end,
        )
        volume_profile = calculate_volume_profile(
            frame,
            session_start,
            bin_count=self.volume_profile_bins,
            value_area_percent=self.value_area_percent,
        )
        if volume_profile is not None:
            self.volume_profiles[symbol] = volume_profile
            values = [
                volume_profile.point_of_control,
                volume_profile.value_area_high,
                volume_profile.value_area_low,
            ]
            for column, value in zip(VOLUME_PROFILE_COLUMNS, values):
                frame.at[frame.index[-1], column] = value
        else:
            self.volume_profiles.pop(symbol, None)

    def on_live_bar(self, bar):
        self.append_live_bar(bar)
        self.apply_indicators(bar["symbol"])
        self.logger.info(
            "LIVE %s @ %s O=%s H=%s L=%s C=%s vol=%s",
            bar["symbol"],
            bar["datetime"],
            bar["open"],
            bar["high"],
            bar["low"],
            bar["close"],
            bar["volume"],
        )

    def load_history(self, feed):
        self.frames = {}
        self.volume_profiles = {}
        history = feed.get_historical_1m()
        for symbol, raw in history.items():
            if raw is None:
                self.logger.warning(
                    "No historical candle data returned for %s", symbol
                )
                self.frames[symbol] = self.candles_to_df(None)
                continue

            frame = self.candles_to_df(raw)
            self.frames[symbol] = frame
            self.apply_indicators(symbol)
            self.logger.info("\n%s", frame.tail(10))
            self.logger.info("Historical %s data loaded and printed.", symbol)

    def run_feed(self):
        with SchwabBarFeed(self.symbols) as feed:
            self.load_history(feed)
            self.logger.info(
                "Polling live 1m updates for %s", ", ".join(self.symbols)
            )
            while True:
                bar = feed.poll(timeout=1.0)
                if bar is not None:
                    self.on_live_bar(bar)

    def run(self):
        try:
            while True:
                try:
                    self.run_feed()
                except Exception:
                    self.logger.exception(
                        "Feed failed; rebuilding in %s seconds",
                        self.reconnect_delay_seconds,
                    )
                    time.sleep(self.reconnect_delay_seconds)
        except KeyboardInterrupt:
            self.logger.info("Stopping")


def main():
    log.setup_logging()
    VwapWaveApp(SYMBOLS).run()


if __name__ == "__main__":
    main()
