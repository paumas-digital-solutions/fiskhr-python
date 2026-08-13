"""Fiskalizacija 1.0 — real-time B2C receipt fiscalization against CIS.

Covers ZKI computation, the F1 message types, and the SOAP client. Targets
tech spec v2.7 and schema/WSDL v1.10 (see ``fiskhr.f1.service`` and the
vendored files under ``schemas/``). Models, messages, and the client land in
Phase 1.
"""

from fiskhr.f1.client import FiskalizacijaClient
from fiskhr.f1.error_codes import CIS_ERROR_MESSAGES
from fiskhr.f1.messages import build_racun_zahtjev, parse_racun_odgovor
from fiskhr.f1.models import (
    BrojRacuna,
    Greska,
    NacinPlacanja,
    Naknada,
    Napojnica,
    OznakaSlijednosti,
    Porez,
    PorezOstalo,
    PorukaOdgovora,
    PromjenaOdgovor,
    ProvjeraOdgovor,
    Racun,
    RacunOdgovor,
)
from fiskhr.f1.service import SCHEMA_VERSION, SERVICE_URLS
from fiskhr.f1.zki import ZKI_DATETIME_FORMAT, izracunaj_zki, zki_payload

__all__ = [
    "CIS_ERROR_MESSAGES",
    "SCHEMA_VERSION",
    "SERVICE_URLS",
    "ZKI_DATETIME_FORMAT",
    "BrojRacuna",
    "FiskalizacijaClient",
    "Greska",
    "NacinPlacanja",
    "Naknada",
    "Napojnica",
    "OznakaSlijednosti",
    "Porez",
    "PorezOstalo",
    "PorukaOdgovora",
    "PromjenaOdgovor",
    "ProvjeraOdgovor",
    "Racun",
    "RacunOdgovor",
    "build_racun_zahtjev",
    "izracunaj_zki",
    "parse_racun_odgovor",
    "zki_payload",
]
