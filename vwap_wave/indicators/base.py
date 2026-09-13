from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Generic, TypeVar

import pandas as pd

from ..config import SessionSchedule

T = TypeVar("T")


@dataclass(frozen=True)
class IndicatorContext:
    """Candles at the indicator's timeframe; treat inputs as read-only."""

    symbol: str
    candles: pd.DataFrame
    session_schedule: SessionSchedule


@dataclass
class IndicatorResult(Generic[T]):
    """Named levels indexed by candle start, plus optional richer output.

    Levels may cover all input candles or only the latest candle. Missing values
    explicitly clear a level. Calculations must not modify the supplied context.
    """

    levels: pd.DataFrame
    detail: T | None = None


class Indicator(ABC):
    """Stateless calculation with constructor settings shared across symbols.

    The engine supplies full available history at ``timeframe``. Implementations
    must handle empty input and return deterministic results without I/O.
    """

    timeframe = "1min"

    @abstractmethod
    def calculate(self, context: IndicatorContext) -> IndicatorResult:
        """Calculate levels and optional detail from the supplied candles."""
        raise NotImplementedError
