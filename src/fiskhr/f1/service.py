"""F1 service endpoints and vendored schema metadata.

Endpoint URLs are taken from the tech spec v2.7, section 6.1 ("Url adrese za
spajanje na Sustav za fiskalizaciju Porezne uprave") and match the vendored
WSDLs. Note: the official PROD WSDL bundle ships with the *test* URL in its
``soap:address`` — the production URL below is the one from the spec text.

The ``provjera`` (receipt check) operation exists only in the test
environment; it is absent from the production WSDL.
"""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from fiskhr.core.environment import Environment

__all__ = ["SCHEMA_VERSION", "SERVICE_URLS", "schema_dir"]

SCHEMA_VERSION = "1.10"
"""Version of the vendored FiskalizacijaSchema.xsd / WSDL bundle (2025-11-24)."""

SERVICE_URLS: dict[Environment, str] = {
    Environment.DEMO: "https://cistest.apis-it.hr:8449/FiskalizacijaServiceTest",
    Environment.PRODUCTION: "https://cis.porezna-uprava.hr:8449/FiskalizacijaService",
}


def schema_dir(version: str = SCHEMA_VERSION) -> Path:
    """Path to the vendored schema directory for ``version``."""
    return Path(str(files("fiskhr.f1") / "schemas" / f"v{version}"))
