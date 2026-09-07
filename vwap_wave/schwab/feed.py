import asyncio
import queue
import threading
from concurrent.futures import TimeoutError as FutureTimeoutError

from ..catalog import require_catalog_symbols


class FeedError(RuntimeError):
    """Base exception for failures at the synchronous feed boundary."""


class FeedStartupError(FeedError):
    """Raised when the feed cannot become ready."""


class FeedConnectionLost(FeedError):
    """Raised when the live stream exits unexpectedly."""


class _FeedFailure:
    def __init__(self, error):
        self.error = error


class SchwabBarFeed:
    """Synchronous, polling interface to the asynchronous Schwab client."""

    def __init__(self, symbols, client_factory=None):
        self.symbols = require_catalog_symbols(symbols)
        if not self.symbols:
            raise ValueError("At least one symbol is required")

        self._client_factory = client_factory
        self._queue = queue.SimpleQueue()
        self._ready = threading.Event()
        self._stopping = threading.Event()
        self._thread = None
        self._loop = None
        self._stream_task = None
        self._client = None
        self._failure = None

    def start(self, timeout=30.0):
        """Start the worker and wait for the live subscription to be ready."""
        if self._thread is not None:
            raise FeedStartupError("Feed has already been started")

        self._thread = threading.Thread(
            target=self._thread_main,
            name="schwab-bar-feed",
            daemon=False,
        )
        self._thread.start()

        if not self._ready.wait(timeout):
            self.close()
            raise FeedStartupError("Timed out waiting for the Schwab feed to start")

        if self._failure is not None:
            self._thread.join()
            raise FeedStartupError("Unable to start the Schwab feed") from self._failure

        return self

    def get_historical_1m(self, timeout=30.0):
        """Synchronously fetch one-minute history for all configured symbols."""
        self._require_running()
        future = asyncio.run_coroutine_threadsafe(
            self._client.get_historical_1m_for_symbols(self.symbols),
            self._loop,
        )
        try:
            return future.result(timeout)
        except FutureTimeoutError as error:
            future.cancel()
            raise FeedError("Timed out fetching historical candles") from error
        except Exception as error:
            raise FeedError("Unable to fetch historical candles") from error

    def poll(self, timeout=0.0):
        """Return the next published bar, None on timeout, or raise on feed loss."""
        self._require_started()

        try:
            item = self._queue.get(timeout=timeout)
        except queue.Empty:
            if self._failure is not None:
                raise FeedConnectionLost("Schwab feed connection was lost") from self._failure
            if not self._stopping.is_set() and not self._thread.is_alive():
                raise FeedConnectionLost("Schwab feed worker stopped unexpectedly")
            return None

        if isinstance(item, _FeedFailure):
            raise FeedConnectionLost("Schwab feed connection was lost") from item.error

        return item

    def close(self, timeout=10.0):
        """Stop the stream and wait for its worker thread to exit."""
        if self._thread is None:
            return

        self._stopping.set()
        if (
            self._loop is not None
            and not self._loop.is_closed()
            and self._stream_task is not None
        ):
            try:
                self._loop.call_soon_threadsafe(self._stream_task.cancel)
            except RuntimeError:
                # The worker may close the loop between is_closed() and this call.
                pass

        self._thread.join(timeout)
        if self._thread.is_alive():
            raise FeedError("Timed out stopping the Schwab feed")

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def _require_started(self):
        if self._thread is None:
            raise FeedError("Feed has not been started")

    def _require_running(self):
        self._require_started()
        if self._failure is not None or not self._thread.is_alive():
            raise FeedConnectionLost("Schwab feed is not running") from self._failure

    def _thread_main(self):
        try:
            asyncio.run(self._run_stream())
            if not self._stopping.is_set():
                self._record_failure(RuntimeError("Schwab stream exited unexpectedly"))
        except BaseException as error:
            if not self._stopping.is_set():
                self._record_failure(error)
        finally:
            self._ready.set()

    async def _run_stream(self):
        if self._client_factory is None:
            from .client import SchwabClient

            self._client_factory = SchwabClient

        self._loop = asyncio.get_running_loop()
        self._stream_task = asyncio.current_task()
        self._client = self._client_factory()
        await self._client.subscribe_live_1m_for_symbols(
            self.symbols,
            on_bar=self._queue.put,
            on_ready=self._ready.set,
        )

    def _record_failure(self, error):
        self._failure = error
        self._queue.put(_FeedFailure(error))
