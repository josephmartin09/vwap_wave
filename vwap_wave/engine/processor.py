import logging

import pandas as pd

from ..config import DEFAULT_SCHEDULE
from ..alerts import ALERT_CONDITIONS
from ..config.alerts import load_default_conditions
from ..resampling import TIMEFRAMES, resample_candles
from ..indicators import Indicator, IndicatorContext, default_indicators
from ..ta.opus import UP, Trend
from ..ta.volume_profile import VolumeProfile


class Engine:
    BAR_COLUMNS = ["open", "high", "low", "close", "volume"]

    def __init__(
        self,
        symbols=None,
        session_schedule=None,
        indicators=None,
        alert_conditions=None,
    ):
        self.session_schedule = DEFAULT_SCHEDULE if session_schedule is None else session_schedule
        requested_symbols = self.session_schedule.symbols if symbols is None else symbols
        self.symbols = list(self.session_schedule.require_symbols(requested_symbols))
        self.indicators = dict(default_indicators() if indicators is None else indicators)
        for name, indicator in self.indicators.items():
            if not isinstance(indicator, Indicator):
                raise TypeError(f"{name} must implement Indicator")
            if indicator.timeframe not in ("1min", *TIMEFRAMES):
                raise ValueError("Unsupported indicator timeframe: " + indicator.timeframe)
        self.frames = {}
        self.resampled_frames = {}
        self.results = {}
        self.recent_sweep_alerts = []
        self.recent_alerts = []
        self._last_sweep_alerted_bars = {}
        alert_conditions = load_default_conditions() if alert_conditions is None else tuple(alert_conditions)
        self._last_alerted_bars = {}
        self.alert_conditions = {}
        for symbol in self.symbols:
            self.set_alert_conditions(symbol, alert_conditions)
        self._last_alerted_bars = {}
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)

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

    def append_bar(self, bar):
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
        frame.sort_index(inplace=True)

    def resample_symbol(self, symbol):
        timeframes = dict.fromkeys(
            indicator.timeframe for indicator in self.indicators.values()
            if indicator.timeframe != "1min"
        )
        self.resampled_frames[symbol] = {
            timeframe: resample_candles(self.frames[symbol], timeframe)
            for timeframe in timeframes
        }

    def apply_indicators(self, symbol):
        frame = self.frames[symbol]
        source = frame[self.BAR_COLUMNS]
        results = {}
        for name, indicator in self.indicators.items():
            candles = (source if indicator.timeframe == "1min"
                       else self.resampled_frames[symbol][indicator.timeframe])
            context = IndicatorContext(symbol, candles, self.session_schedule)
            result = indicator.calculate(context)
            results[name] = result
            if indicator.timeframe == "1min":
                for column in result.levels.columns:
                    if column in self.BAR_COLUMNS:
                        raise ValueError(f"Indicator {name} cannot overwrite {column}")
                    if column not in frame:
                        frame[column] = float("nan")
                    frame.loc[result.levels.index, column] = result.levels[column]
        self.results[symbol] = results

    @property
    def opus_trends(self):
        """Trend view for sweep alerts and replay reporting."""
        return {
            symbol: {
                self.indicators[name].timeframe: result.detail
                for name, result in results.items()
                if isinstance(result.detail, Trend)
            }
            for symbol, results in self.results.items()
        }

    @property
    def volume_profiles(self):
        """Profile view retained for consumers of the full distribution."""
        return {
            symbol: result.detail
            for symbol, results in self.results.items()
            for result in results.values()
            if isinstance(result.detail, VolumeProfile)
        }

    def process_bar(self, bar):
        if bar["symbol"] not in self.symbols:
            raise ValueError("Unknown symbol: " + bar["symbol"])
        self.recent_alerts = []
        self.recent_sweep_alerts = []
        self.append_bar(bar)
        self.resample_symbol(bar["symbol"])
        self.apply_indicators(bar["symbol"])
        self.logger.debug(
            "BAR %s @ %s O=%s H=%s L=%s C=%s vol=%s",
            bar["symbol"],
            bar["datetime"],
            bar["open"],
            bar["high"],
            bar["low"],
            bar["close"],
            bar["volume"],
        )
        self.evaluate_alert_conditions(bar["symbol"])
        self.evaluate_sweep_alerts(bar["symbol"])
        return tuple(self.recent_alerts)

    def evaluate_sweep_alerts(self, symbol):
        for timeframe, trend in self.opus_trends.get(symbol, {}).items():
            condition = "sweep_" + timeframe
            if condition not in self.alert_conditions[symbol]:
                continue
            if trend is None or trend.sweep_level is None:
                continue
            candle_start = self.resampled_frames[symbol][timeframe].index[-1]
            key = (symbol, timeframe)
            previous = self._last_sweep_alerted_bars.get(key)
            if previous is not None and candle_start <= previous:
                continue
            self._last_sweep_alerted_bars[key] = candle_start
            direction = "UP" if trend.dir == UP else "DOWN"
            source_minute = self.frames[symbol].index[-1]
            event = {
                "source_minute": source_minute.isoformat(),
                "symbol": symbol,
                "timeframe": timeframe,
                "candle_start": candle_start.isoformat(),
                "trend_direction": direction,
                "change_level": trend.change_level,
                "sweep_level": trend.sweep_level,
            }
            self.recent_sweep_alerts.append(event)
            self.logger.warning("SWEEP ALERT %s", event)
            self.recent_alerts.append({"kind": "sweep", **event})

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
            self.recent_alerts.append({
                "kind": "touch", "symbol": symbol, "condition": condition,
                "source_minute": bar_timestamp.isoformat(), "level": level,
                "low": low_price, "high": high_price,
            })

    def set_alert_conditions(self, symbol, conditions):
        if symbol not in self.symbols:
            raise ValueError("Unknown symbol: " + symbol)
        conditions = tuple(conditions)
        unknown = set(conditions) - set(ALERT_CONDITIONS)
        if unknown:
            raise ValueError("Unknown alert conditions: " + ", ".join(sorted(unknown)))
        self.alert_conditions[symbol] = conditions
        self._last_alerted_bars = {key: value for key, value in self._last_alerted_bars.items()
                                   if key[0] != symbol}

    def warmup(self, history):
        """Replace candle state from historical frames without producing alerts.

        Preserve alert deduplication across reconnects.
        """
        self.frames = {}
        self.resampled_frames = {}
        self.results = {}
        self.recent_alerts = []
        self.recent_sweep_alerts = []
        for symbol in self.symbols:
            frame = history.get(symbol)
            self.frames[symbol] = self.candles_to_df(None) if frame is None else frame.copy()
            self.resample_symbol(symbol)
            self.apply_indicators(symbol)
