"""Simple per-key cooldown rate limiting."""

from __future__ import annotations

import asyncio
from typing import Any


class RateLimiter:
    def __init__(self) -> None:
        self._last: dict[str, float] = {}

    def allow(self, key: str, min_interval_s: float) -> tuple[bool, float]:
        loop = asyncio.get_running_loop()
        now = loop.time()
        prev = self._last.get(key, 0.0)
        elapsed = now - prev
        if elapsed < min_interval_s:
            return False, min_interval_s - elapsed
        self._last[key] = now
        return True, 0.0
