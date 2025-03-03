"""Module for provider protocol."""

from typing import Any, Protocol

from quieromudarme import db

from .base import HousingPost, ProviderName


class ProviderConnector(Protocol):
    """A protocol for provider connectors."""

    name: ProviderName

    max_results_considered: int

    def is_valid_search_url(self, url: str) -> bool:
        """Return whether the URL is a valid search URL for this provider."""
        ...

    def get_search_results(
        self, url: str, payload: dict[str, Any] | None, *, max_pages: int | None = None
    ) -> tuple[int, list[HousingPost]]:
        """Get the number of results and list of housing posts a search.

        Cut off at `max_pages` if provided.
        """
        ...

    # TODO: max_pages is a bad approach because different providers have different page sizes
    def fetch_latest_results(
        self, search: db.GetHousingSearchesResult, *, max_pages: int | None = None
    ) -> list[HousingPost]:
        """Fetch latest results for a search."""
        ...
