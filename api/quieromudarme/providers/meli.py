"""MercadoLibre Inmuebles connector.

See `tmp/ml_preloaded_state.json`.
"""

import asyncio
import json
import logging
import re
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from http import HTTPStatus
from typing import Any, Final, cast

import niquests
import pydantic as pc
import tenacity
from bs4 import BeautifulSoup
from bs4 import Tag as Bs4Tag

from quieromudarme import db
from quieromudarme.errors import QMError
from quieromudarme.logging import setup_logger
from quieromudarme.providers.common import gen_user_agent
from quieromudarme.settings import cfg
from quieromudarme.utils import batched, run_async_in_thread

from .types import Currency, HousingPost, ProviderName

logger = setup_logger()


name = ProviderName.MERCADOLIBRE


class MercadoLibreError(QMError):
    """Errors on MercadoLibre's side or parsing their data."""


class MercadoLibreHousingPost(HousingPost):
    """A housing post from MercadoLibre Inmuebles.

    This accomodates both the API response (https://api.mercadolibre.com/items/MLA...) and the
    JSON embedded in the HTML page when searching (which has less information than the former).
    """

    model_config = pc.ConfigDict(coerce_numbers_to_str=True)

    provider: ProviderName = ProviderName.MERCADOLIBRE
    post_id: str = pc.Field(validation_alias="id")
    url: str = pc.Field(validation_alias="permalink")
    status: str | None = None  # known values: "active"
    title: str = pc.Field(
        validation_alias=pc.AliasChoices(
            "sub_title", pc.AliasPath("subtitles", "item_title"), "title"
        )
    )
    # Could generate a description by joining the 'descriptions'.*.'label' fields in HTML's JSON
    price: Decimal = pc.Field(
        validation_alias=pc.AliasChoices(pc.AliasPath("price", "amount"), "price")
    )
    price_currency: Currency = pc.Field(
        validation_alias=pc.AliasChoices(pc.AliasPath("price", "currency_id"), "currency_id")
    )
    # expenses: Decimal | None = pc.Field(
    #     default=None, validation_alias=pc.AliasPath("expenses", "amount")
    # )
    # expenses_currency: Literal["USD", "ARS"] | None = pc.Field(
    #     default=None, validation_alias=pc.AliasPath("expenses", "currency")
    # )
    # Address in HTML is a one-liner; in API response it's separated in fields
    location_full: str = pc.Field(
        validation_alias=pc.AliasChoices("location", pc.AliasPath("location", "address_line"))
    )
    picture_urls: list[str] = pc.Field(validation_alias=pc.AliasPath("pictures"))
    # probably always an empty string because MeLi puts this number behind a captcha
    whatsapp_phone_number: str | None = pc.Field(
        default=None, validation_alias=pc.AliasPath("seller_contact", "phone")
    )
    antiquity: None = None
    created_at: pc.AwareDatetime | None = pc.Field(default=None, validation_alias="date_created")
    modified_at: pc.AwareDatetime | None = pc.Field(default=None, validation_alias="last_updated")
    publisher_id: str = pc.Field(validation_alias=pc.AliasPath("seller_info", "id"))

    @property
    def address(self) -> str:
        """Full address."""
        return self.location_full.strip()

    @pc.field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Remove tracking and search params."""
        return v.encode().decode("unicode-escape").split("?")[0].split("#")[0]

    @pc.field_validator("picture_urls", mode="before")
    @classmethod
    def validate_picture_urls(
        cls, v: list[dict[str, str]] | dict[str, dict[str, str]]
    ) -> list[str]:
        """Extract URLs for each picture, or grab only picture if not from API response."""
        if isinstance(v, list):  # from API response
            return [pic["secure_url"] for pic in v]
        if only_pic := v.get("grid", {}).get("retina"):  # from JSON in HTML
            return [only_pic]
        return []

    @pc.field_serializer("created_at", when_used="unless-none")
    def serialize_created_at(self, v: datetime) -> str:
        """Serialize datetime as ISO string."""
        return v.isoformat()


class MercadoLibreSearchResult(pc.BaseModel):
    """Flattened response for a MercadoLibre Inmuebles search from its embedded JSON state."""

    model_config = pc.ConfigDict(frozen=True)

    canonical_url: str = pc.Field(validation_alias=pc.AliasPath("canonical_info", "canonical"))
    page_count: int = pc.Field(validation_alias=pc.AliasPath("pagination", "page_count"))
    page_urls: list[str] = pc.Field(
        default_factory=list, validation_alias=pc.AliasPath("pagination", "pagination_nodes_url")
    )
    num_results: int = pc.Field(validation_alias=pc.AliasPath("pagination", "results_limit"))
    results: Sequence[MercadoLibreHousingPost] = pc.Field(validation_alias="results", repr=False)

    @pc.field_validator("page_urls", mode="before")
    @classmethod
    def validate_page_urls(cls, v: list[dict[str, str]]) -> list[str]:
        """Extract the URL for each page."""
        return [node["url"].encode().decode("unicode-escape") for node in v]


# How many posts can be fetched at once from MeLi's API
MELI_API_MAX_IDS: Final = 20


@tenacity.retry(
    wait=tenacity.wait_exponential(multiplier=1, min=4, max=15),
    stop=tenacity.stop_after_attempt(3),
    before_sleep=tenacity.before_sleep_log(logger, logging.WARNING),
)
async def _fetch_page_async(url: str) -> MercadoLibreSearchResult:
    """Fetch a MercadoLibre Inmuebles search page, async."""
    headers = {"User-Agent": gen_user_agent()}

    logger.debug("Fetching MeLi URL: %s", url)
    async with niquests.AsyncSession() as session:
        resp = await session.get(url, headers=headers, timeout=15)

    resp.raise_for_status()
    if resp.text is None:
        msg = "Empty response"
        raise MercadoLibreError(msg)

    # We get a state JSON object in a script tag within the HTML
    soup = BeautifulSoup(resp.text, "html.parser")
    script_tag = cast(Bs4Tag | None, soup.find("script", id="__PRELOADED_STATE__"))
    if script_tag is None or script_tag.string is None:
        if re.search(r'"results":\s*\[\]', resp.text):
            logger.info("No results for this search, maybe because of 'published today' filter")
            return MercadoLibreSearchResult.model_construct(
                canonical_url=url, page_count=0, num_results=0, results=[]
            )
        msg = "Could not find the JSON state in the HTML"
        raise MercadoLibreError(msg)

    preloaded_data = json.loads(script_tag.string.strip())
    preloaded_state = preloaded_data["pageState"]["initialState"]

    # TODO: refactor; own function with own retries;
    #       and probably better to parallelize all requests to API (in batches)
    # Enrich with MercadoLibre API, getting more data for each post
    post_ids = [post["id"] for post in preloaded_state["results"]]
    if len(post_ids) > 0:
        logger.debug(f"Fetching from API for these {len(post_ids)} posts")
        headers = {"Authorization": f"Bearer {cfg.mercadopago_access_token}"}
        api_posts: list[dict[str, Any]] = []
        for post_ids_batch in batched(post_ids, MELI_API_MAX_IDS):
            api_url = f"https://api.mercadolibre.com/items?ids={','.join(post_ids_batch)}"
            resp = niquests.get(api_url, headers=headers)
            if resp.status_code != HTTPStatus.OK:
                logger.warning(
                    "Failed to fetch API data for posts: %s. Ignoring it.", post_ids_batch
                )
                continue
            api_posts.extend([p["body"] for p in resp.json()])

        for i, web_post in enumerate(preloaded_state["results"]):
            api_post = next((p for p in api_posts if p["id"] == web_post["id"]), None)
            if api_post is None:
                logger.warning("No API data for post %s", web_post["id"])
                continue
            preloaded_state["results"][i] = {**api_post, **web_post}

    return MercadoLibreSearchResult.model_validate(preloaded_state)


async def _gather_async_pages(urls: list[str]) -> list[MercadoLibreSearchResult]:
    """Gather search results for multiple URLs, async."""
    tasks = [asyncio.create_task(_fetch_page_async(url)) for url in urls]
    return await asyncio.gather(*tasks)


DEFAULT_MAX_PAGES: Final = 10
RESULTS_PER_PAGE: Final = 48
max_results_considered: Final = DEFAULT_MAX_PAGES * RESULTS_PER_PAGE


def is_valid_search_url(s: str) -> bool:
    """Check if the string is a valid MercadoLibre Inmuebles search URL."""
    return bool(re.match(r"https?://inmuebles\.mercadolibre\.com\.ar/[a-zA-Z0-9/_-]+", s))


def get_search_results(
    url: str, payload: dict[str, Any] | None, *, max_pages: int | None = DEFAULT_MAX_PAGES
) -> tuple[int, list[HousingPost]]:
    """Get the housing posts and number of results from a MercadoLibre Inmuebles search URL."""
    del payload  # unused
    first_page_url = url.split("?")[0].split("#")[0]
    first_page_url = first_page_url.replace("_DisplayType_M", "")  # don't access map view
    # TODO: clean up URL: make sure it doesn't specify a page or offset, map view, etc

    first_page_result = run_async_in_thread(_fetch_page_async(first_page_url))
    posts: list[HousingPost] = list(first_page_result.results)
    logger.info(f"Total results should be: {first_page_result.num_results}")

    rest_page_urls = first_page_result.page_urls[1:max_pages]
    rest_page_results = run_async_in_thread(_gather_async_pages(rest_page_urls))
    for page_result in rest_page_results:
        posts.extend(page_result.results)

    logger.info(
        f"Fetched {len(posts)=} (from {len(rest_page_urls) + 1} pages)"
        f" vs {first_page_result.num_results} expected"
    )
    return first_page_result.num_results, posts


def fetch_latest_results(
    search: db.GetHousingSearchesResult, *, max_pages: int | None = DEFAULT_MAX_PAGES
) -> list[HousingPost]:
    """Fetch latest results for a MercadoLibre Inmuebles search."""
    first_page_url = search.url.split("?")[0].split("#")[0]
    first_page_url = first_page_url.replace("_DisplayType_M", "")  # don't access map view

    published_today_filter = "_PublishedToday_YES"
    first_page_url = first_page_url.replace(published_today_filter, "")
    # if search.last_search_at:
    #     last_search_local_date = (
    #         (search.last_search_at - timedelta(hours=1)).astimezone(tz=const.LOCAL_TZ).date()
    #     )
    #     if last_search_local_date >= datetime.now(tz=const.LOCAL_TZ).date():
    #         # If already searched today in the local tz (and be conservative about it),
    #         # only fetch posts published today
    #         logger.info("Refining search to only posts published today.")
    #         if published_today_filter in first_page_url:
    #             logger.info("Already has 'published today' filter")
    #         elif (idx := first_page_url.find("_NoIndex_True")) == -1:
    #             first_page_url = f"{first_page_url}{published_today_filter}"
    #         else:
    #             first_page_url = (
    #                 f"{first_page_url[:idx]}{published_today_filter}{first_page_url[idx:]}"
    #             )

    total_results, posts = get_search_results(first_page_url, payload=None, max_pages=max_pages)
    logger.info("Fetched %d posts from %d total results", len(posts), total_results)
    return posts
