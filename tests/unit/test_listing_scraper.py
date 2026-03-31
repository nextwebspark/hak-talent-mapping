from __future__ import annotations

from hak_talent_mapping.services.listing_scraper import _parse_listing_page


def test_parse_listing_page_returns_companies(sample_listing_html: str) -> None:
    companies = _parse_listing_page(sample_listing_html, "https://www.zawya.com")
    assert len(companies) == 2


def test_parse_listing_page_extracts_fields(sample_listing_html: str) -> None:
    companies = _parse_listing_page(sample_listing_html, "https://www.zawya.com")
    acme = companies[0]
    assert acme.company_id == "1234567890"
    assert acme.name == "Acme Trading LLC"
    assert acme.slug == "acme-trading-llc"
    assert acme.sector == "Retailers"
    assert acme.country == "United Arab Emirates"
    assert acme.company_type == "Private"
    assert acme.profile_url == "https://www.zawya.com/company/1234567890/acme-trading-llc"


def test_parse_listing_page_empty_table() -> None:
    html = "<html><body><table><tbody></tbody></table></body></html>"
    companies = _parse_listing_page(html, "https://www.zawya.com")
    assert companies == []


def test_parse_listing_page_skips_malformed_rows() -> None:
    html = """
    <html><body><table><tbody>
      <tr><td>No link here</td><td>X</td><td>Y</td><td>Z</td></tr>
    </tbody></table></body></html>
    """
    companies = _parse_listing_page(html, "https://www.zawya.com")
    assert companies == []
