import asyncio
import inspect
import logging
import os
from datetime import datetime, timezone

import httpx
from schwab import auth, streaming

from vwap_wave import log

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

    async def get_historical_1m(self, symbol):
        LOGGER.debug(f"Requesting historical 1m candles for {symbol}")
        resp = await self._client.get_price_history_every_minute(
            symbol, need_extended_hours_data=True
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

    async def get_historical_1m_for_symbols(self, symbols):
        symbols = list(symbols)
        candles = await asyncio.gather(
            *(self.get_historical_1m(symbol) for symbol in symbols)
        )
        return dict(zip(symbols, candles))

    async def subscribe_live_1m(self, symbol, on_bar=None):
        await self.subscribe_live_1m_for_symbols([symbol], on_bar=on_bar)

    async def subscribe_live_1m_for_symbols(
        self, symbols, on_bar=None, on_ready=None
    ):
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
