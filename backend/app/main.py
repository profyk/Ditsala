from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.routers import (
    account,
    admin,
    admin_auth,
    admin_billing,
    admin_kyc,
    auth,
    billing,
    calls,
    circle,
    health,
    location,
    meetings,
    messaging,
    onboarding,
    plans,
    recovery,
    sos,
    vip,
    vip_chat,
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

# apps/admin and apps/meet are browser clients calling this API
# cross-origin; the mobile app and server-to-server calls never go
# through a browser and are unaffected by this. See Settings.cors_
# allowed_origins for the origin list this reads.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
app.include_router(admin_billing.router, prefix="/api/v1")
app.include_router(recovery.router, prefix="/api/v1")
app.include_router(account.router, prefix="/api/v1")
app.include_router(meetings.router, prefix="/api/v1")
app.include_router(plans.router, prefix="/api/v1")
app.include_router(billing.router, prefix="/api/v1")
app.include_router(billing.webhook_router, prefix="/api/v1")
app.include_router(vip.router, prefix="/api/v1")
app.include_router(vip_chat.router, prefix="/api/v1")
