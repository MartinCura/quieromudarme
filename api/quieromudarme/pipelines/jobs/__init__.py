"""Quieromudarme scheduler jobs."""

from pathlib import Path

from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from pytz import utc

from quieromudarme.log import setup_logger

logger = setup_logger("etl", log_filepath=Path() / "logs" / "etl.log")

from .housing_searches_job import housing_searches_pipeline  # noqa: E402


def run_scheduler() -> None:
    """Run the APScheduler."""
    scheduler = BlockingScheduler(timezone=utc)
    scheduler.add_jobstore(MemoryJobStore())
    scheduler.add_job(
        func=housing_searches_pipeline, trigger=CronTrigger.from_crontab("0 */2 * * *")
    )
    logger.info("Starting scheduler")
    scheduler.start()


if __name__ == "__main__":
    run_scheduler()
