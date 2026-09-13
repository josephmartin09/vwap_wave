import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


DEFAULT_CONFIG_PATH = Path(__file__).with_name("sessions.json")


class SessionSchedule:
    def __init__(self, profiles=None, symbols=None):
        if profiles is None or symbols is None:
            with DEFAULT_CONFIG_PATH.open() as config_file:
                config = json.load(config_file)
            profiles = config["profiles"] if profiles is None else profiles
            symbols = config["symbols"] if symbols is None else symbols
        self._profiles = profiles
        self._symbols = symbols

    @classmethod
    def from_json(cls, path=DEFAULT_CONFIG_PATH):
        with Path(path).open() as config_file:
            config = json.load(config_file)
        return cls(config["profiles"], config["symbols"])

    @property
    def symbols(self):
        """Return the symbols configured by the session file."""
        return tuple(self._symbols)

    def require_symbols(self, symbols):
        requested = (symbols,) if isinstance(symbols, str) else tuple(symbols)
        unknown = [symbol for symbol in requested if symbol not in self.symbols]
        if unknown:
            raise ValueError("Symbols not configured: " + ", ".join(unknown))
        return requested

    def start_for(self, symbol, timestamp):
        """Return the most recent configured session start for a timestamp."""
        try:
            profile_name = self._symbols[symbol]["session_profile"]
            profile = self._profiles[profile_name]
        except KeyError as error:
            raise ValueError(f"No session profile configured for {symbol}") from error

        if hasattr(timestamp, "to_pydatetime"):
            timestamp = timestamp.to_pydatetime()
        if not isinstance(timestamp, datetime) or timestamp.tzinfo is None:
            raise ValueError("timestamp must be a timezone-aware datetime")

        session_timezone = ZoneInfo(profile["timezone"])
        local_timestamp = timestamp.astimezone(session_timezone)
        try:
            start_time = datetime.strptime(profile["start"], "%H:%M").time()
        except ValueError as error:
            raise ValueError(
                f"Invalid session start for profile {profile_name}: {profile['start']}"
            ) from error

        session_start = datetime.combine(
            local_timestamp.date(),
            start_time,
            tzinfo=session_timezone,
        )
        if local_timestamp < session_start:
            session_start -= timedelta(days=1)

        return session_start.astimezone(timezone.utc)

    def initial_balance_window_for(self, symbol, timestamp):
        """Return the initial-balance window belonging to a trading session."""
        try:
            config = self._symbols[symbol]["initial_balance"]
            start_value = config["start"]
            duration_minutes = int(config["duration_minutes"])
            window_timezone = ZoneInfo(config["timezone"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(
                f"No valid initial-balance configuration for {symbol}"
            ) from error

        try:
            start_time = datetime.strptime(start_value, "%H:%M").time()
        except ValueError as error:
            raise ValueError(
                f"Invalid initial-balance start for {symbol}: {start_value}"
            ) from error
        if duration_minutes <= 0:
            raise ValueError(
                f"Initial-balance duration must be positive for {symbol}"
            )

        session_start = self.start_for(symbol, timestamp).astimezone(window_timezone)
        window_start = datetime.combine(
            session_start.date(),
            start_time,
            tzinfo=window_timezone,
        )
        if window_start < session_start:
            window_start += timedelta(days=1)
        window_end = window_start + timedelta(minutes=duration_minutes)

        return (
            window_start.astimezone(timezone.utc),
            window_end.astimezone(timezone.utc),
        )


DEFAULT_SCHEDULE = SessionSchedule.from_json()
SYMBOLS = DEFAULT_SCHEDULE.symbols
require_catalog_symbols = DEFAULT_SCHEDULE.require_symbols
