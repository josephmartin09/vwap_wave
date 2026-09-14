import asyncio
import inspect
import logging
import os
from datetime import datetime, timedelta, timezone

import httpx
from schwab import auth, streaming

from vwap_wave import log
from vwap_wave.config import require_catalog_symbols

USE_HISTORICAL_POLLING = True
HISTORICAL_POLL_INTERVAL_SECONDS = 5

LOGGER = logging.getLogger(__name__)
log.disable_sublogger("httpx2")


class SchwabClient:
    """Minimal Schwab client focused on historical and live 1-minute futures data."""

    def __init__(self):
        token_path = "./token.json"
        api_key = os.environ["SCHWAB_KEY"]
        app_secret = os.environ["SCHWAB_SECRET"]
        acct_id = os.environ.get("SCHWAB_ACCT_ID")

        self._client = auth.client_from_token_file(
            token_path=token_path,
            api_key=api_key,
            app_secret=app_secret,
            asyncio=True,
        )

        if acct_id is not None:
            self._sclient = streaming.StreamClient(self._client, account_id=acct_id)
        else:
            self._sclient = streaming.StreamClient(self._client)

    async def get_historical_1m(self, symbol, start_datetime=None):
        require_catalog_symbols((symbol,))
        LOGGER.debug(f"Requesting historical 1m candles for {symbol}")
        resp = await self._client.get_price_history_every_minute(
            symbol, start_datetime=start_datetime, need_extended_hours_data=True
        )

        if resp.status_code != httpx.codes.OK:
            raise RuntimeError(f"Schwab request failed for {symbol}: {resp.status_code}")

        payload = resp.json()
        if payload.get("empty"):
            LOGGER.warning(f"No candle history returned for {symbol}")
            return None

        candles = payload.get("candles") or []
        if not candles:
            return None

        return candles

    async def get_historical_1m_for_symbols(self, symbols, start_datetime=None):
        symbols = list(require_catalog_symbols(symbols))
        candles = await asyncio.gather(
            *(self.get_historical_1m(symbol, start_datetime=start_datetime)
              for symbol in symbols)
        )
        return dict(zip(symbols, candles))

    async def subscribe_live_1m(self, symbol, on_bar=None):
        require_catalog_symbols((symbol,))
        await self.subscribe_live_1m_for_symbols([symbol], on_bar=on_bar)

    async def subscribe_live_1m_for_symbols(
        self, symbols, on_bar=None, on_ready=None
    ):
        if USE_HISTORICAL_POLLING:
            return await self.poll_historical_1m_for_symbols(
                symbols, on_bar=on_bar, on_ready=on_ready
            )

        symbols = require_catalog_symbols(symbols)
        if on_bar is None:
            on_bar = lambda bar: None

        await self._sclient.login()
        try:
            self._sclient.add_chart_futures_handler(
                lambda update: self._handle_live_update(update, on_bar)
            )
            await self._sclient.chart_futures_subs(list(symbols))

            if on_ready is not None:
                result = on_ready()
                if inspect.isawaitable(result):
                    await result

            while True:
                await self._sclient.handle_message()
        except asyncio.CancelledError:
            LOGGER.info("Stopping live feed")
        finally:
            await self._sclient.logout()

    async def poll_historical_1m_for_symbols(
        self, symbols, on_bar=None, on_ready=None
    ):
        """Publish newly completed historical candles, once per symbol/minute.

        The first response establishes a baseline; older candles belong to
        engine warmup. Afterwards, a new completed candle for symbols[0]
        triggers full-set polling until every symbol reaches that candle's
        timestamp. Each symbol retains its own publication timestamp.
        No streaming connection is opened.
        """
        symbols = require_catalog_symbols(symbols)
        last_seen = {}
        LOGGER.info("Using historical 1m polling every %s seconds",
                    HISTORICAL_POLL_INTERVAL_SECONDS)
        if on_ready is not None:
            result = on_ready()
            if inspect.isawaitable(result):
                await result

        # Establish history baselines without publishing old candles.
        now = datetime.now(timezone.utc)
        current_minute = int(now.timestamp()) // 60 * 60000
        history = await self.get_historical_1m_for_symbols(
            symbols, start_datetime=now - timedelta(days=3)
        )
        for symbol, candles in history.items():
            last_seen[symbol] = max(
                (int(candle["datetime"]) for candle in (candles or [])
                 if int(candle["datetime"]) < current_minute),
                default=current_minute - 60000,
            )
            LOGGER.info("Historical polling baseline for %s: %s", symbol,
                        datetime.fromtimestamp(last_seen[symbol] / 1000,
                                               tz=timezone.utc))

        sentinel = symbols[0]
        while True:
            # Phase 1: wait for a new completed sentinel candle.
            while True:
                await asyncio.sleep(HISTORICAL_POLL_INTERVAL_SECONDS)
                now = datetime.now(timezone.utc)
                current_minute = int(now.timestamp()) // 60 * 60000
                candles = await self.get_historical_1m(
                    sentinel, start_datetime=now - timedelta(days=3)
                )
                target_timestamp = max(
                    (int(candle["datetime"]) for candle in (candles or [])
                     if last_seen[sentinel] < int(candle["datetime"]) < current_minute),
                    default=None,
                )
                if target_timestamp is not None:
                    break

            # Phase 2: poll the full set until every symbol reaches the target.
            while True:
                # Capture before requesting so crossing a minute boundary
                # during the request cannot make a partial candle eligible.
                now = datetime.now(timezone.utc)
                current_minute = int(now.timestamp()) // 60 * 60000
                history = await self.get_historical_1m_for_symbols(
                    symbols, start_datetime=now - timedelta(days=3)
                )
                for symbol, candles in history.items():
                    completed = {
                        int(candle["datetime"]): candle
                        for candle in (candles or [])
                        if int(candle["datetime"]) < current_minute
                    }
                    for timestamp in sorted(completed):
                        if timestamp <= last_seen[symbol]:
                            continue
                        candle = completed[timestamp]
                        bar = {
                            "symbol": symbol,
                            "datetime": datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc),
                            **{field: float(candle[field])
                               for field in ("open", "high", "low", "close")},
                            "volume": int(candle["volume"]),
                        }
                        LOGGER.info("Historical polled 1m candle: %s", bar)
                        if on_bar is not None:
                            result = on_bar(bar)
                            if inspect.isawaitable(result):
                                await result
                        last_seen[symbol] = timestamp
                if all(last_seen[symbol] >= target_timestamp for symbol in symbols):
                    break
                await asyncio.sleep(HISTORICAL_POLL_INTERVAL_SECONDS)

    def _handle_live_update(self, update, on_bar):
        for msg in update.get("content", []):
            key = msg.get("key")
            if not key:
                continue

            try:
                bar = {
                    "symbol": key,
                    "datetime": datetime.fromtimestamp(
                        int(msg["CHART_TIME_MILLIS"]) / 1000,
                        tz=timezone.utc,
                    ),
                    "open": float(msg["OPEN_PRICE"]),
                    "high": float(msg["HIGH_PRICE"]),
                    "low": float(msg["LOW_PRICE"]),
                    "close": float(msg["CLOSE_PRICE"]),
                    "volume": int(msg["VOLUME"]),
                }
            except (KeyError, TypeError, ValueError):
                continue

            result = on_bar(bar)
            if inspect.isawaitable(result):
                asyncio.create_task(result)
