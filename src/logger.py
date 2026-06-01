"""Thin wrapper around `logging` so every module gets a consistently formatted
logger via `get_logger(__name__)` without re-configuring handlers itself.
"""

from __future__ import annotations

import logging
import sys

from src.config import settings

_CONFIGURED = False


def _configure_root_logger() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    root = logging.getLogger()
    root.setLevel(settings.log_level.upper())

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root.handlers.clear()
    root.addHandler(handler)

    # Quiet down chatty third-party libraries.
    for noisy in ("urllib3", "trafilatura", "charset_normalizer", "hpack"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger. Safe to call repeatedly."""
    _configure_root_logger()
    return logging.getLogger(name)
