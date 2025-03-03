"""Blueground connector."""

import asyncio
import logging
import math
import re
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Final, Literal

import niquests
import pydantic as pc
import tenacity

from quieromudarme import db
from quieromudarme.logging import setup_logger
from quieromudarme.providers.base import Currency, HousingPost, ProviderName
from quieromudarme.utils import run_async_in_thread

logger = setup_logger()


BASE_URL: Final = "https://www.theblueground.com/pt-br/"

name: Final = ProviderName.BLUEGROUND


class BluegroundHousingPost(HousingPost):
    """A housing post adapted from Blueground's JSON-in-HTML."""

    model_config = pc.ConfigDict(coerce_numbers_to_str=True, frozen=False)

    provider: ProviderName = ProviderName.BLUEGROUND
    code: str
    post_id: str = pc.Field(validation_alias=pc.AliasPath("id"))
    path: str
    title: str = pc.Field(validation_alias=pc.AliasPath("name"))
    lot_size: int = pc.Field(validation_alias=pc.AliasPath("lotSize"))
    address: str = pc.Field(validation_alias=pc.AliasPath("address", "building"))
    special_price: bool = pc.Field(validation_alias=pc.AliasPath("specialPrice"))
    base_rent: Decimal = pc.Field(validation_alias=pc.AliasPath("baseRent", "amount"))
    base_rent_currency: Literal[Currency.EUR] = pc.Field(
        validation_alias=pc.AliasPath("baseRent", "currency")
    )
    picture_urls: list[str] = pc.Field(validation_alias=pc.AliasPath("photos"))
    geo_lat: float = pc.Field(validation_alias=pc.AliasPath("address", "lat"))
    geo_lng: float = pc.Field(validation_alias=pc.AliasPath("address", "lng"))
    bedrooms: int
    floor: int = pc.Field(validation_alias=pc.AliasPath("highestFloor"))
    price: Decimal = pc.Field(validation_alias=pc.AliasPath("rent", "amount"))
    price_currency: Literal[Currency.EUR] = pc.Field(
        validation_alias=pc.AliasPath("rent", "currency")
    )
    check_in_date: date = pc.Field(validation_alias=pc.AliasPath("rent", "minDuration", "start"))
    check_out_date: date = pc.Field(validation_alias=pc.AliasPath("rent", "minDuration", "end"))
    available_from: date = pc.Field(validation_alias=pc.AliasPath("availableFrom"))

    @pc.computed_field
    @property
    def url(self) -> str:
        """Merge base URL with `path`."""
        return f"{BASE_URL}{self.path}"

    @pc.computed_field
    @property
    def url_with_dates(self) -> str:
        """Merge base URL with `path` and `available_from`."""
        return f"{BASE_URL}{self.path}?checkIn={self.available_from}&checkOut={self.available_from}"

    @pc.field_validator("picture_urls", mode="before")
    @classmethod
    def validate_picture_urls(cls, v: list[dict[str, str]]) -> list[str]:
        """Get picture URLs from Blueground's JSON."""
        return [pic["url"] for pic in v]

    @pc.field_serializer("check_in_date", "check_out_date", when_used="unless-none")
    def serialize_dates(self, v: date) -> str:
        """Serialize dates as ISO string."""
        return v.isoformat()


class BluegroundSearchResult(pc.BaseModel):
    """Search results from Blueground from JSON-in-HTML."""

    items: list[
        Annotated[
            BluegroundHousingPost,
            pc.Field(validation_alias=pc.AliasPath("properties", "allProperties", "main")),
        ]
    ]
    items_per_page: int = pc.Field(
        validation_alias=pc.AliasPath("configuration", "propertiesPerPage")
    )
    items_up_to_page: int = pc.Field(
        validation_alias=pc.AliasPath("properties", "meta", "loadedItems")
    )
    total_items: int = pc.Field(validation_alias=pc.AliasPath("properties", "meta", "totalItems"))

    @pc.computed_field
    @property
    def has_next_page(self) -> bool:
        """Whether there is a next page of results."""
        return self.items_up_to_page < self.total_items


@tenacity.retry(
    wait=tenacity.wait_exponential(multiplier=1, min=4, max=15),
    stop=tenacity.stop_after_attempt(3),
    before_sleep=tenacity.before_sleep_log(logger, logging.WARNING),
)
def _fetch_page_async(url: str, *, page: int | None = None) -> BluegroundSearchResult:
    """Fetch a page of Blueground search results, async."""
    headers = {}
    params = {"page": page} if page else {}

    logger.debug(f"Requesting Blueground URL {url}, with params {params}")
    resp = niquests.get(url=url, params=params, headers=headers, timeout=20)

    resp.raise_for_status()
    if resp.text is None:
        msg = "No response text"
        raise ValueError(msg)

    json_match = re.search(
        r"<script>window\.__INITIAL_STATE__ = (.*?)</script>", resp.text, re.DOTALL
    )
    if json_match is None:
        msg = "Could not find JSON data in HTML response"
        raise ValueError(msg)

    json_data: str = json_match.group(1).strip()
    return BluegroundSearchResult.model_validate_json(json_data)


def is_valid_search_url(url: str) -> bool:
    """Return whether the URL is a valid search URL for Blueground."""
    return bool(
        re.match(r"http(s?)://www\.theblueground\.com/[a-zA-Z-]+/furnished-apartments-.+", url)
    )


async def _gather_async_pages(url: str, pages: list[int]) -> list[BluegroundSearchResult]:
    """Gather search results for multiple pages, async."""
    tasks = [asyncio.create_task(_fetch_page_async(url=url, page=page)) for page in pages]
    return await asyncio.gather(*tasks)


def get_search_results(
    url: str, payload: dict[str, Any] | None, *, max_pages: int | None = None
) -> tuple[int, list[HousingPost]]:
    """Get results for Blueground search URL."""
    del payload  # unused

    first_page_results: BluegroundSearchResult = run_async_in_thread(_fetch_page_async(url))
    posts: list[HousingPost] = list(first_page_results.items)
    logger.info("Found %d results", len(first_page_results.total_items))

    last_page_num = min(
        max_pages, math.ceil(first_page_results.total_items / first_page_results.items_per_page)
    )
    rest_page_nums = range(2, last_page_num + 1)
    rest_page_results = run_async_in_thread(_gather_async_pages(url, rest_page_nums))
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
    first_page_url = search.url.replace("page=[0-9]+&?", "")
    total_results, posts = get_search_results(first_page_url, payload=None, max_pages=max_pages)
    logger.info("Fetched %d posts from %d total results", len(posts), total_results)
    return posts
