"""Some simple tests for the ZonaProp provider."""

import os

import pytest

from quieromudarme.providers import zonaprop_old

is_ci = os.getenv("CI", "").lower() == "true"


def test_parse_general() -> None:
    """General test for parsing a ZonaProp URL."""
    url = "https://www.zonaprop.com.ar/casas-departamentos-alquiler-saavedra-palermo-nunez-con-disposicion-lateral-mas-de-2-banos-mas-de-2-habitaciones-mas-90-m2-publicado-hace-menos-de-1-dia-menos-1100-dolar.html"
    # JSON
    expected = {
        "pagina": 1,
        "ambientesmaximo": "0",
        "ambientesminimo": "0",
        # "amenidades": "",
        # "antiguedad": None,
        # "areaComun": "",
        # "areaPrivativa": "",
        # "auctions": None,
        # "banks": "",
        "banos": "2",
        # "caracteristicasprop": None,
        # "province": None,
        "city": "1003698,1003694,1003697",
        # "valueZone": None,
        # "zone": None,
        # "subZone": None,
        # "comodidades": "",
        # "condominio": "",
        # "coordenates": None,
        # "direccion": None,
        "disposicion": "2000200",
        # "etapaDeDesarrollo": "",
        # "excludePostingContacted": "",
        # "expensasmaximo": None,
        # "expensasminimo": None,
        "garages": None,
        # "general": "",
        # "grupoTipoDeMultimedia": "",
        "habitacionesmaximo": "0",
        "habitacionesminimo": "2",
        # "idInmobiliaria": None,
        "idunidaddemedida": 1,
        "metroscuadradomin": 90,
        "metroscuadradomax": None,
        "moneda": 2,
        # "multipleRets": "",
        # "outside": "",
        # "places": "",
        # "polygonApplied": None,
        "preciomax": 1100,
        "preciomin": None,
        "publicacion": "0",
        # "q": None,
        # "roomType": "",
        # "searchbykeyword": "",
        # "services": "",
        # "sort": "relevance",
        # "subtipoDePropiedad": None,
        "superficieCubierta": 2,
        "tipoAnunciante": "ALL",
        "tipoDeOperacion": "2",
        "tipoDePropiedad": "1,2",
    }

    parsed = zonaprop_old.parse_search_path(url)

    assert parsed == expected


@pytest.mark.skipif(is_ci, reason="requires network access")
def test_get_city_ids() -> None:
    """Test getting city IDs from a ZonaProp URL."""
    url = "https://www.zonaprop.com.ar/casas-departamentos-alquiler-saavedra-palermo-nunez-con-disposicion-lateral-mas-de-2-banos-mas-de-2-habitaciones-mas-90-m2-publicado-hace-menos-de-1-dia-menos-1100-dolar.html"
    expected = [1003698, 1003694, 1003697]

    result = zonaprop_old._get_location_ids(url)["city"]

    assert result == expected


def test_get_search_results() -> None:
    """Test getting search results for a ZonaProp query."""
    url = "https://www.zonaprop.com.ar/casas-departamentos-alquiler-saavedra-palermo-nunez-con-disposicion-lateral-mas-de-2-banos-mas-de-2-habitaciones-mas-90-m2-publicado-hace-menos-de-1-dia-menos-1100-dolar.html"
    payload = zonaprop_old.QueryPayload(
        {
            "sort": "more_recent",
            "pagina": 1,
            "ambientesmaximo": "0",
            "ambientesminimo": "0",
            "banos": "1",
            "province": "",
            "city": "1003698",
            "valueZone": "",
            "zone": "",
            "subZone": "",
            "disposicion": None,
            "garages": None,
            "habitacionesmaximo": "0",
            "habitacionesminimo": "0",
            "idunidaddemedida": 1,
            "metroscuadradomin": 40,
            "metroscuadradomax": None,
            "moneda": 2,
            "preciomax": 2000,
            "preciomin": None,
            "publicacion": None,
            "superficieCubierta": 2,
            "tipoAnunciante": "ALL",
            "tipoDeOperacion": "2",
            "tipoDePropiedad": "1,2",
            "grupoTipoDeMultimedia": None,
            "antiguedad": None,
            "searchbykeyword": None,
        }
    )

    results = zonaprop_old.get_search_results(url, dict(**payload))

    assert len(results) > 0
