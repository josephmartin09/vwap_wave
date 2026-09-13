import logging
import time

from .. import log
from ..engine import Engine
from ..alerts import ALERT_CONDITIONS
from ..alerts.telegram import alerts_from_env, deliver_events
from ..commands import ReplaceAlertConditions, ShowAlertConditions, UnixCommandServer
from ..schwab.feed import SchwabBarFeed


class LiveRunner:
    def __init__(self, engine, command_server=None, telegram_alerts=None, reconnect_delay_seconds=5.0):
        self.engine = engine
        self.command_server = command_server
        self.logger = logging.getLogger(__name__)
        self.reconnect_delay_seconds = reconnect_delay_seconds
        self.telegram_alerts = alerts_from_env(engine.symbols) if telegram_alerts is None else telegram_alerts

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
            if command.symbol not in self.engine.symbols:
                return "unknown symbol: {}".format(command.symbol)
            for condition in command.conditions:
                if condition not in ALERT_CONDITIONS:
                    return "unknown indicator: {}".format(condition)
            return None
        if isinstance(command, ShowAlertConditions):
            if command.symbol not in self.engine.symbols:
                return "unknown symbol: {}".format(command.symbol)
            return None
        return "unsupported command"

    def apply_cli_command(self, command):
        self.logger.info("COMMAND ACK: %r", command)

        if isinstance(command, ReplaceAlertConditions):
            self.engine.set_alert_conditions(command.symbol, command.conditions)
        elif isinstance(command, ShowAlertConditions):
            self.logger.info("%s alert conditions: %s", command.symbol,
                             self.engine.alert_conditions[command.symbol])

    def process_bar(self, bar):
        events = self.engine.process_bar(bar)
        deliver_events(events, self.telegram_alerts)
        return events

    def run_feed(self):
        with SchwabBarFeed(self.engine.symbols) as feed:
            history = feed.get_historical_1m()
            self.engine.warmup({symbol: self.engine.candles_to_df(raw)
                                for symbol, raw in history.items()})
            self.logger.info("Polling live 1m updates for %s", ", ".join(self.engine.symbols))
            while True:
                self.process_cli_commands()
                bar = feed.poll(timeout=1.0)
                if bar is not None:
                    self.process_bar(bar)

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
        LiveRunner(Engine(), command_server=command_server).run()
