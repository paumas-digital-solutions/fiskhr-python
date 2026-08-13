"""eIzvještavanje — reporting payments and rejections (Phase 3).

After an eRačun is fiscalized, the issuer reports collections
(``EvidentirajNaplatu``) and the recipient may report rejections
(``EvidentirajOdbijanje``); ``OvlastenjaFiskalizacije`` lists the OIBs a
taxpayer may report for. Requests share the eFiskalizacija endpoint and the
XAdES-B signature profile.

``EvidentirajIsporukuZaKojuNijeIzdanERacun`` (deliveries without an eRačun)
is defined by the vendored schema but not implemented yet.
"""

from fiskalhr.f2.izvjestavanje.client import EIzvjestavanjeClient
from fiskalhr.f2.izvjestavanje.messages import (
    build_evidentiraj_naplatu_zahtjev,
    build_evidentiraj_odbijanje_zahtjev,
    build_ovlastenja_zahtjev,
    parse_izvjestavanje_odgovor,
    parse_ovlastenja_odgovor,
)
from fiskalhr.f2.izvjestavanje.models import (
    NacinPlacanjaNaplate,
    Naplata,
    Odbijanje,
    RazlogOdbijanja,
)

__all__ = [
    "EIzvjestavanjeClient",
    "NacinPlacanjaNaplate",
    "Naplata",
    "Odbijanje",
    "RazlogOdbijanja",
    "build_evidentiraj_naplatu_zahtjev",
    "build_evidentiraj_odbijanje_zahtjev",
    "build_ovlastenja_zahtjev",
    "parse_izvjestavanje_odgovor",
    "parse_ovlastenja_odgovor",
]
