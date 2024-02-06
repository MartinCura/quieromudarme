"""Module to notify users about their searches."""

import asyncio
from datetime import UTC, datetime, timedelta

import edgedb
import telethon as tg

from quieromudarme import db

from .chatbot import bot as chatbot
from .constants import MAX_NOTIFS_IN_UPDATE_PER_USER
from .logging import setup_logger

logger = setup_logger()


async def notify_new_revisions(tg_client: tg.TelegramClient | None = None) -> None:
    """For each user, notify all updates to their watched housing."""
    db_client = edgedb.create_async_client()
    if tg_client is None:
        tg_client = await chatbot.create_tg_client_async(start=True)

    updated_watches_per_user = await db.get_updated_housing_watches_to_notify(db_client)
    logger.info(
        f"Starting updated revisions notifier for {len(updated_watches_per_user)} Users"
        f" and {sum(len(uw.watches) for uw in updated_watches_per_user)} HousingWatches."
    )
    now = datetime.now(tz=UTC)
    ten_min_ago = now - timedelta(minutes=10)

    for updated_user_watch in updated_watches_per_user:
        await asyncio.sleep(2)  # time for the tg client to breathe
        # Act only on searches created at least 10 minutes ago, for some sanity
        watches = [
            watch for watch in updated_user_watch.watches if watch.search.created_at < ten_min_ago
        ]
        user = updated_user_watch.user
        logger.info(
            "\n\\/----------------------------------------"
            f"\n[Notifier] User {user.telegram_username} ({user.telegram_id})"
            f" will get {len(watches)} notifications."
        )

        # TODO: log which searches cause this

        if len(watches) > MAX_NOTIFS_IN_UPDATE_PER_USER:
            logger.error(
                f"User {user.telegram_username} ({user.telegram_id}) has {len(watches)} updated"
                " housing matches. This is a lot. PROBABLE BUG. Maybe we should warn the user."
            )
            await chatbot.alert_admin(
                f"Too many updated housing matches for user {user.telegram_username}"
                f" ({user.telegram_id}), filtering to {MAX_NOTIFS_IN_UPDATE_PER_USER},"
                f" total: {len(watches)}",
                client=tg_client,
            )
            watches = watches[:MAX_NOTIFS_IN_UPDATE_PER_USER]

        await chatbot.notify_updated_housing(user, watches, client=tg_client)

        user_updated_housing_watches = [
            db.WatchRevisionsitem(hw_id=watch.id, revision_id=watch.current_revision.id)
            for watch in watches
        ]
        logger.info(f"Updating db for {len(user_updated_housing_watches)} HousingWatches")
        db_client = db_client.with_retry_options(edgedb.RetryOptions(attempts=5))
        await db.update_notified_housing_watches(
            db_client, watch_revisions=user_updated_housing_watches, notified_at=now
        )

    logger.info("Finished notifying updated revisions")


def notify_new_revisions_sync() -> None:
    """Sync version of notify_new_revisions."""
    asyncio.run(notify_new_revisions())


async def notify_new_housing(tg_client: tg.TelegramClient | None = None) -> None:
    """For each user, notify all new housing that matches their searches."""
    db_client = edgedb.create_async_client()
    if tg_client is None:
        tg_client = await chatbot.create_tg_client_async(start=True)

    new_housing_per_user = await db.get_new_housing_watches_to_notify(db_client)
    logger.info(
        f"Starting new housing notifier for {len(new_housing_per_user)} Users"
        f" and {sum(len(uw.watches) for uw in new_housing_per_user)} HousingWatches."
    )
    now = datetime.now(tz=UTC)
    ten_min_ago = now - timedelta(minutes=10)

    for new_user_watches in new_housing_per_user:
        await asyncio.sleep(2)  # time for the tg client to breathe
        # Act only on searches created at least 10 minutes ago, for some sanity
        watches = [
            watch for watch in new_user_watches.watches if watch.search.created_at < ten_min_ago
        ]
        user = new_user_watches.user
        logger.info(
            "\n\\/----------------------------------------"
            f"\n[Notifier] User {user.telegram_username} ({user.telegram_id})"
            f" will get {len(watches)} notifications."
        )

        big_search_warning = len(watches) >= 50
        if len(watches) > MAX_NOTIFS_IN_UPDATE_PER_USER:
            logger.error(
                f"User {user.telegram_username} ({user.telegram_id}) has {len(watches)} new"
                " housing matches. This is a lot. PROBABLE BUG."
            )
            await chatbot.alert_admin(
                f"Too many new housing matches for user {user.telegram_username}"
                f" ({user.telegram_id}), filtering to {MAX_NOTIFS_IN_UPDATE_PER_USER},"
                f" total: {len(watches)}",
                client=tg_client,
            )
            watches = watches[:MAX_NOTIFS_IN_UPDATE_PER_USER]

        await chatbot.notify_new_housing(
            user, watches, warn_big_search=big_search_warning, client=tg_client
        )

        user_notified_housing_watches = [
            db.WatchRevisionsitem(hw_id=watch.id, revision_id=watch.current_revision.id)
            for watch in watches
        ]
        logger.info(f"Updating db for {len(user_notified_housing_watches)} HousingWatches")
        db_client = db_client.with_retry_options(edgedb.RetryOptions(attempts=5))
        await db.update_notified_housing_watches(
            db_client, watch_revisions=user_notified_housing_watches, notified_at=now
        )

    logger.info("Finished notifying new housing")


def notify_new_housing_sync() -> None:
    """Sync version of notify_new_housing."""
    asyncio.run(notify_new_housing())
