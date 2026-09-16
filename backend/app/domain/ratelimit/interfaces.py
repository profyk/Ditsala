"""
Rate limiting (§32) — abuse-prevention throttles on OTP sends, email
verification sends, login attempts, invitation issuance, contact
requests, and SOS triggers. Behind a Protocol like every other external
dependency (Working Rule 4): the production-shaped adapter here is
Redis-backed (shared counters across instances), which this
single-machine dev environment can't run (no Redis binary available —
same constraint documented for `ConnectionManager`), so isolating it
behind an interface keeps that swap a `services/factory.py`-style
one-line change later, not a rewrite of every call site.
"""

from typing import Protocol


class RateLimitExceeded(Exception):
    """
    Raised when a caller has exceeded an action's configured rate limit.
    Callers turn this into a 429, not a 500 or a 400 — it isn't a bad
    request, it's a request that would otherwise be fine, too soon.
    """

    def __init__(self, key: str, *, retry_after_seconds: int) -> None:
        super().__init__(
            f"Rate limit exceeded for {key!r}; retry after {retry_after_seconds}s."
        )
        self.key = key
        self.retry_after_seconds = retry_after_seconds


class RateLimiter(Protocol):
    async def hit(self, key: str, *, limit: int, window_seconds: int) -> None:
        """
        Record one attempt under `key`. Raises `RateLimitExceeded` if this
        attempt would put the rolling window's count over `limit`;
        otherwise records it and returns normally. `key` should already
        encode which action this is (e.g. `"onboarding:email_code:<email>"`)
        — the limiter itself has no notion of actions, just counters.
        """
        ...
