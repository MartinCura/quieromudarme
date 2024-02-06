"""Providers module."""

from . import airbnb, meli, zonaprop
from .protocol import ProviderConnector
from .types import HousingPost, ProviderName


def get_provider_by_name(name: ProviderName) -> ProviderConnector:
    """Return the provider connector by name."""
    if name == ProviderName.ZONAPROP:
        return zonaprop
    if name == ProviderName.MERCADOLIBRE:
        return meli
    if name == ProviderName.AIRBNB:
        return airbnb
    msg = f"Unknown provider name: {name}"
    raise ValueError(msg)


def get_provider_by_url(url: str) -> ProviderConnector | None:
    """Return the provider name if the URL is valid for any known provider, else None."""
    if zonaprop.is_valid_search_url(url):
        return zonaprop
    if meli.is_valid_search_url(url):
        return meli
    if airbnb.is_valid_search_url(url):
        return airbnb
    return None


def clean_search_url(url: str) -> str:
    """Clean up the URL to make it more uniform.

    If new providers are added that depend on these parts of the URL, revisit this.

    Example: should not be used for Airbnb.
    """
    return url.split("?")[0].split("#")[0]


__all__ = [
    "airbnb",
    "meli",
    "zonaprop",
    "HousingPost",
    "ProviderName",
    "ProviderConnector",
    "clean_search_url",
    "get_provider_by_name",
    "get_provider_by_url",
]
