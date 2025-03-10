"""Job for housing searches."""

import logging
from datetime import timedelta
from pathlib import Path

import tenacity

from quieromudarme.log import setup_logger

logger = setup_logger("etl", log_filepath=Path() / "logs" / "etl.log")

from quieromudarme import etl, notifier  # noqa: E402


@tenacity.retry(
    wait=tenacity.wait_exponential(multiplier=1, min=4, max=15),
    stop=tenacity.stop_after_attempt(3),
    before_sleep=tenacity.before_sleep_log(logger, logging.WARNING),
)
def etl_searches() -> None:
    """Run all housing searches."""
    logger.info("======\n\n\nStarting ETL.")
    start_delta = timedelta(minutes=90)
    etl.etl_housing_for_all_searches_sync(start_delta=start_delta)
    logger.info("Finished ETL.\n\n\n======")


@tenacity.retry(
    wait=tenacity.wait_exponential(multiplier=1, min=4, max=15),
    stop=tenacity.stop_after_attempt(3),
    before_sleep=tenacity.before_sleep_log(logger, logging.WARNING),
)
def notify_revised_housing() -> None:
    """Notify users about new revisions."""
    logger.info("======\n\n\nStarting new revisions notifier.")
    notifier.notify_revised_sync()
    logger.info("Finished new revisions notifier.\n\n\n======")


@tenacity.retry(
    wait=tenacity.wait_exponential(multiplier=1, min=4, max=15),
    stop=tenacity.stop_after_attempt(3),
    before_sleep=tenacity.before_sleep_log(logger, logging.WARNING),
)
def notify_new_housing() -> None:
    """Notify users about new housing."""
    logger.info("======\n\n\nStarting new housing notifier.")
    notifier.notify_new_housing_sync()
    logger.info("Finished new housing notifier.\n\n\n======")


def housing_searches_pipeline() -> None:
    """Pipeline for housing searches."""
    logger.info("Starting housing searches pipeline")
    try:
        etl_searches()
    except Exception:
        logger.exception("Error in housing searches pipeline")
    try:
        notify_revised_housing()
    except Exception:
        logger.exception("Error in notify_revised_housing")
    try:
        notify_new_housing()
    except Exception:
        logger.exception("Error in notify_new_housing")
    logger.info("Finished housing searches pipeline")
