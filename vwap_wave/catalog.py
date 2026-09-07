from .sessions import SessionSchedule
from .ta.initial_balance import INITIAL_BALANCE_COLUMNS
from .ta.volume_profile import VOLUME_PROFILE_COLUMNS
from .ta.vwap import SESSION_VWAP_COLUMNS


SYMBOLS = SessionSchedule.from_json().symbols

INDICATOR_COLUMNS = tuple(
    SESSION_VWAP_COLUMNS + INITIAL_BALANCE_COLUMNS + VOLUME_PROFILE_COLUMNS
)


def require_catalog_symbols(symbols):
    """Return symbols as a tuple or raise if any are not configured."""
    if isinstance(symbols, str):
        requested = (symbols,)
    else:
        requested = tuple(symbols)

    unknown = [symbol for symbol in requested if symbol not in SYMBOLS]
    if unknown:
        raise ValueError(
            "Symbols not configured in sessions.json: " + ", ".join(unknown)
        )
    return requested
