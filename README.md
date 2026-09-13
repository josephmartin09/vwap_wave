# VWAP Wave

Live and replay both use `vwap_wave.engine.Engine`. Given the same initial
history, alert conditions, and bar sequence, they produce the same alert events.
The engine has no Telegram or market-data connection dependencies.

- `config/`: symbol definitions, session schedules, and symbol validation.
- `engine/`: candle state, resampling, indicators, alert evaluation, and warmup.
- `alerts/`: supported conditions, shared defaults, and Telegram delivery.
- `live/`: feed polling, reconnects, CLI commands, and Telegram wiring.
- `replay/`: historical bar input and CSV reports.
- `schwab/`: Schwab transport.
- `ta/`: indicator calculations.

Edit `vwap_wave/config/sessions.json` to add symbols and session definitions.
`config/sessions.py` loads that file and handles session calculations and symbol
validation. Restart the application and CLI after editing the file. Session times
retain their existing UTC definitions.

## Run

Live: `python -m vwap_wave`

Interactive configuration: `python -m vwap_wave.cli`

Replay: `python -m vwap_wave.replay --symbol /ES --conditions sweep_1h`

Both modes default to no enabled alert conditions. In the live CLI,
`set /ES sweep_1h` enables hourly sweep alerts; `set` replaces the symbol's
conditions, and `set /ES` disables them. Replay's `--conditions` selects the same
condition names without changing engine defaults. Replay never wires Telegram.
The replay candle and alert CSV formats remain unchanged; the alert CSV records
sweep events. All event types are available through `Engine.process_bar()`.

## Initialization and parity

`Engine.warmup(history)` accepts a mapping of symbols to UTC-indexed OHLCV
DataFrames and initializes state without emitting historical alerts. Live uses
this on startup and reconnect. `replay_minutes(engine, symbol, frame,
history=history)` supports the same initialization; history must precede the
replay bars. Without history, replay starts empty. Comparisons with a live run
must use matching warmup data and subsequent bars. Historical minute candles
cannot reproduce updates within a minute.

## Indicators

`indicators/` defines the `Indicator` ABC, its input/output types, and the four
built-in implementations. Each indicator owns its constructor settings and
implements `calculate(context)`. The existing `ta/` functions provide the math.

```python
from vwap_wave.engine import Engine
from vwap_wave.indicators import (
    SessionVwapIndicator, InitialBalanceIndicator,
    VolumeProfileIndicator, OpusIndicator,
)

engine = Engine(indicators={
    "vwap": SessionVwapIndicator(),
    "initial_balance": InitialBalanceIndicator(),
    "volume_profile": VolumeProfileIndicator(bins=100, value_area_percent=0.70),
    "opus": OpusIndicator(timeframe="1h", lookback=2000),
})
```

Omitting `indicators` creates these defaults; an empty mapping disables all
calculations. Settings dictionaries can be passed directly to constructors,
e.g. `VolumeProfileIndicator(**settings)`. Indicator configuration file loading
is not implemented yet. Engine-level profile and Opus settings have moved to
these constructors; replay's `--opus-lookback` option remains available.

The engine resamples once per requested timeframe. `IndicatorContext` contains
the symbol, candles at that timeframe, and session schedule. Inputs are read-only
by convention; indicators are stateless and must handle empty candle frames.
They receive only OHLCV input, so calculations do not depend on indicator order.
The supported timeframes are currently `1min` and `1h`.

`IndicatorResult` contains a DataFrame of named levels and optional detail such
as a volume distribution or latest Opus trend. Read results through
`engine.results[symbol][name]`. Minute levels are also copied into the engine's
minute frame for existing touch alerts. Hourly levels remain in their result at
their native timestamps. Alert selection and notification delivery remain
separate from indicator calculations; custom alert conditions still require
registration in `alerts/conditions.py`.
