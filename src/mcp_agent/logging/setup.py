"""
Structured logging configuration using loguru.

Configures loguru to output JSON logs to stdout with session and node context binding.
"""

import sys

from loguru import logger

from mcp_agent.settings import Settings


def configure_logging(settings: Settings) -> None:
    """
    Configure loguru JSON logging.

    Sets up a JSON sink to stdout with the specified log level.
    Enables context binding for session_id and node identifiers.

    Args:
        settings: Application settings containing log_level configuration.
    """
    # Remove default handler
    logger.remove()

    # Add JSON sink to stdout
    logger.add(
        sink=sys.stdout,
        format="{message}",
        level=settings.log_level,
        serialize=True,
        backtrace=True,
        diagnose=True,
    )
