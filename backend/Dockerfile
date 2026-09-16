# Multi-stage build: the builder stage has uv and compiles dependencies,
# the runtime stage only carries the installed packages and app code —
# keeps the deployed image lean and avoids shipping build tooling.

FROM python:3.12-slim AS builder

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
# --no-install-project: dependencies only, in their own layer, so an app
# code change doesn't invalidate this (much slower) layer's cache.
RUN uv sync --frozen --no-install-project --no-dev

COPY . .
RUN uv sync --frozen --no-dev

FROM python:3.12-slim

RUN useradd --create-home --uid 1000 ditsala
WORKDIR /app

COPY --from=builder --chown=ditsala:ditsala /app /app
ENV PATH="/app/.venv/bin:${PATH}"

USER ditsala

EXPOSE 8000
# "sh entrypoint.sh" rather than "./entrypoint.sh" deliberately — Windows
# git checkouts (this repo's primary dev environment) don't preserve the
# executable bit, so relying on it would break the build intermittently
# depending on what checked the file out.
ENTRYPOINT ["sh", "entrypoint.sh"]
