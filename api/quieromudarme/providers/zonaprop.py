"""ZonaProp connector."""

import logging
import os
import random
import re
import tempfile
from decimal import Decimal
from typing import Any, Final, cast

import py_mini_racer
import pydantic as pc
import tenacity
from bs4 import BeautifulSoup
from bs4 import Tag as Bs4Tag
from seleniumbase import SB

from quieromudarme import db
from quieromudarme.errors import QMError
from quieromudarme.logging import setup_logger

from .base import Currency, HousingPost, ProviderName
from .common import gen_user_agent

DEFAULT_MAX_PAGES: Final = 20
RESULTS_PER_PAGE: Final = 20
max_results_considered: Final = DEFAULT_MAX_PAGES * RESULTS_PER_PAGE

logger = setup_logger()


name = ProviderName.ZONAPROP


class ZonaPropError(QMError):
    """Errors on ZonaProp's side or parsing their data."""


class ZonaPropHousingPost(HousingPost):
    """A housing post from ZonaProp."""

    provider: ProviderName = ProviderName.ZONAPROP
    post_id: str = pc.Field(validation_alias="postingId")
    url: str
    # TODO: what to do with status? only show those with status == 'ONLINE' or similar?
    status: str | None = None  # known values: "ONLINE", null
    # i think this is the announcer's housing ID
    post_code: str = pc.Field(validation_alias="postingCode")
    title: str
    generated_title: str = pc.Field(validation_alias="generatedTitle", repr=False)
    description: str = pc.Field(repr=False)
    description_normalized: str = pc.Field(validation_alias="descriptionNormalized", repr=False)
    price: Decimal = pc.Field(
        validation_alias=pc.AliasPath("priceOperationTypes", -1, "prices", -1, "amount")
    )
    price_currency: Currency = pc.Field(
        validation_alias=pc.AliasPath("priceOperationTypes", -1, "prices", -1, "currency")
    )
    expenses: Decimal | None = pc.Field(
        default=None, validation_alias=pc.AliasPath("expenses", "amount")
    )
    expenses_currency: Currency | None = pc.Field(
        default=None, validation_alias=pc.AliasPath("expenses", "currency")
    )
    location_address: str | None = pc.Field(
        default=None, validation_alias=pc.AliasPath("postingLocation", "address", "name")
    )
    # has parents that could also be interesting, e.g. Almagro (parent: CABA (parent: Arg))
    location_area: str | None = pc.Field(
        default=None, validation_alias=pc.AliasPath("postingLocation", "location", "name")
    )
    picture_urls: list[str] = pc.Field(
        default_factory=list, validation_alias=pc.AliasPath("visiblePictures", "pictures")
    )
    whatsapp_phone_number: str | None = pc.Field(
        default=None, validation_alias=pc.AliasChoices("whatsapp", "whatsApp")
    )
    antiquity: str | None = None
    modified_at: pc.AwareDatetime = pc.Field(validation_alias="modified_date")
    publisher_id: str = pc.Field(validation_alias=pc.AliasPath("publisher", "publisherId"))

    @pc.computed_field  # type: ignore [misc]
    @property
    def address(self) -> str:
        """Full address from location elements."""
        return ", ".join(filter(None, [self.location_address, self.location_area]))

    @pc.field_validator("url")
    @classmethod
    def fix_url(cls, v: str) -> str:
        """Keep full URL instead of just path."""
        return f"https://www.zonaprop.com.ar/{v.lstrip('/')}"

    @pc.field_validator("picture_urls", mode="before")
    @classmethod
    def fix_picture_urls(cls, v: list[dict[str, Any]]) -> list[str]:
        """Extract the URL for a mid-size resolution for each picture."""
        return [pic["url730x532"] for pic in v]

    @pc.field_validator("price_currency", "expenses_currency", mode="before")
    @classmethod
    def fix_currencies(cls, v: str) -> str:
        """Normalize currencies to USD/ARS."""
        return v.replace("U$S", "USD").replace("$", "ARS").replace("Pesos", "ARS")

    @pc.field_serializer("expenses", when_used="unless-none")
    def serialize_expenses(self, v: Decimal) -> float:
        """Serialize expenses as float."""
        return float(v)


class ZonaPropSearchResult(pc.BaseModel):
    """Model for ZonaProp search results."""

    posts: list[ZonaPropHousingPost] = pc.Field(
        validation_alias=pc.AliasPath("listStore", "listPostings")
    )
    total_results: int = pc.Field(validation_alias=pc.AliasPath("listStore", "paging", "total"))
    total_pages: int = pc.Field(validation_alias=pc.AliasPath("listStore", "paging", "totalPages"))
    page_urls: list[str] = pc.Field(
        validation_alias=pc.AliasPath("listStore", "paging", "pagesUrl")
    )
    # TODO: should we use this? if the other providers have it too
    search_title: str | None = pc.Field(
        default=None, validation_alias=pc.AliasPath("listStore", "title")
    )

    @pc.field_validator("page_urls", mode="before")
    @classmethod
    def fix_page_urls(cls, v: dict[str, str | None]) -> list[str]:
        """Extract URLs, sort by page number, and prepend the base URL."""
        v = {k: p for k, p in v.items() if k.isdigit()}
        paths = [p for _, p in sorted(v.items(), key=lambda x: int(x[0])) if p is not None]
        return [f"https://www.zonaprop.com.ar/{p.lstrip('/')}" for p in paths]


def _process_page_html(page_html: str) -> ZonaPropSearchResult:
    """Process the HTML of a ZonaProp search results page.

    This is done simply by looking for the preloaded data that ZonaProp includes,
    converting from JS object to JSON to Python dict, and extracting all the
    relevant information into a ZonaPropSearchResult.
    """
    # Find the script tag with the preloaded data
    soup = BeautifulSoup(page_html, "html.parser")
    script_tag = cast(Bs4Tag | None, soup.find("script", id="preloadedData"))
    if script_tag is None or script_tag.string is None:
        logger.error(f"Start of HTML: {page_html[:1000]}")
        msg = "Could not find preloaded data in ZonaProp search results page"
        raise ZonaPropError(msg)

    # Stringify the JS object and parse it as JSON
    js_content = (
        script_tag.string.strip()
        .splitlines()[0]
        .replace("window.__PRELOADED_STATE__ = ", "", 1)
        .strip()
        .strip(";")
    )
    js_content = f"JSON.stringify({js_content})"

    # To fix a weird bug, write the string to a file, and read it back immediately
    with tempfile.NamedTemporaryFile(mode="w+t", suffix=".js") as f:
        f.write(js_content)
        f.seek(0)
        js_content = f.read()

    # Parse the JS object into JSON
    json_preloaded_data = py_mini_racer.MiniRacer().eval(js_content)  # TODO: wildly unsafe?
    # Parse the JSON into a ZonaPropSearchResult
    return ZonaPropSearchResult.model_validate_json(json_preloaded_data)


def is_valid_search_url(url: str) -> bool:
    """Check if the string is a valid ZonaProp search URL."""
    return bool(re.match(r"https?://(www\.)?zonaprop\.com\.ar/[a-zA-Z0-9-]+\.html", url))


@tenacity.retry(
    wait=tenacity.wait_exponential(multiplier=1, min=5, max=15),
    stop=tenacity.stop_after_attempt(3),
    before_sleep=tenacity.before_sleep_log(logger, logging.WARNING),
)
def get_search_results(
    url: str, payload: dict[str, Any] | None, *, max_pages: int | None = DEFAULT_MAX_PAGES
) -> tuple[int, list[HousingPost]]:
    """Get housing posts from ZonaProp for a certain URL.

    Fetch the first page, then fetch the rest, and return a list of HousingPost objects.
    If max_pages is provided, only fetch up to that many pages.
    """
    del payload
    # TODO: remove payload from all the signatures, no?
    logger.debug(f"Fetching ZonaProp search results for url {url}")
    logger.debug(f"User ID: {os.getuid()}")

    with SB(
        uc=True,
        headless2=True,
        disable_js=True,
        disable_csp=True,
        agent=gen_user_agent(),
        chromium_arg="--no-sandbox,--disable-gpu",
    ) as sb:
        logger.debug("Driver connected, first attempt")
        sb.driver.uc_open_with_reconnect(url, 4)
        if not sb.is_text_visible("Temporal"):
            logger.debug("Second attempt, ideally already validated")
            sb.driver.uc_open_with_reconnect(url, 5)
        if not sb.is_text_visible("Temporal"):
            msg = "Failed to get ZonaProp search page"
            raise ZonaPropError(msg)
        logger.info("Everything a-ok!")

        first_page_html = sb.driver.get_page_source()
        first_page_result = _process_page_html(first_page_html)

        posts: list[HousingPost] = list(first_page_result.posts)
        logger.info(
            f"Found {first_page_result.total_pages} pages"
            f" for {first_page_result.total_results} total results"
        )

        # Fetch the rest of the pages
        max_page = min(max_pages or 1000, first_page_result.total_pages)
        for page_url in first_page_result.page_urls[1:max_page]:
            logger.debug(f"Fetching page {page_url}")
            sb.driver.sleep(5 * random.random())  # noqa: S311
            sb.driver.default_get(page_url)
            page_html = sb.driver.get_page_source()
            page_result = _process_page_html(page_html)
            posts.extend(page_result.posts)
        logger.info(f"Fetched {len(posts)} posts (from {max_page} pages) for search {url}")

    return first_page_result.total_results, posts


def fetch_latest_results(
    search: db.GetHousingSearchesResult, max_pages: int | None = DEFAULT_MAX_PAGES
) -> list[HousingPost]:
    """Fetch the latest results for a ZonaProp search."""
    # TODO: remove previous sortings, page numbers, etc.
    # sort by most recent first
    url = re.sub(r"\.html$", "orden-publicado-descendente.html", search.url)

    total_results, posts = get_search_results(url, None, max_pages=max_pages)
    logger.info(
        f"Found {total_results} results for search {search.id} by {search.user.telegram_id}"
    )
    return posts


def debug() -> None:
    """Run some debug code."""
    url = "https://www.zonaprop.com.ar/departamentos-ph-alquiler-villa-urquiza-palermo-belgrano-villa-ortuzar-villa-crespo-almagro-colegiales-coghlan-parque-chas-parque-centenario-mas-50-m2-cubiertos-publicado-hace-menos-de-1-semana-menos-500000-pesos-orden-precio-ascendente.html"
    total_results, posts = get_search_results(url, None)
    logger.debug(total_results)
    for post in posts:
        logger.debug(post.title)


# TODO: both of these are sync, wtf
async def debug_async() -> None:
    """Run some async debug code."""
    url = "https://www.zonaprop.com.ar/departamentos-ph-alquiler-villa-urquiza-palermo-belgrano-villa-ortuzar-villa-crespo-almagro-colegiales-coghlan-parque-chas-parque-centenario-mas-50-m2-cubiertos-publicado-hace-menos-de-1-semana-menos-500000-pesos-orden-precio-ascendente.html"
    total_results, posts = get_search_results(url, None)
    logger.debug(total_results)
    for post in posts:
        logger.debug(post.title)


def main() -> None:
    """Run the main code."""
    import asyncio

    asyncio.run(debug_async())
