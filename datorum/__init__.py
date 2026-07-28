import logging
import os
import sys
from pathlib import Path


_PACKAGE_LOGGER_NAME = "datorum"


def get_logger(name: str) -> logging.Logger:
    """Returns a namespaced logger."""
    return logging.getLogger(
        f"{_PACKAGE_LOGGER_NAME}.{name}" if name != _PACKAGE_LOGGER_NAME else name
    )


def configure_logging(
    level: int = logging.WARNING,
    log_file: Path | None = None
) -> None:
    """Call one, from the entrypoint."""
    logger = logging.getLogger(_PACKAGE_LOGGER_NAME)
    logger.handlers.clear()
    logger.setLevel(level)
    logger.propagate = False

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = logging.FileHandler(log_file)
    else:
        handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    logger.addHandler(handler
)