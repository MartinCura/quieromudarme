# TODO: delete this file
"""ZonaProp connector.

TODO: Missing support for:
- "Incluir expensas al precio final" <- ask user?
- Dirección: "drc-<direccion>" <- difficult to distinguish from other keywords

Query params not covered yet:

{
    "q": null,
    "direccion": null,
    "general": "",
    "amenidades": "",
    "outside": "",
    "areaPrivativa": "",
    "areaComun": "",
    "multipleRets": "",
    "subtipoDePropiedad": null,
    "expensasminimo": null,
    "expensasmaximo": null,
    "etapaDeDesarrollo": "",
    "auctions": null,
    "polygonApplied": null,
    "idInmobiliaria": null,
    "excludePostingContacted": "",
    "banks": "",
    "places": "",
    "condominio": "",
    "coordenates": null
}
"""

import concurrent.futures
import json
import logging
import math
import random
import re
import time
from decimal import Decimal
from typing import Any, Final, Literal, TypeAlias, TypedDict, cast

import niquests
import py_mini_racer
import pydantic as pc
import tenacity
from bs4 import BeautifulSoup
from bs4 import Tag as Bs4Tag

from quieromudarme import db
from quieromudarme.errors import QMError
from quieromudarme.logging import setup_logger
from quieromudarme.providers.common import gen_user_agent
from quieromudarme.utils import slugify

from .types import Currency, HousingPost, ProviderName

name = ProviderName.ZONAPROP


class ZonaPropError(QMError):
    """Errors on ZonaProp's side or parsing their data."""


PROPERTY_TYPES = {
    "casas": 1,
    "departamentos": 2,
    "ph": 2001,
    "locales-comerciales": 5,
    "oficinas-comerciales": 4,
    "bodegas-galpones": 8,
    "cocheras": 32,
    "depositos": 45,
    "terrenos": 26,
    "edificios": 7,
    "quintas-vacacionales": 11,
    "campos": 14,
    "fondos-de-comercio": 99,
    "hoteles": 38,
    "consultorios": 10,
    "cama-nautica": 2005,
    "bovedas-nichos-y-parcelas": 2000,
}
OPERATION_TYPES: dict[str | None, str | int | None] = {
    None: None,
    "alquiler-temporal": 4,  # Important to have this before "alquiler"
    "alquiler": 2,
    "venta": 1,
    "emprendimientos": "desarrollosURL",
}
CURRENCIES = {"pesos": 1, "dolar": 2}
MEASURE_UNITS = {"m2": 1, "ha": 2}
DISPOSITIONS = {
    "contrafrente": "2000201",
    "frente": "2000199",
    "interior": "2000202",
    "lateral": "2000200",
}
# GET https://www.zonaprop.com.ar/rplis-api/features/suggestFeatures?name=
CHARACTERISTICS_REVERSE = [
    {"id": "1000003", "labelSuggest": "Uso comercial"},
    {"id": "1000004", "labelSuggest": "Apto profesional"},
    {"id": "1000125", "labelSuggest": "Gas natural"},
    {"id": "1000028", "labelSuggest": "Ofrece financiación"},
    {"id": "1000127", "labelSuggest": "Luz"},
    {"id": "1000105", "labelSuggest": "Dependencia servicio"},
    {"id": "1000087", "labelSuggest": "Sala de juegos"},
    {"id": "1000088", "labelSuggest": "Sauna"},
    {"id": "1000121", "labelSuggest": "Agua corriente"},
    {"id": "1000001", "labelSuggest": "Apto crédito"},
    {"id": "1000100", "labelSuggest": "Balcón"},
    {"id": "1000002", "labelSuggest": "Permite mascotas"},
    {"id": "1000068", "labelSuggest": "Gimnasio"},
    {"id": "1000046", "labelSuggest": "Calefacción"},
    {"id": "2000199", "labelSuggest": "Vista frente"},
    {"id": "2000174", "labelSuggest": "Acepta recibo de sueldo como garantía"},
    {"id": "2000137", "labelSuggest": "Cocina equipada"},
    {"id": "1000106", "labelSuggest": "Dormitorio en suite"},
    {"id": "1000109", "labelSuggest": "Jardín"},
    {"id": "2000194", "labelSuggest": "Luminoso"},
    {"id": "2000171", "labelSuggest": "Acceso para personas con movilidad reducida"},
    {"id": "2000192", "labelSuggest": "Cancha de deportes"},
    {"id": "1000040", "labelSuggest": "Amoblado"},
    {"id": "1000085", "labelSuggest": "Quincho"},
    {"id": "1000114", "labelSuggest": "Patio"},
    {"id": "1000038", "labelSuggest": "Aire acondicionado"},
    {"id": "2000127", "labelSuggest": "Acepta seguro de caución"},
    {"id": "2000149", "labelSuggest": "Caja Fuerte"},
    {"id": "1000116", "labelSuggest": "Terraza"},
    {"id": "1000110", "labelSuggest": "Lavadero"},
    {"id": "1000132", "labelSuggest": "Living comedores"},  # changed from "Living comedor"
    {"id": "1000078", "labelSuggest": "Parrilla"},
    {"id": "1000133", "labelSuggest": "Cocinas"},  # changed from "Cocina"
    {"id": "1000079", "labelSuggest": "Pileta"},
    {"id": "2000143", "labelSuggest": "Servicio de limpieza"},
    {"id": "2000142", "labelSuggest": "Encargado / Vigilancia"},
    {"id": "2000141", "labelSuggest": "Internet / Wifi"},
    {"id": "2000148", "labelSuggest": "Ascensor"},
    {"id": "1000117", "labelSuggest": "Toilette"},
    {"id": "2000202", "labelSuggest": "Vista interior"},
    {"id": "1000118", "labelSuggest": "Vestidor"},
    {"id": "2000140", "labelSuggest": "Ropa de cama"},
    {"id": "1000074", "labelSuggest": "Laundry"},
    {"id": "1000090", "labelSuggest": "Solarium"},
    {"id": "1000092", "labelSuggest": "SUM"},
]
CHARACTERISTICS = {slugify(v["labelSuggest"]): v["id"] for v in CHARACTERISTICS_REVERSE}

AnnouncerType: TypeAlias = Literal["ALL", "COMPANY", "PARTICULAR"]
LocationType: TypeAlias = Literal["province", "city", "valueZone", "zone", "subZone"]

logger = setup_logger()


# TODO: this should just be a pydantic model
class QueryPayload(TypedDict):
    """Payload for ZonaProp JSON queries."""

    sort: Literal["more_recent", "high_price", "most_lowered_price"] | None
    pagina: int | None
    tipoDePropiedad: str
    tipoDeOperacion: str | None
    ambientesminimo: str
    ambientesmaximo: str
    habitacionesminimo: str
    habitacionesmaximo: str
    moneda: int | str | None
    preciomin: int | str | None
    preciomax: int | str | None
    metroscuadradomin: int | str | None
    metroscuadradomax: int | str | None
    superficieCubierta: int
    idunidaddemedida: int
    banos: str | None
    garages: str | None
    publicacion: str | None
    tipoAnunciante: AnnouncerType
    disposicion: str | None
    antiguedad: str | None
    province: str | None
    city: str | None
    valueZone: str | None
    zone: str | None
    subZone: str | None
    grupoTipoDeMultimedia: str | None
    # takes the place of: services, caracteristicasprop, comodidades, roomType, ¿amenidades?
    searchbykeyword: str | None


class ZonaPropHousingPost(HousingPost):
    """A housing post from ZonaProp."""

    provider: ProviderName = ProviderName.ZONAPROP
    post_id: str = pc.Field(validation_alias=pc.AliasChoices("postingId", "posting_id"))
    url: str
    # TODO: what to do with status? only show those with status == 'ONLINE' or similar?
    status: str | None = None  # known values: "ONLINE", null
    # i think this is the announcer's housing ID
    post_code: str = pc.Field(validation_alias=pc.AliasChoices("postingCode", "posting_code"))
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
    expenses_currency: Literal["USD", "ARS"] | None = pc.Field(
        default=None, validation_alias=pc.AliasPath("expenses", "currency")
    )
    location_address: str | None = pc.Field(
        default=None, validation_alias=pc.AliasPath("postingLocation", "address", "name")
    )
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
    def validate_url(cls, v: str) -> str:
        """Keep full URL instead of just path."""
        return f"https://www.zonaprop.com.ar/{v.lstrip('/')}"

    @pc.field_validator("picture_urls", mode="before")
    @classmethod
    def validate_picture_urls(cls, v: list[dict[str, Any]]) -> list[str]:
        """Extract the URL for a mid-size resolution for each picture."""
        return [pic["url730x532"] for pic in v]

    @pc.field_validator("price_currency", "expenses_currency", mode="before")
    @classmethod
    def validate_currencies(cls, v: str) -> str:
        """Normalize currencies to USD/ARS."""
        return v.replace("U$S", "USD").replace("$", "ARS").replace("Pesos", "ARS")

    @pc.field_serializer("expenses", when_used="unless-none")
    def serialize_expenses(self, v: Decimal) -> float:
        """Serialize expenses as float."""
        return float(v)


def _match_option_range(
    q: str, noun_regex: str, default: int | None = None
) -> tuple[int | None, int | None]:
    """Find the range (min, max) for an option in query path.

    The options are in the form "desde-<min>-hasta-<max>-<noun>" and variants;
    for example "desde-2-hasta-4-ambientes". Include all variants for the noun,
    e.g. singular and plural, such as "habitacion(es)?".
    """
    noun_regex = rf"\b({noun_regex})\b"
    if match := re.search(rf"(desde-)?(\d+)-(hasta-)?(\d+)-{noun_regex}", q):
        return (int(match.group(2)), int(match.group(4)))
    if match := re.search(rf"mas-(de-)?(\d+)-{noun_regex}", q):
        return (int(match.group(2)), default)
    if match := re.search(rf"(hasta|menos)-(\d+)-{noun_regex}", q):
        return (default, int(match.group(2)))
    if match := re.search(rf"(\d+)-{noun_regex}", q):
        return (int(match.group(1)), int(match.group(1)))
    if match := re.search(rf"sin-{noun_regex}", q):
        return (-1, None)  # special case used in garages, explicit lack of them
    return (default, default)


def parse_search_path(url: str) -> QueryPayload:  # noqa: PLR0915, PLR0912, C901
    """Get the JSON payload for API, from a web search URL."""
    # TODO: if continuing with this approach, should really do something about
    #       the path parts not matched by anything known
    path = url.split("zonaprop.com.ar/")[-1].split(".html")[0]
    logger.debug("Query path: %s", path)

    property_types = []
    for property_type_slug, property_type_id in PROPERTY_TYPES.items():
        if re.search(rf"\b{property_type_slug}\b", path):
            logger.info("found property_type: %s", property_type_slug)
            property_types.append(property_type_id)

    operation_type_pattern = "|".join(rf"({ot})" for ot in OPERATION_TYPES)
    operation_type_match = re.search(operation_type_pattern, path)
    operation_type = None if operation_type_match is None else operation_type_match.group(0)
    logger.info("found operation_type: %s", operation_type)

    spaces = _match_option_range(path, r"ambientes?", default=0)
    logger.info("found spaces: %s", spaces)

    rooms = _match_option_range(path, r"habitacion(es)?", default=0)
    logger.info("found rooms: %s", rooms)

    currency = None
    for currency_slug, currency_id in CURRENCIES.items():
        if re.search(rf"\b{currency_slug}\b", path):
            currency = currency_id
    prices = _match_option_range(path, "|".join(f"({c})" for c in CURRENCIES))
    logger.info("found currency and prices: %s", (currency, prices))

    measure_unit = "m2"
    m2_are_covered = 1
    square_meters = _match_option_range(path, "|".join(MEASURE_UNITS))
    if square_meters != (None, None):
        measure_unit = "m2" if "m2" in path else "ha"  # easy path
        m2_are_covered = (  # 1 -> covered m2/ha, 2 -> total m2/ha
            1 if re.search(rf"({'|'.join(MEASURE_UNITS)})-cubiertos", path) else 2
        )
        logger.info("found square_meters: %s", (square_meters, measure_unit, m2_are_covered))

    # for these the format is always "mas-de-<min>-banos", if present
    min_bathrooms = _match_option_range(path, r"banos?")[0]
    garages = _match_option_range(path, r"garages?")[0]

    announcer_type: AnnouncerType
    if "inmobiliaria" in path:
        announcer_type = "COMPANY"
    elif "dueno-directo" in path:
        announcer_type = "PARTICULAR"
    else:
        announcer_type = "ALL"

    publicacion: int | None = None
    if "hace-menos-de-1-dia" in path:
        publicacion = 0  # today
    elif "hace-menos-de-2-dias" in path:
        publicacion = 1  # yesterday
    elif "hace-menos-de-1-semana" in path:
        publicacion = 7
    elif "hace-menos-de-15-dias" in path:
        publicacion = 15
    elif "hace-menos-de-1-mes" in path:
        publicacion = 30
    elif "hace-menos-de-45-dias" in path:
        publicacion = 45

    building_age: int | None = None
    if "en-construccion" in path:
        building_age = -1
    elif "a-estrenar" in path:
        building_age = 0
    elif "hasta-5-anos" in path:
        building_age = 5
    elif "hasta-10-anos" in path:
        building_age = 10
    elif "hasta-20-anos" in path:
        building_age = 20
    elif "hasta-50-anos" in path:
        building_age = 50
    elif "mas-de-50-anos" in path:
        building_age = 51

    disposition_pattern = f"con-disposicion-({'|'.join(rf'({d})' for d in DISPOSITIONS)})"
    disposition_match = re.search(disposition_pattern, path)
    disposition = None if disposition_match is None else disposition_match.group(1)
    logger.info("found disposition: %s", disposition)

    characteristics = []
    for char_slug, char_id in CHARACTERISTICS.items():
        if re.search(rf"\b{char_slug}\b", path):
            characteristics.append(char_id)

    multimedia: list[int] = []
    if "recorrido-360" in path:
        multimedia.append(4)
    if "videos" in path:
        multimedia.append(1)
    if "planos" in path:
        multimedia.append(10)

    location_ids = _get_location_ids(url)

    return QueryPayload(
        sort=None,  # ignoring it
        pagina=1,
        tipoDePropiedad=",".join(str(pt) for pt in property_types),
        tipoDeOperacion=(None if operation_type is None else str(OPERATION_TYPES[operation_type])),
        ambientesminimo=str(spaces[0]),
        ambientesmaximo=str(spaces[1]),
        habitacionesminimo=str(rooms[0]),
        habitacionesmaximo=str(rooms[1]),
        moneda=currency,
        preciomin=prices[0],
        preciomax=prices[1],
        idunidaddemedida=MEASURE_UNITS[measure_unit],
        metroscuadradomin=square_meters[0],
        metroscuadradomax=square_meters[1],
        superficieCubierta=m2_are_covered,
        banos=str(min_bathrooms) if min_bathrooms is not None else None,
        garages=str(garages) if garages is not None else None,
        tipoAnunciante=announcer_type,
        publicacion=str(publicacion) if publicacion is not None else None,
        disposicion=DISPOSITIONS[disposition] if disposition is not None else None,
        antiguedad=str(building_age) if building_age is not None else None,
        grupoTipoDeMultimedia=",".join(str(m) for m in multimedia),
        province=",".join(str(l_id) for l_id in location_ids["province"]),
        city=",".join(str(l_id) for l_id in location_ids["city"]),
        valueZone=",".join(str(l_id) for l_id in location_ids["valueZone"]),
        zone=",".join(str(l_id) for l_id in location_ids["zone"]),
        subZone=",".join(str(l_id) for l_id in location_ids["subZone"]),
        searchbykeyword=",".join(str(c_id) for c_id in characteristics),
    )


@tenacity.retry(
    wait=tenacity.wait_exponential(multiplier=1, min=4, max=15),
    stop=tenacity.stop_after_attempt(4),
    before_sleep=tenacity.before_sleep_log(logger, logging.WARNING),
)
def _get_location_ids(url: str) -> dict[LocationType, list[int]]:
    """Get the IDs per type for each location filtered by in this ZonaProp search.

    This is done simply by hitting the real URL, looking for the preloaded data
    that ZonaProp includes, converting from JS object to JSON to Python dict,
    and extracting the location IDs from the helpful JSON and its section on filters.

    TODO: should just use this JSON to get most filters and be done with it.
    """
    time.sleep(random.random() * 2.1)  # noqa: S311

    with niquests.Session() as session:
        headers = {"User-Agent": gen_user_agent()}
        resp = session.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
    if resp.text is None:
        msg = f"No response text found: {resp.status_code=}"
        raise ZonaPropError(msg)

    # Find the script tag with the preloaded data
    soup = BeautifulSoup(resp.text, "html.parser")
    script_tag = cast(Bs4Tag | None, soup.find("script", id="preloadedData"))
    if script_tag is None or script_tag.string is None:
        raise ZonaPropError

    # Stringify the JS object and parse it as JSON
    ctx = py_mini_racer.MiniRacer()
    js_content = (
        script_tag.string.strip()
        .splitlines()[0]
        .replace("window.__PRELOADED_STATE__ = ", "", 1)
        .strip()
        .strip(";")
    )
    js_content = f"JSON.stringify({js_content})"
    json_preloaded_data = ctx.eval(js_content)  # TODO: wildly unsafe?
    preloaded_data = json.loads(json_preloaded_data)

    # Extract the necessary data  # TODO: clean up
    # applied_filters = preloaded_data["listStore"]["appliedFilters"]
    # location_filters = next((f["options"] for f in applied_filters if f["type"] == "location"),[])
    # location_ids = {"province": [], "city": [], "valueZone": [], "zone": [], "subZone": []}
    # for loc in location_filters:
    #     location_ids[loc["type"]].append(loc["min"])
    location_ids: dict[LocationType, list[int]] = preloaded_data["filtersStore"]["location"]["min"]
    logger.info("Location IDs: %s", location_ids)

    return location_ids


fallback_cf_cookies = {
    "_cfuvid": "Y19VLW.RZRY5nwL_p1TTgbi4x2XS.VTXAVmVghwTKPE-1711506522918-0.0.1.1-604800000"
    # "cf_clearance": "7Xr9esDZap.g9XhfmVA82T55vV3GuRlBUMWIx3lV5OQ-1711463482-1.0.1.1-Ca_Dqg_Kcuh.MIdLqbXlZ6mjuAd7Yj276OUkiwi_PKEqJpHmTT0S9lJ9OmDYheqaDTxY.aqctSPcMpxo_TYB3Q",  # noqa: E501
}


@tenacity.retry(
    wait=tenacity.wait_exponential(multiplier=1, min=10, max=20),
    stop=tenacity.stop_after_attempt(1),
    before_sleep=tenacity.before_sleep_log(logger, logging.WARNING),
    retry_error_callback=lambda _retry_state: fallback_cf_cookies,
)
def _get_cf_cookies() -> dict[str, str]:
    """Generate valid CloudFlare cookies for ZonaProp's "difficult" endpoints."""
    headers = {"User-Agent": gen_user_agent()}
    with niquests.Session() as session:
        session.quic_cache_layer.add_domain("www.zonaprop.com.ar")
        resp = session.get("https://www.zonaprop.com.ar", headers=headers, timeout=15)
        resp.raise_for_status()
        return session.cookies.get_dict(domain=".zonaprop.com.ar")  # type: ignore [no-any-return]


@tenacity.retry(
    wait=tenacity.wait_exponential(multiplier=1, min=10, max=20),
    stop=tenacity.stop_after_attempt(3),
    before_sleep=tenacity.before_sleep_log(logger, logging.WARNING),
)
def _fetch_page_of_results(payload: QueryPayload, page: int) -> dict[str, Any]:
    """Request a page of results from ZonaProp's API."""
    api_url = "https://www.zonaprop.com.ar/rplis-api/postings"
    payload = payload.copy()
    payload["pagina"] = page
    time.sleep(random.random() * 2.3)  # noqa: S311

    with niquests.Session() as session:
        cookies = _get_cf_cookies()
        session.quic_cache_layer.add_domain("www.zonaprop.com.ar")
        headers = {"User-Agent": gen_user_agent()}
        resp = session.post(api_url, json=payload, headers=headers, cookies=cookies, timeout=15)
        resp.raise_for_status()

    if resp.text is None:
        msg = f"No response text found: {resp.status_code=}"
        raise ZonaPropError(msg)

    return cast(dict[str, Any], resp.json())


def is_valid_search_url(url: str) -> bool:
    """Check if the string is a valid ZonaProp search URL."""
    return bool(re.match(r"https?://(www\.)?zonaprop\.com\.ar/[a-zA-Z0-9-]+\.html", url))


DEFAULT_MAX_PAGES: Final = 20
RESULTS_PER_PAGE: Final = 20
max_results_considered: Final = DEFAULT_MAX_PAGES * RESULTS_PER_PAGE


def get_search_results(
    url: str, payload: dict[str, Any] | None, *, max_pages: int | None = DEFAULT_MAX_PAGES
) -> tuple[int, list[HousingPost]]:
    """Get housing posts from ZonaProp's API for a certain URL/query.

    Fetch the first page, then fetch the rest in parallel, and return the
    results as a list of HousingPost objects. If `max_pages` is passed,
    only fetch that many pages, otherwise fetch all available pages.
    """
    # TODO: clean up URL? e.g. remove query params; make sure it doesn't specify a page or offset
    logger.debug("Fetching search results for %s", url)
    if payload is None:
        logger.debug("No payload provided, parsing from URL")
        query_payload = parse_search_path(url)
    else:
        query_payload = QueryPayload(**payload)  # type: ignore [typeddict-item]
    first_page_payload = _fetch_page_of_results(query_payload, 1)

    first_page_results = first_page_payload.get("listPostings") or []
    if len(first_page_results) == 0 or first_page_payload.get("totalPosting") is None:
        return 0, []

    total_results = int(first_page_payload["totalPosting"].replace(".", ""))
    logger.info("Total results should be: %s", total_results)

    num_pages = math.ceil(total_results / 20)
    pages = range(2, num_pages if max_pages is None else min(num_pages, max_pages) + 1)

    posts_per_page: dict[int, list[dict[str, Any]]] = {1: first_page_results}
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_page = {
            executor.submit(_fetch_page_of_results, query_payload, page): page for page in pages
        }
        for future in concurrent.futures.as_completed(future_to_page):
            page = future_to_page[future]
            try:
                resp_payload = future.result()
                posts_per_page[page] = resp_payload["listPostings"]
            except Exception:
                logger.exception("Fetching page %s generated an exception", page)
                # TODO: no re-raise?

    posts_in_pages = [v for _, v in sorted(posts_per_page.items(), key=lambda kv: kv[0])]
    posts: list[dict[str, Any]] = [post for page_posts in posts_in_pages for post in page_posts]
    logger.info("Fetched %s results in %s pages", len(posts), num_pages)

    housing_posts: list[HousingPost] = [ZonaPropHousingPost(**p) for p in posts]

    return total_results, housing_posts


def fetch_latest_results(
    search: db.GetHousingSearchesResult, max_pages: int | None = DEFAULT_MAX_PAGES
) -> list[HousingPost]:
    """Get the latest results from ZonaProp's API."""
    if not search.query_payload:
        # TODO: or should i just parse it from the URL and use it / save it?
        msg = f"Search {search.id} has no API query payload. Cannot continue."
        raise ZonaPropError({"message": msg})

    query_payload = json.loads(search.query_payload)
    query_payload["sort"] = "more_recent"

    total_results, results = get_search_results(search.url, query_payload, max_pages=max_pages)
    if total_results == 0:
        return []

    return results


# TODO: See tmp/zonaprop_leads_for_sellers.sh
## Example of a PublisherInfoResponse
# [
#   {
#     "resultLeadOutput": {
#       "code": 200,
#       "userId": "51156271",
#       "contactId": 276947781,
#       "description": "Somos ...",
#       "message": null,
#       "leadEventType": "clasificados",
#       "postingId": null,
#       "postingUrl": null,
#       "showFeedbackBanner": false,
#       "multilead": false
#     },
#     "publisherOutput": {
#       "publisherId": "30481070",
#       "username": "Figlioli Bienes Raíces",
#       "email": null,
#       "phone": "1155046477",
#       "cellPhone": null,
#       "whatsApp": null,
#       "show": true
#     }
#   }
# ]


# class PublisherInfoResponsePublisherOuptput(pc.BaseModel):
#     """Publisher info response from ZonaProp's API."""

#     model_config = pc.ConfigDict(frozen=True)

#     publisher_id: str = pc.Field(alias="publisherId")
#     username: str
#     email: str | None = None
#     phone: str | None = None
#     cell_phone: str | None = pc.Field(default=None, alias="cellPhone")
#     whatsapp: str | None = pc.Field(default=None, alias="whatsApp")
#     show: bool


# # TODO: use fetch_publisher_info() to fill missing phone numbers with the publisher's data
# #       probably would be best to create a separate table for them though
# #       also do this only per a certain flag in the call, to not slow down some callers


# @tenacity.retry(
#     wait=tenacity.wait_exponential(multiplier=1, min=4, max=15),
#     stop=tenacity.stop_after_attempt(3),
#     before_sleep=tenacity.before_sleep_log(logger, logging.WARNING),
# )
# def fetch_publisher_info(publisher_id: str) -> PublisherInfoResponsePublisherOuptput:
#     """Fetch the publisher's info from ZonaProp's API."""
#     api_url = "https://www.zonaprop.com.ar/rp-api/leads/view"
#     payload = {"publisherId": publisher_id, "email": "fake@email.com"}
#     with niquests.Session() as session:
#         cookies = _get_cf_cookies()
#         session.quic_cache_layer.add_domain("www.zonaprop.com.ar")  # type: ignore [attr-defined]
#         headers = {"User-Agent": gen_user_agent()}
#         resp = session.post(api_url, json=payload, headers=headers, cookies=cookies, timeout=15)
#         resp.raise_for_status()
#
#     info = cast(list[dict[str, Any]], resp.json())
#     return PublisherInfoResponsePublisherOuptput(**info[0]["publisherOutput"])
