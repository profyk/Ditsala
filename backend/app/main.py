from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.routers import auth, calls, circle, health, location, messaging, onboarding, sos
from app.core.config import get_settings
from app.core.logging import configure_logging

configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Touches settings once at boot so a missing/invalid env fails fast.
    get_settings()
    yield


app = FastAPI(title="DITSALA API", version="0.1.0", lifespan=lifespan)
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
