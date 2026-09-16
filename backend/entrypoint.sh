#!/bin/sh
# Runs pending Alembic migrations before the server starts accepting
# traffic — deliberately sequential (not backgrounded), so a container
# never serves requests against a schema it doesn't match yet. Safe to
# run on every boot: Alembic no-ops when there's nothing pending, which
# matters here since Railway/ECS restart this same entrypoint on every
# deploy and every crash-restart.
set -e
alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
