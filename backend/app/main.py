from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.v1.routers import (
    account,
    admin,
    admin_auth,
    admin_kyc,
    auth,
    calls,
    circle,
    health,
    location,
    messaging,
    onboarding,
    recovery,
    sos,
)
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.domain.ratelimit.interfaces import RateLimitExceeded
from app.tasks.scheduler import start_scheduler

configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Touches settings once at boot so a missing/invalid env fails fast.
    get_settings()
    scheduler = start_scheduler()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="DITSALA API", version="0.1.0", lifespan=lifespan)


@app.exception_handler(RateLimitExceeded)
async def rate_limit_exceeded_handler(_: Request, exc: RateLimitExceeded) -> JSONResponse:
    """§32 — a single handler for every rate-limited action rather than a
    try/except in each router, since the response shape (429 + Retry-After)
    never varies by action."""
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests. Please try again shortly."},
        headers={"Retry-After": str(exc.retry_after_seconds)},
    )


app.include_router(health.router, prefix="/api/v1")
app.include_router(onboarding.router, prefix="/api/v1")
app.include_router(onboarding.webhook_router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(messaging.router, prefix="/api/v1")
app.include_router(messaging.ws_router, prefix="/api/v1")
app.include_router(circle.router, prefix="/api/v1")
app.include_router(location.router, prefix="/api/v1")
app.include_router(sos.router, prefix="/api/v1")
app.include_router(calls.router, prefix="/api/v1")
app.include_router(admin_auth.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
app.include_router(admin_kyc.router, prefix="/api/v1")
app.include_router(recovery.router, prefix="/api/v1")
app.include_router(account.router, prefix="/api/v1")
