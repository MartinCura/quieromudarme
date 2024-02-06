"""Tests for the ZonaProp provider."""

from pathlib import Path

from quieromudarme.providers import zonaprop


def test_process_page() -> None:
    """Test for processing a ZonaProp search results page."""
    html_str = Path(
        "tests/data/zonaprop_departamentos-alquiler-ciudad-de-santa-fe-sf-orden-publicado-descendente.html"
    ).read_text()

    result = zonaprop._process_page_html(html_str)

    assert result.total_results == 119
    assert result.total_pages == 6
