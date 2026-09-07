import logging
import time

import pandas as pd

from . import log
from .catalog import INDICATOR_COLUMNS, SYMBOLS, require_catalog_symbols
from .commands import (
    ReplaceAlertConditions,
    ShowAlertConditions,
    UnixCommandServer,
)
from .schwab.feed import SchwabBarFeed
from .sessions import SessionSchedule
from .ta.initial_balance import INITIAL_BALANCE_COLUMNS, calculate_initial_balance
from .ta.volume_profile import VOLUME_PROFILE_COLUMNS, calculate_volume_profile
from .ta.vwap import SESSION_VWAP_COLUMNS, calculate_session_vwap
from .telegram_alert import alerts_from_env


class VwapWaveApp:
    BAR_COLUMNS = ["open", "high", "low", "close", "volume"]

    def __init__(
        self,
        symbols=None,
        reconnect_delay_seconds=5.0,
        session_schedule=None,
        volume_profile_bins=100,
        value_area_percent=0.70,
        command_server=None,
        telegram_alerts=None,
    ):
        requested_symbols = SYMBOLS if symbols is None else symbols
        self.symbols = list(require_catalog_symbols(requested_symbols))
        self.reconnect_delay_seconds = reconnect_delay_seconds
        self.session_schedule = (
            SessionSchedule.from_json()
            if session_schedule is None
            else session_schedule
        )
        self.volume_profile_bins = volume_profile_bins
        self.value_area_percent = value_area_percent
        self.command_server = command_server
        self.frames = {}
        self.volume_profiles = {}
        self.alert_conditions = {symbol: () for symbol in self.symbols}
        self._last_alerted_bars = {}
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        self.telegram_alerts = (
            alerts_from_env(self.symbols, logger=self.logger)
            if telegram_alerts is None
            else telegram_alerts
        )

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
        self.logger.debug(
            "LIVE %s @ %s O=%s H=%s L=%s C=%s vol=%s",
            bar["symbol"],
            bar["datetime"],
            bar["open"],
            bar["high"],
            bar["low"],
            bar["close"],
            bar["volume"],
        )
        self.evaluate_alert_conditions(bar["symbol"])

    def evaluate_alert_conditions(self, symbol):
        frame = self.frames[symbol]
        if frame.empty:
            return

        row = frame.iloc[-1]
        low_price = row["low"]
        high_price = row["high"]
        if pd.isna(low_price) or pd.isna(high_price):
            return

        bar_timestamp = frame.index[-1]
        for condition in self.alert_conditions[symbol]:
            if condition not in row.index or pd.isna(row[condition]):
                continue

            level = row[condition]
            if not low_price <= level <= high_price:
                continue

            alert_key = (symbol, condition)
            if self._last_alerted_bars.get(alert_key) == bar_timestamp:
                continue
            self._last_alerted_bars[alert_key] = bar_timestamp
            self.logger.warning(
                "ALERT %s touched %s @ %s level=%s range=%s-%s",
                symbol,
                condition,
                bar_timestamp,
                level,
                low_price,
                high_price,
            )
            telegram_alert = self.telegram_alerts.get(symbol)
            if telegram_alert is not None:
                telegram_alert.send(
                    self.format_alert_message(
                        symbol,
                        condition,
                        bar_timestamp,
                        level,
                        low_price,
                        high_price,
                    )
                )

    @staticmethod
    def format_alert_message(
        symbol,
        condition,
        bar_timestamp,
        level,
        low_price,
        high_price,
    ):
        return (
            f"🔔 {symbol} touched {condition}\n"
            f"Time: {bar_timestamp.isoformat()}\n"
            f"Level: {level}\n"
            f"Bar range: {low_price}–{high_price}"
        )

    def process_cli_commands(self):
        if self.command_server is None:
            return

        while True:
            received = self.command_server.receive_nowait()
            if received is None:
                return
            if received.rejection is not None:
                self.logger.warning("COMMAND REJECTED: %s", received.rejection)
                continue

            command = received.command
            rejection = self.validate_cli_command(command)
            if rejection is not None:
                self.logger.warning("COMMAND REJECTED: %s", rejection)
                continue

            self.apply_cli_command(command)

    def validate_cli_command(self, command):
        if isinstance(command, ReplaceAlertConditions):
            if command.symbol not in self.symbols:
                return "unknown symbol: {}".format(command.symbol)
            for condition in command.conditions:
                if condition not in INDICATOR_COLUMNS:
                    return "unknown indicator: {}".format(condition)
            return None
        if isinstance(command, ShowAlertConditions):
            if command.symbol not in self.symbols:
                return "unknown symbol: {}".format(command.symbol)
            return None
        return "unsupported command"

    def apply_cli_command(self, command):
        self.logger.info("COMMAND ACK: %r", command)

        if isinstance(command, ReplaceAlertConditions):
            self.alert_conditions[command.symbol] = command.conditions
            self._last_alerted_bars = {
                key: timestamp
                for key, timestamp in self._last_alerted_bars.items()
                if key[0] != command.symbol
            }

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
            self.logger.info("Historical %s data loaded and printed.", symbol)

    def run_feed(self):
        with SchwabBarFeed(self.symbols) as feed:
            self.load_history(feed)
            self.logger.info(
                "Polling live 1m updates for %s", ", ".join(self.symbols)
            )
            while True:
                self.process_cli_commands()
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
    with UnixCommandServer() as command_server:
        VwapWaveApp(SYMBOLS, command_server=command_server).run()


if __name__ == "__main__":
    main()
