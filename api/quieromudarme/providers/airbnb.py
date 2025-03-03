"""Airbnb connector."""

import asyncio
import logging
import re
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Final, Literal, cast

import niquests
import pydantic as pc
import tenacity
from bs4 import BeautifulSoup
from bs4 import Tag as Bs4Tag

from quieromudarme import db
from quieromudarme.logging import setup_logger
from quieromudarme.utils import run_async_in_thread

from .base import Currency, HousingPost, ProviderName
from .common import gen_user_agent

logger = setup_logger()


class AirbnbHousingPost(HousingPost):
    """A housing post adapted from an Airbnb "room" or "stay".

    Adapted from Airbnb's JSON-in-HTML.
    """

    model_config = pc.ConfigDict(coerce_numbers_to_str=True, frozen=False)

    post_type: Literal["StaySearchResult"] = pc.Field(validation_alias="__typename")

    provider: ProviderName = ProviderName.AIRBNB
    post_id: str = pc.Field(validation_alias=pc.AliasPath("listing", "id"))
    url: str = ""  # URL is not present, it's generated
    title: str = pc.Field(validation_alias=pc.AliasPath("listing", "name"))  # There's also "title"
    description: str = pc.Field(
        default="",
        validation_alias=pc.AliasChoices(
            pc.AliasPath("listing", "structuredContent", "secondaryLine", 1, "body"),
            pc.AliasPath("listing", "structuredContent", "secondaryLine", 0, "body"),
        ),
    )
    price: Decimal = pc.Field(
        validation_alias=pc.AliasChoices(
            pc.AliasPath(
                "pricingQuote", "structuredStayDisplayPrice", "primaryLine", "discountedPrice"
            ),
            pc.AliasPath("pricingQuote", "structuredStayDisplayPrice", "primaryLine", "price"),
            pc.AliasPath(
                "pricingQuote", "structuredStayDisplayPrice", "primaryLine", "originalPrice"
            ),
        )
    )
    price_currency: Literal[Currency.EUR] = Currency.EUR  # TODO: hardcoded
    picture_urls: list[str] = pc.Field(
        validation_alias=pc.AliasPath("listing", "contextualPictures")
    )
    publisher_id: str = ""  # TODO: doesn't seem to be included in current query
    check_in_date: date = pc.Field(
        validation_alias=pc.AliasPath("listingParamOverrides", "checkin")
    )
    check_out_date: date = pc.Field(
        validation_alias=pc.AliasPath("listingParamOverrides", "checkout")
    )

    @pc.model_validator(mode="after")
    def validate_url(self) -> "AirbnbHousingPost":
        """Generate post's URL for corresponding search.

        TODO: [WARNING] this is a search-specific URL, not generic.
        """
        self.url = (
            f"https://www.airbnb.com/rooms/{self.post_id}?adults=2&currency={self.price_currency}"
            f"&check_in={self.check_in_date.isoformat()}&check_out={self.check_out_date.isoformat()}"
        )
        return self

    @pc.field_validator("price", mode="before")
    @classmethod
    def validate_price(cls, v: str) -> Decimal:
        """Extract price amount from label string with currency."""
        # TODO: simplification for a couple of known cases, not general
        v = v.replace("€ ", "").replace("$", "").replace("USD", "").replace(",", "").strip()
        return Decimal(v)

    @pc.field_validator("picture_urls", mode="before")
    @classmethod
    def validate_picture_urls(cls, v: list[dict[str, str]]) -> list[str]:
        """Get picture URLs from Airbnb's JSON."""
        return [pic["picture"] for pic in v]

    @pc.field_serializer("check_in_date", "check_out_date", when_used="unless-none")
    def serialize_dates(self, v: date) -> str:
        """Serialize dates as ISO string."""
        return v.isoformat()


class DiscardPost(pc.BaseModel):
    """Discarded posts, e.g. results with different filters."""

    post_type: Literal["HeaderInsert", "ExploreSplitStaysListingItem"] = pc.Field(
        validation_alias="__typename"
    )


class AirbnbSearchResult(pc.BaseModel):
    """Simplified search result from Airbnb's embedded JSON-in-HTML."""

    search_results: list[
        Annotated[
            AirbnbHousingPost | DiscardPost,
            pc.Field(
                discriminator="post_type",
                validation_alias=pc.AliasPath(
                    "niobeMinimalClientData",
                    0,
                    1,
                    "data",
                    "presentation",
                    "staysSearch",
                    "results",
                    "searchResults",
                ),
            ),
        ]
    ]
    page_cursors: list[str] = pc.Field(
        validation_alias=pc.AliasPath(
            "niobeMinimalClientData",
            0,
            1,
            "data",
            "presentation",
            "staysSearch",
            "results",
            "paginationInfo",
            "pageCursors",
        )
    )

    @property
    def posts(self) -> list[AirbnbHousingPost]:
        """Return only the Airbnb posts."""
        return [post for post in self.search_results if post.post_type == "StaySearchResult"]


@tenacity.retry(
    wait=tenacity.wait_exponential(multiplier=1, min=4, max=15),
    stop=tenacity.stop_after_attempt(3),
    before_sleep=tenacity.before_sleep_log(logger, logging.WARNING),
)
async def _fetch_page_async(url: str, *, cursor: str | None = None) -> AirbnbSearchResult:
    """Fetch a page of Airbnb search results, async."""
    # TODO: make sure the URL has its `cursor` query param cleaned, this will not override it
    headers = {
        "User-Agent": gen_user_agent(),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.5",
        "Alt-Used": "www.airbnb.com",
    }
    params = {"cursor": cursor} if cursor else {}

    logger.debug(f"Requesting Airbnb URL {url}, with params {params}")
    resp = niquests.get(url=url, params=params, headers=headers, timeout=20)

    resp.raise_for_status()
    if resp.text is None:
        msg = "No response text"
        raise ValueError(msg)

    # We get a state JSON object in a script tag within the HTML
    soup = BeautifulSoup(resp.text, "html.parser")
    script_tag = cast(Bs4Tag | None, soup.find("script", id=re.compile(r"data-deferred-state")))
    if script_tag is None or script_tag.string is None:
        msg = "No script tag with state JSON"
        raise ValueError(msg)

    return AirbnbSearchResult.model_validate_json(script_tag.string.strip())


async def _gather_async_pages(url: str, cursors: list[str]) -> list[AirbnbSearchResult]:
    """Gather search results for multiple page cursors, async."""
    tasks = [asyncio.create_task(_fetch_page_async(url=url, cursor=cursor)) for cursor in cursors]
    return await asyncio.gather(*tasks)


name: Final = ProviderName.AIRBNB

DEFAULT_MAX_PAGES: Final = 20
RESULTS_PER_PAGE: Final = 18
max_results_considered: Final = DEFAULT_MAX_PAGES * RESULTS_PER_PAGE


def is_valid_search_url(url: str) -> bool:
    """Return whether the URL is a valid search URL for Airbnb."""
    # TODO: support for other countries; support for air.tl
    return bool(re.match(r"http(s?)://(www\.)?airbnb\.com/s/[^/?]+/homes\?", url))


def get_search_results(
    url: str, payload: dict[str, Any] | None, *, max_pages: int | None = DEFAULT_MAX_PAGES
) -> tuple[int, list[HousingPost]]:
    """Get results for Airbnb search URL."""
    del payload, max_pages  # unused

    first_page_result = run_async_in_thread(_fetch_page_async(url))
    posts: list[HousingPost] = list(first_page_result.posts)
    logger.info("Found %d pages of results", len(first_page_result.page_cursors))

    rest_page_cursors = first_page_result.page_cursors[1:]
    rest_page_results = run_async_in_thread(_gather_async_pages(url, rest_page_cursors))
    for page_result in rest_page_results:
        posts.extend(page_result.posts)

    logger.info(
        "Found %d results (from %s pages) for search %s",
        len(posts),
        len(first_page_result.page_cursors),
        url,
    )
    # TODO: should be total results, not just the amount we fetched
    return len(posts), posts


def fetch_latest_results(
    search: db.GetHousingSearchesResult, *, max_pages: int | None = None
) -> list[HousingPost]:
    """Fetch latest results for a search."""
    # TODO: remove cursor; anything else?
    total_results, posts = get_search_results(search.url, payload=None, max_pages=max_pages)
    logger.info(f"Found {total_results} results for search {search.id}")
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
