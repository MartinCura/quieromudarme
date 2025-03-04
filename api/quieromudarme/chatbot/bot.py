"""Telegram bot."""

import asyncio
import functools
import re
import urllib.parse
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any, Final

import edgedb
import telethon as tg
import telethon.tl.custom as tg_custom

from quieromudarme import constants as const
from quieromudarme import db
from quieromudarme.etl import store_housing_posts
from quieromudarme.log import setup_logger
from quieromudarme.providers import ProviderName, clean_search_url, get_provider_by_url
from quieromudarme.settings import cfg

from . import content
from .state import ConversationStatus, conversation_states

logger = setup_logger()


def create_tg_client(*, start: bool = False) -> tg.TelegramClient:
    """Create a new Telegram client and start it."""
    # TODO: consider using different session strings for different callers
    session_name = f"bot-{cfg.tg_bot_id}"
    client = tg.TelegramClient(session_name, cfg.tg_app_api_id, cfg.tg_app_api_hash)
    if start:
        client.start(bot_token=cfg.tg_bot_token)
    return client


async def create_tg_client_async(*, start: bool = False) -> tg.TelegramClient:
    """Create a new Telegram client and start it, async version."""
    client = create_tg_client(start=False)
    if start:
        await client.start(bot_token=cfg.tg_bot_token)
    me = await client.get_me()
    logger.info(f"Bot started as @{me.username} ({me.id})")
    if me.id != cfg.tg_bot_id:
        error_msg = f"Bot started as @{me.username} ({me.id}), but expected {cfg.tg_bot_id}."
        raise RuntimeError(error_msg)
    return client


async def alert_admin(message: str, client: tg.TelegramClient | None = None) -> None:
    """Send a message to the admin about an error."""
    if client is None:
        client = await create_tg_client_async(start=True)

    await client.send_message(cfg.admin_tg_user_id, f"[🤖] {message}")


def _last_modified_dt_str(dt: datetime | None) -> str:
    """Format a datetime to a nice string in Argentina tz, unless None."""
    # TODO: how about a human date diff since now? e.g. "hace 2 horas"
    if not dt:
        return ""
    dt_arg = dt.astimezone(tz=const.LOCAL_TZ)
    return f"__Últ. modificación: {dt_arg.strftime('%H:%M del %d/%m')}__"


def _price_str(
    revision: db.GetNewHousingWatchesToNotifyResultWatchesItemCurrentRevision, *, bold: bool = True
) -> str:
    """Format a price and currency to a nice string."""
    if revision.price == 0:
        return "Consultar"
    s = f"$ {revision.price:,.0f} {revision.currency}"
    return f"**{s}**" if bold else s


def _housing_buttons(
    housing: db.GetNewHousingWatchesToNotifyResultWatchesItemHousing,
) -> list[tg_custom.Button]:
    """Create buttons for a housing post message."""
    buttons = [tg_custom.Button.url(f"{housing.provider}", housing.url)]

    if housing.whatsapp_phone_number:  # TODO: sanitize this phone number!
        greeting = urllib.parse.quote_plus(
            f"Hola! Vi esta publicación en {housing.provider} y me interesa."
            " Podemos coordinar una visita?"
            f"\n\n{housing.url}"
        )
        whatsapp_link = f"https://wa.me/{housing.whatsapp_phone_number}?text={greeting}"
        buttons.append(tg_custom.Button.url("Contactar", whatsapp_link))

    return buttons


def bren_special_alert(
    text_msg: str,
    housing: db.GetNewHousingWatchesToNotifyResultWatchesItemHousing,
    user: db.GetNewHousingWatchesToNotifyResultUser,
) -> str:
    """Special alert for Bren: in case of mention of 7th or higher floor."""
    bren_tg_id: Final = 1962124742
    if user.telegram_id != bren_tg_id and user.telegram_username != "martincura":
        return text_msg

    s = f"{housing.title or ''} {housing.description or ''}"
    matches = (re.search(r"(7|8|9|\d\d)(?:\s*°|º|\w+)\s*piso(?! [1-6]\b)", s, re.IGNORECASE)) or (
        re.search(r"(?<!\d )piso.{0,5}(7|8|9|\d\d)", s, re.IGNORECASE)
    )
    if matches:
        logger.debug(f"Special Bren Alert: {matches.group(0)}")
        text_msg += f"\n\n🚨 Piso alto?? ({matches.group(0)}) Investigarrrr"
    return text_msg


def sanitize_str_for_tg(s: str | None) -> str:
    """Sanitize a string for Telegram by removing all Markdown delimiters."""
    if s is None:
        return "Propiedad sin nombre"
    return re.sub(r"[\*_`~\\]", "", s)


async def notify_updated_housing(
    user: db.GetNewHousingWatchesToNotifyResultUser,
    watches: list[db.GetUpdatedHousingWatchesToNotifyResultWatchesItem],
    *,
    client: tg.TelegramClient | None = None,
) -> None:
    """Notify user of updated housing posts."""
    # TODO: should catch errors in sending and return which were notified
    if client is None:
        client = await create_tg_client_async(start=True)

    messages: list[tuple[str, list[tg_custom.Button] | None]] = [
        (
            f"🗞🗞🗞 {len(watches)}"
            + (
                " propiedades de tus búsquedas cambiaron de moneda o bajaron"
                if len(watches) > 1
                else " propiedad de tus búsquedas cambió de moneda o bajó"
            )
            + f" de precio al menos {const.PRICE_OFF_PCT_THRESHOLD:.0%}.",
            None,
        )
    ]
    for hw in watches:
        text_msg = (
            f'🔽 "{sanitize_str_for_tg(hw.housing.title)}"'
            f"\n{_price_str(hw.old_revision, bold=False)} → {_price_str(hw.current_revision)}"
            f"\n{_last_modified_dt_str(hw.housing.post_modified_at)}"
            f"\n[publicación]({hw.housing.url}) | [búsqueda]({hw.search.url})"
        )
        text_msg = bren_special_alert(text_msg, hw.housing, user)
        messages.append((text_msg, _housing_buttons(hw.housing)))
    for message, buttons in messages:
        try:
            await client.send_message(entity=user.telegram_id, message=message, buttons=buttons)
        except tg.errors.rpcerrorlist.UserIsBlockedError:
            logger.warning(
                f"User {user.telegram_id} ({user.telegram_username}) has blocked the bot."
            )
            break
        except Exception:
            logger.exception(
                f"Error sending to user {user.telegram_id} the message:"
                f"\n{message}"
                f"\nwith buttons: {buttons}"
            )
            raise


async def notify_new_housing(
    user: db.GetNewHousingWatchesToNotifyResultUser,
    watches: list[db.GetNewHousingWatchesToNotifyResultWatchesItem],
    *,
    warn_big_search: bool = False,
    client: tg.TelegramClient | None = None,
) -> None:
    """Notify user of new housing posts."""
    # TODO: should catch errors in sending and return which were notified
    if client is None:
        client = await create_tg_client_async(start=True)

    messages: list[tuple[str, list[tg_custom.Button] | None]] = [
        (
            (
                f"🗞🗞🗞 {len(watches)} nuevas propiedades para tus búsquedas."
                if len(watches) > 1
                else f"🗞🗞🗞 {len(watches)} nueva propiedad para tus búsquedas."
            ),
            None,
        )
    ]
    for hw in watches:
        text_msg = (
            f'🆕 "{sanitize_str_for_tg(hw.housing.title)}"'
            f"\n{_price_str(hw.current_revision)}"
            f"\n{_last_modified_dt_str(hw.housing.post_modified_at)}"
            f"\n[publicación]({hw.housing.url}) | [búsqueda]({hw.search.url})"
        )
        text_msg = bren_special_alert(text_msg, hw.housing, user)
        messages.append((text_msg, _housing_buttons(hw.housing)))
    if warn_big_search:
        messages.append(
            (
                (
                    "⚠️ **Esta búsqueda parece retornar muchos resultados nuevos.** No te enviamos"
                    f" más de {const.MAX_NOTIFS_IN_UPDATE_PER_USER} a la vez. Considerá borrarla"
                    " y hacer una más específica, o vas a estar recibiendo demasiadas alertas."
                ),
                None,
            )
        )
    for message, buttons in messages:
        try:
            await client.send_message(entity=user.telegram_id, message=message, buttons=buttons)
        except tg.errors.rpcerrorlist.UserIsBlockedError:
            logger.warning(
                f"User {user.telegram_id} ({user.telegram_username}) has blocked the bot."
            )
            break
        except Exception:
            logger.exception(
                f"Error sending to user {user.telegram_id} the message:"
                f"\n{message}"
                f"\nwith buttons: {buttons}"
            )
            raise


####################


async def log_event(event: tg.events.NewMessage.Event) -> None:
    """Log received message."""
    chat: tg.types.Chat = await event.get_chat()
    logger.debug(f"Received:\n> {chat.username} ({chat.id}): '{event.message.message}'")


async def get_or_create_user(
    event: tg.events.NewMessage.Event, *, db_client: edgedb.AsyncIOClient | None = None
) -> db.UpsertUserResult:
    """Get or create the user from the database."""
    if db_client is None:
        db_client = edgedb.create_async_client()
    chat: tg.types.Chat = await event.get_chat()
    user = await db.upsert_user(db_client, telegram_id=chat.id, telegram_username=chat.username)
    if not user:
        msg = "User upsert somehow failed!!"
        raise RuntimeError(msg)
    return user


def can_user_create_search(user: db.UpsertUserResult) -> bool:
    """Check if user can create a new housing search."""
    return user.tier.value != db.UserTier.FREE.value or len(user.searches) < const.MAX_FREE_SEARCHES


async def create_search(  # noqa: C901
    event: tg.events.NewMessage.Event, user: db.UpsertUserResult, search_url: str
) -> None:
    """Create a new housing search for the user based on their input."""
    if not (provider := get_provider_by_url(search_url)):
        await event.reply(
            f"⚠️ No se reconoció el link. Por ahora solo funcionamos con los siguientes sitios:\n"
            f"\n👉 {ProviderName.ZONAPROP}"
            f"\n👉 {ProviderName.MERCADOLIBRE}"
            "\n\nSi querías usar otro sitio contanos cuál y por qué con /sugerencias y veremos"
            " de agregarlo pronto!"
        )
        return

    if provider.name in [ProviderName.ZONAPROP, ProviderName.MERCADOLIBRE]:
        search_url = clean_search_url(search_url)

    conversation_states[user.telegram_id].status = ConversationStatus.IDLE

    if not can_user_create_search(user):
        await event.reply(
            f"⚠️ Lo siento, pero por ahora solo puedes tener hasta {const.MAX_FREE_SEARCHES}"
            f" {'búsquedas' if const.MAX_FREE_SEARCHES > 1 else 'búsqueda'}."
        )
        return

    # TODO: refactor into provider-specific clean_search_url, together with payload
    if provider.name == ProviderName.MERCADOLIBRE:
        published_today_filter = "_PublishedToday_YES"
        search_url = search_url.replace(published_today_filter, "")

    db_client = edgedb.create_async_client()
    if await db.get_housing_search_by_url(
        db_client, user_id=user.id, provider=provider.name, search_url=search_url
    ):
        # TODO: check what happens with soft-deleted searches
        await event.reply(f"⚠️ Ya tenés una búsqueda para {provider.name} con el mismo link.")
        return

    msg_processing: tg.custom.Message = await event.reply(
        "Procesando la búsqueda. Esto puede tardar unos segundos..."
    )
    parsed_payload = None  # TODO: clean this up

    now = datetime.now(tz=UTC)
    try:
        total_results, posts = provider.get_search_results(search_url, parsed_payload)
        # TODO: only get number of results then async get the posts and store them
    except Exception:
        logger.exception("Error getting search results. Continuing anyway.")
        total_results, posts = None, []

    await msg_processing.delete()
    if total_results == 0:
        await event.reply("⚠️ No se encontraron resultados para esa búsqueda.")
        return

    if total_results is not None:
        if total_results > const.EXCESSIVE_RESULTS_ERROR:
            logger.warning(f"Excessive results error for search: {total_results}")
            await event.respond(
                "❌ **Esta búsqueda retornó demasiados resultados**, probá de nuevo agregando"
                " más filtros para hacerla más específica."
            )
            return

        await event.respond(
            f"En este momento hay {total_results} publicaciones que coinciden con esta búsqueda."
            " Recordá que no te vamos a avisar sobre estas existentes a menos que bajen de precio."
        )
        if total_results > const.EXCESSIVE_RESULTS_WARNING:
            await event.respond(
                "**Esta búsqueda parece retornar muchos resultados**, considerá borrarla y hacer"
                f" una más específica. Solo tomaré en cuenta los {provider.max_results_considered}"
                " resultados más recientes cada vez que haga la búsqueda por vos."
            )

    created_search = await db.insert_housing_search(
        db_client,
        user_id=user.id,
        provider=provider.name,
        search_url=search_url,
        query_payload=None,
        # query_payload=json.dumps(parsed_payload) if parsed_payload else None,
    )
    await event.reply(
        f"✅ Búsqueda creada para {provider.name}."
        f"\n`{search_url}`"
        "\n\nDesde ahora te voy a avisar cuando haya novedades! 🚀"
    )

    if len(posts):
        logger.debug(f"Storing this initial list of {len(posts)} posts")
        await store_housing_posts(
            posts=posts,
            search=created_search,
            refreshed_at=now,
            db_client=db_client,
            as_notified=True,
        )
        logger.debug("Finished storing posts for new search.")


def make_list_of_user_searches(
    user: db.UpsertUserResult, *, easycopy: bool = False
) -> tuple[str, int]:
    """Get a message of the user's housing searches, and how many they have.

    With easycopy=True, the URLs are formatted as code for easy copying.
    """
    # TODO: should be split into messages or sth or else it breaks (MessageTooLongError)
    if len(user.searches) == 0:
        msg = "No tenés búsquedas en este momento."
    else:
        msg = "🔍 Tus búsquedas actuales son:\n\n"
        msg += "\n".join(
            [
                (
                    f"👉 {f'`{search.url}`' if easycopy else search.url}"
                    f" (creada: {search.created_at.date()})"
                )
                for search in user.searches
            ]
        )
    return msg, len(user.searches)


async def delete_search_by_url(
    event: tg.events.NewMessage.Event, user: db.UpsertUserResult, search_url: str
) -> None:
    """Delete a user's housing search by URL."""
    db_client = edgedb.create_async_client()

    if search_url.lower() == "confirmar" and len(user.searches) == 1:
        # Special case: delete the user's only search
        search_url = user.searches[0].url

    provider = get_provider_by_url(search_url)
    if not provider:
        await event.reply(
            "⚠️ Error. Ese link de búsqueda es válido?"
            " Acordate de que por ahora solo tenemos soporte para ZonaProp y MercadoLibre."
        )
        return

    deleted_search = await db.delete_housing_search_by_url(
        db_client, user_id=user.id, provider=provider.name, search_url=search_url
    )
    if not deleted_search:
        await event.reply("⚠️ No se encontró ninguna búsqueda con ese link.")
        return

    await event.reply(
        "🗑 Búsqueda borrada."
        f"\n\n`{search_url}`"
        "\n\nNo te olvides de que si tenés un problema o sugerencia podés mandarla con /sugerencia."
    )
    conversation_states[user.telegram_id].status = ConversationStatus.IDLE


async def process_feedback(
    bot: tg.TelegramClient,
    event: tg.events.NewMessage.Event,
    user: db.UpsertUserResult,
    message: str,
) -> None:
    """Send user's feedback to the bot admin."""
    msg = (
        f"Feedback de @{user.telegram_username} ({user.telegram_id}):<br/>"
        f"<blockquote><br/>{message}<br/></blockquote><br/>"
    )
    await bot.send_message(cfg.admin_tg_user_id, msg, parse_mode="html")

    await event.reply("✅ Feedback recibido. ¡Gracias!")
    conversation_states[user.telegram_id].status = ConversationStatus.IDLE


#########


async def run_async() -> None:  # noqa: C901, PLR0915
    """Start the chatbot: listen and respond to messages."""
    logger.info("Starting bot...")
    bot = await create_tg_client_async(start=True)

    def handle_errors(
        func: Callable[[tg.events.NewMessage.Event], Coroutine[Any, Any, None]],
    ) -> Callable[[tg.events.NewMessage.Event], Coroutine[Any, Any, None]]:
        """Decorator to catch errors, send responses, and notify admin."""

        @functools.wraps(func)
        async def wrapper(event: tg.events.NewMessage.Event) -> None:
            try:
                await func(event)
            except Exception as e:
                admin_msg = f"Error en {func.__name__}: {e!s}\n\n"
                admin_msg += f"Usuario: {event.chat_id}\n"
                admin_msg += f"Mensaje: {event.message.message}\n\n"
                logger.exception(f"Error in handler {func.__name__}")
                try:
                    await alert_admin(admin_msg, bot)
                    await event.reply(
                        "Upa, tengo algún cable suelto, no pude procesar ese mensaje. "
                        "(Ya notifiqué al admin para que investigue el problema.)"
                    )
                except Exception:
                    logger.exception("Failed to send error notification")
                raise

        return wrapper

    @bot.on(
        tg.events.NewMessage(
            pattern=r"(?i)/?(start|help|empezar|ayuda|hola|holis)\s*$", incoming=True
        )
    )  # type: ignore [misc]
    @handle_errors
    async def help_handler(event: tg.events.NewMessage.Event) -> None:
        """Send explanation of what the bot does and how to use it."""
        await log_event(event)
        # TODO: refactor
        for i, text in enumerate(content.HELP_MSGS):
            await event.respond(
                text,
                link_preview=False,
                # TODO: make this more efficient with a file ID or something
                file=("./static/help_1.png" if i == 1 else None),
            )
        conversation_states[event.chat_id].status = ConversationStatus.IDLE

    @bot.on(tg.events.NewMessage(pattern=r"(?i)/(crear|nuevo|nueva|new)", incoming=True))  # type: ignore [misc]
    @handle_errors
    async def create_housing_search_handler(event: tg.events.NewMessage.Event) -> None:
        """Create new housing search for this user."""
        await log_event(event)
        user = await get_or_create_user(event)
        message: str = event.message.message
        args = message.strip().split()

        if not message or len(args) > 2:  # noqa: PLR2004
            await event.reply("⚠️ No te entendí. Probá mandar solo /crear.")
            return None
        if not can_user_create_search(user):
            await event.reply(
                f"⚠️ Lo siento, pero por ahora solo podés tener hasta {const.MAX_FREE_SEARCHES}"
                f" {'búsquedas' if const.MAX_FREE_SEARCHES > 1 else 'búsqueda'}."
            )
            return None

        if len(args) == 1:
            await event.reply(
                "Buenísimo, creemos una búsqueda nueva. Puede ser para alquilar o comprar, casas"
                " o deptos, ¡lo que necesites!"
                "\n\nIntentá que sea **específica** para que no te lleguen demasiados mensajes y te"
                " hartes de mí. 😅 **Tenés que hacerla en la compu así podés copiar la dirección!**"
                "\n\nMandame el link entero de tu búsqueda. Debería verse algo como: `https://www.zonaprop.com.ar/departamentos-alquiler-....html`."
                "\n\nTambién podés mandar /cancelar para no crear nada."
            )
            conversation_states[user.telegram_id].status = ConversationStatus.CREATING_SEARCH
            return None

        return await create_search(event, user, search_url=args[1].strip())

    @bot.on(tg.events.NewMessage(pattern=r"(?i)/(listar|list|busquedas)", incoming=True))  # type: ignore [misc]
    @handle_errors
    async def list_housing_searches_handler(event: tg.events.NewMessage.Event) -> None:
        """List all housing searches for this user."""
        await log_event(event)
        user = await get_or_create_user(event)

        msg, _ = make_list_of_user_searches(user)
        await event.reply(msg, link_preview=False)
        conversation_states[user.telegram_id].status = ConversationStatus.IDLE

    @bot.on(tg.events.NewMessage(pattern=r"(?i)/(borrar|eliminar|delete)", incoming=True))  # type: ignore [misc]
    @handle_errors
    async def delete_housing_search_handler(event: tg.events.NewMessage.Event) -> None:
        """Delete a housing search for this user."""
        await log_event(event)
        message: str = event.message.message
        user = await get_or_create_user(event)

        if len(message.strip().split()) > 1:
            await event.respond("(Este comando solo funciona con confirmación.)")

        msg, n_searches = make_list_of_user_searches(user, easycopy=True)
        await event.respond(msg, link_preview=False)
        if n_searches == 0:
            conversation_states[user.telegram_id].status = ConversationStatus.IDLE
            return

        if n_searches == 1:
            await event.reply(
                "👇 Mandame 'confirmar' para borrar la única búsqueda que tenés."
                " También podés mandar /cancelar para no borrar nada."
            )
        else:
            await event.reply(
                "👇 Mandame el link de la búsqueda que querés borrar (podés tocarla para copiarla)."
                " También podés mandar /cancelar para no borrar nada."
            )
        conversation_states[user.telegram_id].status = ConversationStatus.DELETING_SEARCH

    @bot.on(tg.events.NewMessage(pattern=r"(?i)/(sugerencia(s)?|feedback)", incoming=True))  # type: ignore [misc]
    @handle_errors
    async def feedback_handler(event: tg.events.NewMessage.Event) -> None:
        """Send feedback to the bot admin."""
        await log_event(event)
        db_client = edgedb.create_async_client()
        user = await get_or_create_user(event, db_client=db_client)

        message: str = event.message.message.strip()
        if not message or len(message.split()) <= 1:
            await event.reply(
                "Nos encanta que nos envíen sus dudas, ideas y los problemas que han tenido con"
                " el bot. (Mejor aún si nos aclarás que podemos contactarte para más preguntas.)"
                "\n\n"
                "👇👇 Dejanos acá tus sugerencias en 1 mensaje. 👇👇"
            )
            conversation_states[user.telegram_id].status = ConversationStatus.SENDING_FEEDBACK
            return

        await process_feedback(bot, event, user, message)
        conversation_states[user.telegram_id].status = ConversationStatus.IDLE

    @bot.on(tg.events.NewMessage(pattern=r"(?i)/?(cancelar)", incoming=True))  # type: ignore [misc]
    @handle_errors
    async def cancel_handler(event: tg.events.NewMessage.Event) -> None:
        """Cancel any ongoing conversation status."""
        await log_event(event)
        chat: tg.types.Chat = await event.get_chat()
        conversation_states[chat.id].status = ConversationStatus.IDLE
        await event.reply("Operación cancelada.")

    @bot.on(tg.events.NewMessage(pattern=r"^\s*https?://", incoming=True))  # type: ignore [misc]
    @handle_errors
    async def url_handler(event: tg.events.NewMessage.Event) -> None:
        """Identify if this is a provider URL and assume the user wants to create a search."""
        await log_event(event)
        user = await get_or_create_user(event)
        message: str = event.message.message.strip()

        if conversation_states[user.telegram_id].status != ConversationStatus.IDLE:
            logger.debug("Ignoring received URL while in a conversation.")
            return None

        return await create_search(event, user, search_url=message)

    ## Admin commands

    @bot.on(tg.events.NewMessage(pattern=r"^!create \d+ https", incoming=True))  # type: ignore [misc]
    @handle_errors
    async def admin_create_housing_search_for_user_handler(
        event: tg.events.NewMessage.Event,
    ) -> None:
        """(Admin command.) Create new housing search for the selected user."""
        await log_event(event)
        message: str = event.message.message.strip()
        args = [a.strip() for a in message.split()]
        if not message or len(args) != 3:  # noqa: PLR2004
            await event.reply("⚠️ No te entendí.")
            return None

        _, user_tg_id, url = args
        db_client = edgedb.create_async_client()
        user = await db.upsert_user(db_client, telegram_id=int(user_tg_id), telegram_username=None)
        if not user:
            msg = "User upsert somehow failed!"
            raise RuntimeError(msg)
        if not can_user_create_search(user):
            await event.reply(
                f"⚠️ El usuario solo puede tener hasta {const.MAX_FREE_SEARCHES}"
                f" {'búsquedas' if const.MAX_FREE_SEARCHES > 1 else 'búsqueda'}."
            )
            return None

        return await create_search(event, user, search_url=url)

    @bot.on(tg.events.NewMessage(pattern=r"^\s*[^/!]", incoming=True))  # type: ignore [misc]
    @handle_errors
    async def default_handler(event: tg.events.NewMessage.Event) -> None:
        """Catch all messages not starting on a command, respond based on current user state.

        Do note that the pattern is generous thus this can be called at the same time as other
        handlers, thus it's best if it doesn't do anything in the case of IDLE state.
        """
        await log_event(event)
        user = await get_or_create_user(event)
        message: str = event.message.message.strip()

        match conversation_states[user.telegram_id].status:
            case ConversationStatus.IDLE:
                return None  # do nothing
            case ConversationStatus.CREATING_SEARCH:
                return await create_search(event, user, search_url=message)
            case ConversationStatus.DELETING_SEARCH:
                return await delete_search_by_url(event, user, search_url=message)
            case ConversationStatus.SENDING_FEEDBACK:
                return await process_feedback(bot, event, user, message=message)

    @bot.on(tg.events.NewMessage(pattern=r"!ping", incoming=True))  # type: ignore [misc]
    @handle_errors
    async def ping_handler(event: tg.events.NewMessage.Event) -> None:
        """Respond "!pong" whenever someone sends "!ping", then delete both messages."""
        m = await event.respond("!pong")
        await log_event(event)
        conversation_states[event.chat_id].status = ConversationStatus.IDLE

        await asyncio.sleep(3)
        await event.message.delete()
        await asyncio.sleep(1)
        await m.delete()

    @bot.on(tg.events.NewMessage(pattern=r"^!announce ", incoming=True))  # type: ignore [misc]
    @handle_errors
    async def announcement_handler(event: tg.events.NewMessage.Event) -> None:
        """Send an announcement to all users. Admin-only."""
        await log_event(event)
        chat: tg.types.Chat = await event.get_chat()
        if chat.id != cfg.admin_tg_user_id:
            await event.reply("⚠️ No tenés permiso para usar este comando.")
            return

        db_client = edgedb.create_async_client()
        users = await db.get_users(db_client)
        message = re.sub(r"^\s*!announce ", "", event.message.message)

        for user in users:
            try:
                await bot.send_message(user.telegram_id, message)
            except tg.errors.rpcerrorlist.UserIsBlockedError:
                logger.warning(
                    f"User {user.telegram_id} ({user.telegram_username}) has blocked the bot."
                )
            except Exception:
                logger.exception(
                    f"Error sending to user {user.telegram_id} the message:\n{message}"
                )

        await event.reply("✅ Mensaje enviado a todos los usuarios.")

    @bot.on(tg.events.NewMessage(pattern=r"^!message \d+", incoming=True))  # type: ignore [misc]
    @handle_errors
    async def admin_message_handler(event: tg.events.NewMessage.Event) -> None:
        """Send an admin message to a particular user. Admin-only.

        `!message <user_id> <message...>`
        """
        await log_event(event)
        msg: str = event.message.message
        chat: tg.types.Chat = await event.get_chat()
        if chat.id != cfg.admin_tg_user_id:
            await event.reply("⚠️ No tenés permiso para usar este comando.")
            return

        db_client = edgedb.create_async_client()
        _, user_tg_id, message = msg.split(maxsplit=2)
        users = await db.get_users(db_client)  # TODO: change to more specific, efficient query
        user = next((u for u in users if u.telegram_id == int(user_tg_id)), None)
        if not user:
            await event.reply("⚠️ No se encontró el usuario.")
            return

        # TODO: catch errors and return reason to admin
        await bot.send_message(user.telegram_id, message)
        await bot.send_message(chat.id, f"[COPY] {message}")
        await event.reply("✅ Mensaje enviado al usuario.")

    logger.info("Chatbot ONLINE.")
    # TODO: somehow only send once in dev if autorestarting
    await bot.send_message(cfg.admin_tg_user_id, "`Chatbot ONLINE.`")

    await bot.run_until_disconnected()


def run() -> None:
    """ENTRYPOINT. Start the chatbot: listen and respond to messages."""
    try:
        asyncio.run(run_async())
    except KeyboardInterrupt:
        logger.warning("Shutting down bot...")


if __name__ == "__main__":
    run()
