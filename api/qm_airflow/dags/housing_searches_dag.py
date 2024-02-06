"""DAG to look for new housings for each housing search."""

from datetime import UTC, datetime, timedelta
from typing import Unpack

from airflow.decorators import dag, task
from airflow.utils.context import Context
from airflow.utils.trigger_rule import TriggerRule

from quieromudarme import etl, notifier
from quieromudarme.logging import setup_logger

logger = setup_logger()


def handle_failure(_context: Context) -> None:
    """Send a message to the admin about an error in the DAG."""
    # logger.debug("Handling failure, notifying admin.")
    # dag_info = context.get("dag")
    # run_async_in_thread(
    #     alert_admin(
    #         f"Error in DAG `{dag_info.dag_id if dag_info else '[Unknown]'}`:"
    #         f"\n```{context.get('exception')}```"
    #     )
    # )
    # logger.debug("Admin notified.")
    logger.warning("Doing nothing because calling async functions breaks this.")


@dag(
    schedule="0 */2 * * *",  # at the start of every 2 hours
    catchup=False,
    max_active_runs=1,
    tags=["quieromudarme", "providers"],
    default_args={
        "owner": "martin",
        "depends_on_past": False,
        "start_date": datetime(2024, 1, 1, tzinfo=UTC),
        "retries": 2,
        "retry_delay": timedelta(minutes=4),
        "execution_timeout": timedelta(minutes=65),  # TODO: is this dangerous for the notifier?
        "on_failure_callback": handle_failure,
    },
)
def housing_searches_dag() -> None:
    """DAG to look for new housings for each housing search and notify them."""

    @task.python
    def etl_all_searches(
        **kwargs: Unpack[Context],  # type: ignore [misc]
    ) -> None:
        logger.info("======\n\n\nStarting ETL.")
        # TODO: should it only get properties where
        #       [data_interval_start <=] modified_date <= data_interval_end ?
        #       in this case i should revisit the `catchup` DAG parameter
        dag_run = kwargs.get("dag_run")
        is_manual_run = bool(dag_run.external_trigger if dag_run else False)
        logger.debug("Is manual run: %s", is_manual_run)
        start_delta = None if is_manual_run else timedelta(minutes=90)

        etl.etl_housing_for_all_searches_sync(start_delta=start_delta)
        logger.info("Finished ETL.\n\n\n======")

    @task.python(trigger_rule=TriggerRule.ALL_DONE)
    def notify_new_revisions() -> None:
        logger.info("======\n\n\nStarting new revisions notifier.")
        notifier.notify_new_revisions_sync()
        logger.info("Finished new revisions notifier.\n\n\n======")

    @task.python
    def notify_new_housing() -> None:
        logger.info("======\n\n\nStarting new housing notifier.")
        notifier.notify_new_housing_sync()
        logger.info("Finished new housing notifier.\n\n\n======")

    etl_task = etl_all_searches()
    notify1_task = notify_new_revisions()
    notify2_task = notify_new_housing()

    etl_task >> notify1_task >> notify2_task


housing_searches_dag_ = housing_searches_dag()
