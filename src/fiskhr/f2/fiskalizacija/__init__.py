"""eFiskalizacija — reporting eRačuni to the Tax Administration (Phase 3).

The ``EvidentirajERacun`` message carries a structured digest of each
eRačun (not the UBL document itself), signed with a XAdES-B enveloped
signature. `EvidencijaERacun.from_eracuna` derives the digest from the same
`fiskhr.f2.ubl.ERacun` model that produced the UBL document.
"""

from fiskhr.f2.fiskalizacija.client import EFiskalizacijaClient
from fiskhr.f2.fiskalizacija.error_codes import EFISKALIZACIJA_ERROR_MESSAGES
from fiskhr.f2.fiskalizacija.messages import (
    build_evidentiraj_eracun_zahtjev,
    parse_evidentiraj_eracun_odgovor,
)
from fiskhr.f2.fiskalizacija.models import (
    DokumentUkupanIznos,
    EvidencijaERacun,
    EvidencijaGreska,
    EvidencijaOdgovor,
    Izdavatelj,
    PrethodniERacun,
    PrijenosSredstava,
    Primatelj,
    RaspodjelaPdv,
    StavkaEvidencije,
    VrstaERacuna,
)

__all__ = [
    "EFISKALIZACIJA_ERROR_MESSAGES",
    "DokumentUkupanIznos",
    "EFiskalizacijaClient",
    "EvidencijaERacun",
    "EvidencijaGreska",
    "EvidencijaOdgovor",
    "Izdavatelj",
    "PrethodniERacun",
    "PrijenosSredstava",
    "Primatelj",
    "RaspodjelaPdv",
    "StavkaEvidencije",
    "VrstaERacuna",
    "build_evidentiraj_eracun_zahtjev",
    "parse_evidentiraj_eracun_odgovor",
]
