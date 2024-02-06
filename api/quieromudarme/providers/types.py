"""Common types for provider entities."""

import enum
from datetime import datetime
from decimal import Decimal

import pydantic as pc


# This should match the Provider "enum" in edgedb (dbschema/default.esdl)
class ProviderName(enum.StrEnum):
    """Enum for the different providers of housing posts."""

    ZONAPROP = "ZonaProp"
    MERCADOLIBRE = "MercadoLibre"
    AIRBNB = "Airbnb"


class Currency(enum.StrEnum):
    """Currency codes."""

    USD = "USD"
    ARS = "ARS"
    EUR = "EUR"


class HousingPost(pc.BaseModel):
    """Base housing post from a provider, subclassed by provider-specific models."""

    model_config = pc.ConfigDict(frozen=True)

    provider: ProviderName
    post_id: str
    url: str
    title: str
    price: Decimal
    price_currency: Currency
    # expenses: Decimal | None = None
    # expenses_currency: Literal["USD", "ARS"] | None = None
    picture_urls: list[str]
    # TODO: consider using pydantic_extra_types.PhoneNumber
    whatsapp_phone_number: str | None = None
    antiquity: str | None = None
    modified_at: pc.AwareDatetime | None = None
    publisher_id: str

    @property
    def address(self) -> str:
        """Full address."""
        raise NotImplementedError

    @pc.computed_field  # type: ignore [misc]
    @property
    def main_image_url(self) -> str | None:
        """The first picture URL, if any."""
        return self.picture_urls[0] if len(self.picture_urls) > 0 else None

    @pc.field_validator("whatsapp_phone_number", mode="after")
    @classmethod
    def validate_phone_numbers(cls, v: str | None) -> str | None:
        """Normalize phone numbers."""
        if v is None:
            return v
        return v.replace(" ", "").replace("-", "").lstrip("+0").strip() or None

    @pc.field_serializer("price", when_used="unless-none")
    def serialize_price(self, v: Decimal) -> float:
        """Serialize price as float."""
        return float(v)

    @pc.field_serializer("modified_at", when_used="unless-none")
    def serialize_modified_at(self, v: datetime) -> str:
        """Serialize datetime as ISO string."""
        return v.isoformat()
