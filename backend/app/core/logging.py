import logging

import structlog


def configure_logging() -> None:
    """
    Structured JSON logging. Field allowlist (not denylist) is enforced here
    so a new field must be deliberately added before it can be logged —
    fails safe against accidentally logging P0/P1/P2 data (see
    docs/DITSALA_MASTER_SPEC.md §5, §30).
    """
    logging.basicConfig(format="%(message)s", level=logging.INFO)
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
    )
