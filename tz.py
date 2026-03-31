"""Centralized timezone helper. All timestamps use Brasilia time."""

from datetime import datetime, timezone, timedelta

BRT = timezone(timedelta(hours=-3))


def now_brt() -> datetime:
    """Returns current datetime in Brasilia timezone (UTC-3)."""
    return datetime.now(BRT)
