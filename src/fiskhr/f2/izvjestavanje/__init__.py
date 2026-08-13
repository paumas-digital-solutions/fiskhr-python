"""eIzvještavanje — reporting payments and rejections (Phase 3).

After an eRačun is fiscalized, the issuer reports collections
(``EvidentirajNaplatu``) and the recipient may report rejections
(``EvidentirajOdbijanje``); ``OvlastenjaFiskalizacije`` lists the OIBs a
taxpayer may report for. Requests share the eFiskalizacija endpoint and the
XAdES-B signature profile.

``EvidentirajIsporukuZaKojuNijeIzdanERacun`` reports invoices for
deliveries where no eRačun was issued, reusing the same digest model as
eFiskalizacija (`fiskhr.f2.fiskalizacija.EvidencijaERacun`).
"""

from fiskhr.f2.izvjestavanje.client import EIzvjestavanjeClient
from fiskhr.f2.izvjestavanje.messages import (
    build_evidentiraj_isporuku_zahtjev,
    build_evidentiraj_naplatu_zahtjev,
    build_evidentiraj_odbijanje_zahtjev,
    build_ovlastenja_zahtjev,
    parse_izvjestavanje_odgovor,
    parse_ovlastenja_odgovor,
)
from fiskhr.f2.izvjestavanje.models import (
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
    "build_evidentiraj_isporuku_zahtjev",
    "build_evidentiraj_naplatu_zahtjev",
    "build_evidentiraj_odbijanje_zahtjev",
    "build_ovlastenja_zahtjev",
    "parse_izvjestavanje_odgovor",
    "parse_ovlastenja_odgovor",
]
