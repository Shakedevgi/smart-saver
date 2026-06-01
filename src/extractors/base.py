"""Abstract contract every concrete extractor must implement."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from src.schemas import ArticleResult, VideoResult

TResult = TypeVar("TResult", ArticleResult, VideoResult)


class BaseExtractor(ABC, Generic[TResult]):
    """Common interface for article / video extractors."""

    @abstractmethod
    def extract(self, url: str) -> TResult:
        """Pull every piece of usable text we can from `url`.

        Implementations must never raise on expected failure modes
        (network error, geo-block, paywall, missing audio, …). They should
        log and return a partially-populated result instead, so the
        orchestrator can still hand *something* to the LLM layer.
        """
