"""structlog setup - structured JSON logs, dev pretty mode."""
import logging
import sys

import structlog


def setup_logging(debug: bool = False, json_mode: bool = True) -> None:
    level = logging.DEBUG if debug else logging.INFO
    timestamper = structlog.processors.TimeStamper(fmt="iso")
    shared = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        timestamper,
    ]
    renderer = (
        structlog.dev.ConsoleRenderer()
        if not json_mode or debug
        else structlog.processors.JSONRenderer()
    )
    structlog.configure(
        processors=[*shared, structlog.processors.StackInfoRenderer(),
                     structlog.processors.format_exc_info, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )
