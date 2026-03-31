from __future__ import annotations

import pytest


@pytest.fixture
def sample_listing_html() -> str:
    """Minimal HTML mimicking a Zawya listing page."""
    return """
    <html><body>
    <table>
      <tbody>
        <tr>
          <td><a href="/company/1234567890/acme-trading-llc">Acme Trading LLC</a></td>
          <td>Retailers</td>
          <td>United Arab Emirates</td>
          <td>Private</td>
        </tr>
        <tr>
          <td><a href="/company/9876543210/xyz-group-pjsc">XYZ Group PJSC</a></td>
          <td>Retailers</td>
          <td>United Arab Emirates</td>
          <td>Public</td>
        </tr>
      </tbody>
    </table>
    </body></html>
    """
