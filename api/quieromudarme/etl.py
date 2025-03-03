"""ETL for housing data, calling the providers for each housing search."""

import asyncio
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import edgedb

from quieromudarme import db
from quieromudarme.errors import QMError
from quieromudarme.log import setup_logger
from quieromudarme.providers import HousingPost, ProviderName, get_provider_by_name

if TYPE_CHECKING:
    from quieromudarme.chatbot.base import TelegramID

logger = setup_logger()


async def store_housing_posts(
    posts: list[HousingPost],
    search: db.GetHousingSearchesResult | db.InsertHousingSearchResult,
    refreshed_at: datetime,
    db_client: edgedb.AsyncIOClient,
    *,
    as_notified: bool = False,
) -> int:
    """Store housing posts for search in the database.

    Args:
        posts: List of HousingPost objects to store.
        search: HousingSearch for which these posts are being stored.
        refreshed_at: Datetime at which the search was refreshed.
        db_client: Database client to use.
        as_notified: Whether to set up the HousingWatches so that the user will be
            notified of the housing changes, or marked as already notified.

    Returns:
        The total added new housings + revisions for existing housings.
    """
    unique_post_ids = {post.post_id for post in posts}
    if len(unique_post_ids) != len(posts):
        logger.warning(
            f"Investigate dupes. Unique post IDs: {len(unique_post_ids)},"
            f" {len(unique_post_ids) / len(posts):.1%} of results."
        )
        # Remove duplicates
        posts = list({post.post_id: post for post in posts}.values())

    # TODO: reenable this? does it accomplish anything?
    # if search.last_search_at:
    #     logger.debug(f"Filtering results by last search date ({search.last_search_at})")
    #     results = [
    #         post for post in results if post.modified_date >= search.last_search_at
    #     ]

    # The following operations are quite intensive so we add more retries
    db_client = db_client.with_retry_options(edgedb.RetryOptions(attempts=10))

    # DB 1 of 2: upsert housings and their revisions
    posts_json = json.dumps([post.model_dump() for post in posts])
    upserted_housing = await db.upsert_housing_from_search(db_client, housing_posts=posts_json)
    logger.debug("Upserted housing.")

    # DB 2 of 2: upsert housing watches
    housing_ids = [h.id for h in upserted_housing]
    # TODO: this is more inefficient that it should be, e.g. takes 30 s to upsert 60 watches
    await db.upsert_watches_for_search(
        db_client,
        housing_search_id=search.id,
        housing_ids=housing_ids,
        refreshed_at=refreshed_at,
        as_notified=as_notified,
    )
    logger.debug("Upserted watches.")

    n_new_stuff = sum(u.added_revision for u in upserted_housing) + (
        sum(u.is_new for u in upserted_housing)
    )
    # TODO: this should look at what the second db operation does
    logger.info(f"""
        Search: {search.id} {search.url}
        User: {search.user.telegram_username} ({search.user.telegram_id})
        Refreshed at: {refreshed_at}

        - Fetched {len(posts)} results
        - Upserted {len(upserted_housing)} housings
        - Inserted {sum(u.is_new for u in upserted_housing)} new housings
        - Updated {sum(not u.is_new for u in upserted_housing)} existing housings
          - {sum(u.added_revision for u in upserted_housing)} of them have a new revision
          - {sum(not u.is_new and not u.added_revision for u in upserted_housing)} have no changes
        => News: {n_new_stuff}
        {"Notifications suppressed." if as_notified else "Will be sent as notifications."}
    """)
    return n_new_stuff


async def etl_housing_for_search(
    search: db.GetHousingSearchesResult, db_client: edgedb.AsyncIOClient | None = None
) -> int:
    """Fetch latest properties for a housing search and store them.

    Return the number of new housings or revisions added.
    """
    if db_client is None:
        db_client = edgedb.create_async_client()

    provider = get_provider_by_name(ProviderName(search.provider))
    refreshed_at = datetime.now(tz=UTC)

    posts = provider.fetch_latest_results(search)
    logger.debug(f"Fetched {len(posts)} results for search {search.id}")

    as_notified = search.last_search_at is None
    if as_notified:
        logger.warning("First search for this HousingSearch. Will not notify user.")

    n_new_stuff = await store_housing_posts(
        posts=posts,
        search=search,
        refreshed_at=refreshed_at,
        as_notified=as_notified,
        db_client=db_client,
    )
    return n_new_stuff


async def etl_housing_for_all_searches(start_delta: timedelta | None = None) -> None:
    """For each housing search, fetch latest properties and store them.

    Prioritizes premium users.
    """
    db_client = edgedb.create_async_client()
    searches = await db.get_housing_searches(db_client)
    logger.info(f"There are {len(searches)} searches in the database.")
    errors: list[Exception] = []
    n_added_per_user: defaultdict[TelegramID, int] = defaultdict(int)

    # Keep only those created at least 10 minutes ago
    ten_min_ago = datetime.now(tz=UTC) - timedelta(minutes=10)
    searches = [s for s in searches if s.created_at < ten_min_ago]

    if start_delta is not None:
        searches = [
            s
            for s in searches
            if s.last_search_at is None or s.last_search_at < (datetime.now(tz=UTC) - start_delta)
        ]

    logger.info(f"Starting ETL for {len(searches)} searches.")
    for search in searches:
        try:
            logger.info(
                "\n\\/----------------------------------------"
                f"\n[ETL] Search {search.id}: {search.url}"
                f"\nfor user {search.user.telegram_username} ({search.user.telegram_id})"
            )
            n_added_per_user[search.user.telegram_id] += await etl_housing_for_search(
                search, db_client=db_client
            )
        except Exception as err:
            logger.exception(f"Error processing search {search.id}")
            errors.append(err)

    logger.info("\n\n***** ETL finished. *****")
    logger.info(f"Total new properties added: {sum(n_added_per_user.values())}\n")
    for user_id, n_added in n_added_per_user.items():
        logger.info(f" - For user {user_id}: added {n_added}")
    if errors:
        msg = f"{len(errors)} errors during ETL"
        raise QMError({"message": msg, "errors": [str(err) for err in errors]})


def etl_housing_for_all_searches_sync(start_delta: timedelta | None = None) -> None:
    """Sync version of etl_housing_from_searches."""
    asyncio.run(etl_housing_for_all_searches(start_delta))
