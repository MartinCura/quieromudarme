"""Logging setup."""

import logging
import os
from pathlib import Path

import colorlog
from dotenv import load_dotenv

from quieromudarme import __version__

load_dotenv()

DEBUG = os.getenv("DEBUG", "false").lower() == "true"
RUNNING_IN_AIRFLOW = os.getenv("AIRFLOW_HOME") is not None

logged_initial: bool = False


def setup_logger(
    name: str = "quieromudarme",
    log_filepath: Path = Path() / "logs" / "bot.log",
    level: int = logging.DEBUG if DEBUG else logging.INFO,
) -> logging.Logger:
    """Sets up a logger with the given name, log filename, and level."""
    global logged_initial  # noqa: PLW0603 (it's not the end of the world for this)
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not logger.handlers and not RUNNING_IN_AIRFLOW:
        # Create the directory for the log file if it doesn't exist
        log_filepath.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_filepath)
        file_handler.setFormatter(
            logging.Formatter(
                fmt="[%(asctime)s %(levelname)s %(module)s] %(funcName)s: %(message)s"
            )
        )
        logger.addHandler(file_handler)

        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(
            colorlog.ColoredFormatter(
                fmt="%(log_color)s[%(asctime)s %(levelname)s %(module)s] %(funcName)s: %(message)s"
            )
        )
        logger.addHandler(stream_handler)

    if not logged_initial:
        logger.info(f"Running quieromudarme version {__version__}")
        if RUNNING_IN_AIRFLOW:
            logger.debug("Detected as running in Airflow.")
        logger.info(f"Logging to {log_filepath}")
        logger.info(f"Logging level set to {logging.getLevelName(level)}")
        logged_initial = True

    return logger
