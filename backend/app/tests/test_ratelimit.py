"""Unit tests for the §32 in-memory rate limiter."""

import asyncio

import pytest

from app.domain.ratelimit.interfaces import RateLimitExceeded
from app.services.ratelimit.memory import InMemoryRateLimiter


async def test_allows_up_to_the_limit() -> None:
    limiter = InMemoryRateLimiter()
    for _ in range(3):
        await limiter.hit("k", limit=3, window_seconds=60)


async def test_raises_once_limit_is_exceeded() -> None:
    limiter = InMemoryRateLimiter()
    for _ in range(3):
        await limiter.hit("k", limit=3, window_seconds=60)

    with pytest.raises(RateLimitExceeded) as exc_info:
        await limiter.hit("k", limit=3, window_seconds=60)
    assert exc_info.value.retry_after_seconds > 0


async def test_different_keys_are_independent() -> None:
    limiter = InMemoryRateLimiter()
    for _ in range(3):
        await limiter.hit("a", limit=3, window_seconds=60)

    # "b" has its own counter — must not be affected by "a" hitting its cap.
    await limiter.hit("b", limit=3, window_seconds=60)


async def test_window_expiry_allows_further_hits() -> None:
    limiter = InMemoryRateLimiter()
    await limiter.hit("k", limit=1, window_seconds=0)
    await asyncio.sleep(0.01)
    # A zero-second window has already fully elapsed by the next hit.
    await limiter.hit("k", limit=1, window_seconds=0)
