import asyncio
import logging

import pandas as pd

from . import log
from .schwab.client import SchwabClient

SYMBOL = "/ES"


def candles_to_df(candles):
    if not candles:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    df = pd.DataFrame(candles)
    if df.empty:
        return df

    df["datetime"] = pd.to_datetime(df["datetime"], unit="ms", utc=True)
    df.set_index("datetime", inplace=True)
    return df[["open", "high", "low", "close", "volume"]]


async def main():
    log.setup_logging()
    logger = logging.getLogger(__name__)

    client = SchwabClient()
    raw = await client.get_historical_1m(SYMBOL)
    if raw is None:
        logger.warning(f"No historical candle data returned for {SYMBOL}")
        return

    df = candles_to_df(raw)
    print(df.tail(10))
    logger.info(f"Historical {SYMBOL} data loaded and printed.")


if __name__ == "__main__":
    asyncio.run(main())
