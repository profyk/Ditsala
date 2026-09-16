"""
In-memory, single-process rate limiter — see
`app/domain/ratelimit/interfaces.py`'s docstring for why this isn't
Redis-backed yet (same "single instance is all this phase needs"
reasoning as `ConnectionManager`). Fixed-window counters keyed by an
arbitrary string; each `hit` lazily evicts timestamps that have aged out
of that key's own window, so the dict never needs a separate sweep task.
"""

import time
from collections import defaultdict

from app.domain.ratelimit.interfaces import RateLimiter, RateLimitExceeded


class InMemoryRateLimiter(RateLimiter):
    def __init__(self) -> None:
        self._hits: dict[str, list[float]] = defaultdict(list)

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> None:
        now = time.monotonic()
        window_start = now - window_seconds
        timestamps = self._hits[key]
        while timestamps and timestamps[0] < window_start:
            timestamps.pop(0)
        if len(timestamps) >= limit:
            retry_after = int(timestamps[0] + window_seconds - now) + 1
            raise RateLimitExceeded(key, retry_after_seconds=retry_after)
        timestamps.append(now)


# One instance per process — counters are inherently process-local, same
# as `connection_manager`.
rate_limiter = InMemoryRateLimiter()
