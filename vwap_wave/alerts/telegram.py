import logging
import os

import requests

LOGGER = logging.getLogger(__name__)


def topic_env_name(symbol):
    """Return the topic-id environment variable used by a futures symbol."""
    symbol_name = symbol.lstrip("/").upper()
    return f"TELEGRAM_TOPICID_{symbol_name}_FUT"


def alerts_from_env(symbols, environ=None, logger=None):
    """Build the configured per-symbol Telegram alert senders.

    Missing symbol topics are intentionally optional. They are reported in one
    startup warning and omitted from the returned mapping.
    """
    environ = os.environ if environ is None else environ
    logger = LOGGER if logger is None else logger
    token = environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = environ.get("TELEGRAM_GID")
    if not token or not chat_id:
        missing = [
            name
            for name, value in (
                ("TELEGRAM_BOT_TOKEN", token),
                ("TELEGRAM_GID", chat_id),
            )
            if not value
        ]
        logger.warning(
            "Telegram alerts disabled: missing %s",
            ", ".join(missing),
        )
        return {}

    alerts = {}
    missing_topics = []
    for symbol in symbols:
        env_name = topic_env_name(symbol)
        topic_id = environ.get(env_name)
        if not topic_id:
            missing_topics.append(f"{symbol} ({env_name})")
            continue
        alerts[symbol] = TelegramAlert(token, chat_id, topic_id)

    if missing_topics:
        logger.warning(
            "Telegram alerts disabled for symbols without topic IDs: %s",
            ", ".join(missing_topics),
        )
    return alerts


class TelegramAlert:
    def __init__(self, token, chat_id, topic_id, timeout_seconds=10):
        self.token = token
        self.chat_id = chat_id
        self.topic_id = topic_id
        self.timeout_seconds = timeout_seconds
        self.base_url = f"https://api.telegram.org/bot{self.token}"

    def send(self, message: str):
        url = f"{self.base_url}/sendMessage"
        data = {
            "chat_id": self.chat_id,
            "text": message,
            "message_thread_id": self.topic_id,
        }
        try:
            response = requests.post(
                url,
                data=data,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as error:
            # Request exceptions can include the token-bearing URL. Log only
            # the exception type so credentials cannot leak into output.
            LOGGER.error(
                "Telegram send failed: %s",
                type(error).__name__,
            )
            return False

        if not response.ok:
            LOGGER.error(
                "Telegram send failed with HTTP status %s",
                response.status_code,
            )
            return False
        return True


def deliver_events(events, senders):
    """Deliver engine events to configured Telegram topics."""
    for event in events:
        sender = senders.get(event["symbol"])
        if sender is None:
            continue
        if event["kind"] == "sweep":
            message = (
                f"🔔 {event['symbol']} {event['timeframe']} sweep ({event['trend_direction']} trend)\n"
                f"Candle: {event['candle_start']}\n"
                f"Source minute: {event['source_minute']}\n"
                f"Change level: {event['change_level']}\n"
                f"Sweep level: {event['sweep_level']}"
            )
        else:
            message = (
                f"🔔 {event['symbol']} touched {event['condition']}\n"
                f"Time: {event['source_minute']}\n"
                f"Level: {event['level']}\n"
                f"Bar range: {event['low']}–{event['high']}"
            )
        sender.send(message)
