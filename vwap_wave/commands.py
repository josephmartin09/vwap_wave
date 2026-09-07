import json
import os
import socket
from dataclasses import dataclass
from pathlib import Path


DEFAULT_COMMAND_SOCKET_PATH = Path(
    os.environ.get(
        "VWAP_WAVE_COMMAND_SOCKET",
        "/tmp/vwap-wave-{}.sock".format(os.getuid()),
    )
)
MAX_COMMAND_BYTES = 1024


@dataclass(frozen=True)
class ReplaceAlertConditions:
    symbol: str
    conditions: tuple


@dataclass(frozen=True)
class ShowAlertConditions:
    symbol: str


@dataclass(frozen=True)
class ReceivedCommand:
    command: object = None
    rejection: str = None


def encode_command(command):
    if isinstance(command, ReplaceAlertConditions):
        payload = {
            "operation": "replace_alert_conditions",
            "symbol": command.symbol,
            "conditions": list(command.conditions),
        }
    elif isinstance(command, ShowAlertConditions):
        payload = {
            "operation": "show_alert_conditions",
            "symbol": command.symbol,
        }
    else:
        raise TypeError("unsupported command type")
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def decode_command(payload):
    try:
        message = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("invalid JSON command") from error

    if not isinstance(message, dict):
        raise ValueError("command must be a JSON object")
    operation = message.get("operation")
    if operation == "replace_alert_conditions":
        symbol = message.get("symbol")
        conditions = message.get("conditions")
        if not isinstance(symbol, str) or not symbol:
            raise ValueError("symbol must be a non-empty string")
        if not isinstance(conditions, list) or not all(
            isinstance(condition, str) for condition in conditions
        ):
            raise ValueError("conditions must be a list of strings")
        return ReplaceAlertConditions(symbol=symbol, conditions=tuple(conditions))

    if operation == "show_alert_conditions":
        symbol = message.get("symbol")
        if not isinstance(symbol, str) or not symbol:
            raise ValueError("symbol must be a non-empty string")
        return ShowAlertConditions(symbol=symbol)

    raise ValueError("unknown command operation")


class UnixCommandClient:
    def __init__(self, path=DEFAULT_COMMAND_SOCKET_PATH):
        self.path = Path(path)

    def send(self, command):
        payload = encode_command(command)
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as command_socket:
            command_socket.sendto(payload, str(self.path))


class UnixCommandServer:
    def __init__(self, path=DEFAULT_COMMAND_SOCKET_PATH):
        self.path = Path(path)
        self._socket = None
        self._socket_inode = None

    def open(self):
        if self._socket is not None:
            raise RuntimeError("command socket is already open")

        command_socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            command_socket.bind(str(self.path))
            os.chmod(self.path, 0o600)
            command_socket.setblocking(False)
        except Exception:
            command_socket.close()
            raise

        self._socket = command_socket
        self._socket_inode = self.path.stat().st_ino
        return self

    def receive_nowait(self):
        if self._socket is None:
            raise RuntimeError("command socket is not open")

        try:
            payload = self._socket.recv(MAX_COMMAND_BYTES)
        except BlockingIOError:
            return None

        try:
            return ReceivedCommand(command=decode_command(payload))
        except ValueError as error:
            return ReceivedCommand(rejection=str(error))

    def close(self):
        if self._socket is None:
            return

        self._socket.close()
        self._socket = None
        try:
            if self.path.stat().st_ino == self._socket_inode:
                self.path.unlink()
        except FileNotFoundError:
            pass
        finally:
            self._socket_inode = None

    def __enter__(self):
        return self.open()

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
