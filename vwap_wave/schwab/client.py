import logging
import os

import httpx
from schwab import auth

from vwap_wave import log

LOGGER = logging.getLogger(__name__)
log.disable_sublogger("httpx2")


class SchwabClient:
    """Minimal Schwab client focused on historical 1-minute futures data."""

    def __init__(self):
        token_path = "./token.json"
        api_key = os.environ["SCHWAB_KEY"]
        app_secret = os.environ["SCHWAB_SECRET"]

        self._client = auth.client_from_token_file(
            token_path=token_path,
            api_key=api_key,
            app_secret=app_secret,
            asyncio=True,
        )

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
        return {
            symbol: await self.get_historical_1m(symbol)
            for symbol in symbols
        }
