"""Blueground connector."""

import asyncio
import logging
import math
import re
from datetime import date
from decimal import Decimal
from typing import Any, Final, Literal, Self

import niquests
import pydantic as pc
import tenacity

from quieromudarme import db
from quieromudarme.log import setup_logger
from quieromudarme.providers.base import Currency, HousingPost, ProviderName
from quieromudarme.providers.common import gen_user_agent
from quieromudarme.utils import run_async_in_thread

logger = setup_logger()


BASE_URL: Final = "https://www.theblueground.com/pt-br/"
MAX_PAGE_SIZE: Final = 50
DEFAULT_MAX_PAGES: Final = 20


name: Final = ProviderName.BLUEGROUND
max_results_considered: Final = MAX_PAGE_SIZE * DEFAULT_MAX_PAGES


class BluegroundHousingPost(HousingPost):
    """A housing post adapted from Blueground's JSON-in-HTML."""

    model_config = pc.ConfigDict(coerce_numbers_to_str=True, frozen=False)

    provider: ProviderName = ProviderName.BLUEGROUND
    code: str
    post_id: str = pc.Field(validation_alias=pc.AliasPath("id"))
    publisher_id: str = pc.Field(validation_alias=pc.AliasPath("source"))
    path: str
    url: str = ""  # URL is not present, it's generated
    title: str = pc.Field(validation_alias=pc.AliasPath("name"))
    lot_size: int = pc.Field(validation_alias=pc.AliasPath("lotSize"))
    address_building: str | None = pc.Field(validation_alias=pc.AliasPath("address", "building"))
    special_price: bool = pc.Field(validation_alias=pc.AliasPath("specialPrice"))
    base_rent: Decimal = pc.Field(validation_alias=pc.AliasPath("baseRent", "amount"))
    base_rent_currency: Literal[Currency.EUR] = pc.Field(
        validation_alias=pc.AliasPath("baseRent", "currency")
    )
    picture_urls: list[str] = pc.Field(validation_alias=pc.AliasPath("photos"))
    geo_lat: float = pc.Field(validation_alias=pc.AliasPath("address", "lat"))
    geo_lng: float = pc.Field(validation_alias=pc.AliasPath("address", "lng"))
    bedrooms: int
    floor: int | None = pc.Field(default=None, validation_alias=pc.AliasPath("highestFloor"))
    price: Decimal = pc.Field(validation_alias=pc.AliasPath("rent", "amount"))
    price_currency: Literal[Currency.EUR] = pc.Field(
        validation_alias=pc.AliasPath("rent", "currency")
    )
    check_in_date: date | None = pc.Field(
        default=None, validation_alias=pc.AliasPath("rent", "minDuration", "start")
    )
    check_out_date: date | None = pc.Field(
        default=None, validation_alias=pc.AliasPath("rent", "minDuration", "end")
    )
    available_from: date = pc.Field(validation_alias=pc.AliasPath("availableFrom"))

    @pc.computed_field  # type: ignore [prop-decorator]
    @property
    def url_with_dates(self) -> str:
        """Merge base URL with `path` and `available_from`."""
        return f"{BASE_URL}{self.path}?checkIn={self.available_from}&checkOut={self.available_from}"

    @pc.field_validator("picture_urls", mode="before")
    @classmethod
    def validate_picture_urls(cls, v: list[dict[str, str]]) -> list[str]:
        """Get picture URLs from Blueground's JSON."""
        return [pic["url"] for pic in v]

    @pc.model_validator(mode="after")
    def complete_url(self) -> Self:
        """Replace the URL with a full version with dates."""
        self.url = self.url_with_dates
        return self

    @pc.field_serializer(
        "check_in_date", "check_out_date", "available_from", when_used="unless-none"
    )
    def serialize_dates(self, v: date) -> str:
        """Serialize dates as ISO string."""
        return v.isoformat()

    @pc.field_serializer("base_rent", when_used="unless-none")
    def serialize_base_rent(self, v: Decimal) -> float:
        """Serialize base rent as float."""
        return float(v)


class BluegroundSearchResult(pc.BaseModel):
    """Search results from Blueground from JSON-in-HTML."""

    items: list[BluegroundHousingPost] = pc.Field(
        validation_alias=pc.AliasChoices(
            pc.AliasPath("properties", "allProperties", "main"), pc.AliasPath("properties", "main")
        )
    )
    items_per_page: int = pc.Field(
        default=MAX_PAGE_SIZE, validation_alias=pc.AliasPath("configuration", "propertiesPerPage")
    )
    total_items: int = pc.Field(
        validation_alias=pc.AliasChoices(
            pc.AliasPath("properties", "meta", "totalItems"), pc.AliasPath("totalItems")
        )
    )


# TODO: unused
@tenacity.retry(
    wait=tenacity.wait_exponential(multiplier=1, min=4, max=15),
    stop=tenacity.stop_after_attempt(3),
    before_sleep=tenacity.before_sleep_log(logger, logging.WARNING),
)
async def _fetch_page_async_html(url: str, *, page: int | None = None) -> BluegroundSearchResult:
    """Fetch a page of Blueground search results from HTML, async."""
    headers = {"User-Agent": gen_user_agent()}
    params = {"page": str(page)} if page else {}

    logger.debug(f"Requesting Blueground URL {url}, with params {params}")
    resp = niquests.get(url=url, params=params, headers=headers, timeout=20)
    resp.raise_for_status()

    if resp.text is None:
        msg = "No response text"
        raise ValueError(msg)

    json_match = re.search(
        r"<script>window\.__INITIAL_STATE__ *= *(.*?)</script>", resp.text, re.DOTALL
    )
    if json_match is None:
        msg = "Could not find JSON data in HTML response"
        raise ValueError(msg)

    json_data: str = json_match.group(1).strip()
    return BluegroundSearchResult.model_validate_json(json_data)


@tenacity.retry(
    wait=tenacity.wait_exponential(multiplier=1, min=6, max=30),
    stop=tenacity.stop_after_attempt(3),
    before_sleep=tenacity.before_sleep_log(logger, logging.WARNING),
)
async def _fetch_page_async(url: str, *, page: int | None = None) -> BluegroundSearchResult:
    """Fetch a page of Blueground search results from JSON REST API, async."""
    headers = {"User-Agent": gen_user_agent()}
    params = {"items": str(MAX_PAGE_SIZE), "offset": str((page or 0) * MAX_PAGE_SIZE)}

    logger.debug(f"Requesting Blueground URL {url}, with params {params}")
    resp = niquests.get(url=url, params=params, headers=headers, timeout=20)
    resp.raise_for_status()

    if (data := resp.json()) is None:
        msg = "No JSON data in response"
        raise ValueError(msg)

    return BluegroundSearchResult.model_validate(data)


def is_valid_search_url(url: str) -> bool:
    """Return whether the URL is a valid search URL for Blueground."""
    return bool(re.match(r"http(s?)://www\.theblueground\.com/api/furnished-apartments-.+", url))


async def _gather_async_pages(url: str, pages: list[int]) -> list[BluegroundSearchResult]:
    """Gather search results for multiple pages, async."""
    tasks = [asyncio.create_task(_fetch_page_async(url=url, page=page)) for page in pages]
    return await asyncio.gather(*tasks)


def get_search_results(
    url: str, payload: dict[str, Any] | None, *, max_pages: int | None = DEFAULT_MAX_PAGES
) -> tuple[int, list[HousingPost]]:
    """Get results for Blueground search URL."""
    del payload  # unused

    first_page_results: BluegroundSearchResult = run_async_in_thread(_fetch_page_async(url))
    posts: list[HousingPost] = list(first_page_results.items)
    logger.info("Found %d results", first_page_results.total_items)

    last_page_num = int(
        min(
            max_pages if max_pages is not None else float("inf"),
            math.ceil(first_page_results.total_items / first_page_results.items_per_page),
        )
    )
    rest_page_results = run_async_in_thread(
        _gather_async_pages(url, list(range(2, last_page_num + 1)))
    )
    for page_result in rest_page_results:
        posts.extend(page_result.items)

    logger.info(
        f"Fetched {len(posts)=} (from {last_page_num} pages)"
        f" vs {first_page_results.total_items} expected"
    )
    return first_page_results.total_items, posts


def fetch_latest_results(
    search: db.GetHousingSearchesResult, *, max_pages: int | None = None
) -> list[HousingPost]:
    """Fetch latest results for a Blueground search."""
    first_page_url = search.url
    total_results, posts = get_search_results(first_page_url, payload=None, max_pages=max_pages)
    logger.info("Fetched %d posts from %d total results", len(posts), total_results)
    return posts


if __name__ == "__main__":
    """For debugging."""
    import sys

    if len(sys.argv) < 2:  # noqa: PLR2004
        logger.error(f"Usage: {sys.argv[0]} URL")
        sys.exit(1)

    posts = get_search_results(sys.argv[1], payload=None)[1]
    for post in posts:
        logger.info(post.model_dump_json(indent=2))


# TODO: allow receiving HTML URL and convert it to API URL
