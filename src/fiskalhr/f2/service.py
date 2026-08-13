"""F2 service endpoints and vendored schema paths.

Endpoint URLs are from the F2 tech spec ("Tehnička specifikacija -
Fiskalizacija eRačuna i eIzvještavanje"), ch. 10.1 ("URL adrese za spajanje
na Sustav za fiskalizaciju Porezne uprave"). One endpoint pair serves the
whole Sustav za fiskalizaciju — the eFiskalizacija operations
(``EvidentirajERacun``) and the eIzvještavanje operations
(``EvidentirajNaplatu``, ``EvidentirajOdbijanje``, …) alike. The vendored
WSDLs ship with an empty ``soap:address``; these URLs are the ones from the
spec text.

Note the port and paths differ from F1: F2 runs on ``:8509``, and the test
path is ``FiskalizacijaServiceEprod`` (not ``FiskalizacijaServiceTest`` as
in F1).
"""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from fiskalhr.core.environment import Environment

__all__ = [
    "SERVICE_URLS",
    "efiskalizacija_schema_path",
    "eizvjestavanje_schema_path",
]

SERVICE_URLS: dict[Environment, str] = {
    Environment.DEMO: "https://cistest.apis-it.hr:8509/FiskalizacijaServiceEprod",
    Environment.PRODUCTION: "https://cis.porezna-uprava.hr:8509/FiskalizacijaService",
}


def efiskalizacija_schema_path() -> Path:
    """Path to the vendored eFiskalizacija XSD (changelog 2026-01-17)."""
    return Path(
        str(files("fiskalhr.f2") / "schemas" / "efiskalizacija" / "eFiskalizacijaSchema.xsd")
    )


def eizvjestavanje_schema_path() -> Path:
    """Path to the vendored eIzvještavanje XSD."""
    return Path(
        str(files("fiskalhr.f2") / "schemas" / "eizvjestavanje" / "eIzvjestavanjeSchema.xsd")
    )
