"""F1 data models (Pydantic v2), mirroring FiskalizacijaSchema.xsd v1.10.

Model and field names keep the schema's Croatian names in snake_case
(``ozn_slijed`` ↔ ``OznSlijed``) — every integrator reads the Croatian spec
alongside this code, so nothing is translated. Serialisation to the exact
XML element names lives in `fiskalhr.f1.messages`.

Amounts are ``Decimal`` end to end; the schema's ``IznosType`` demands
exactly two decimals with ``.`` as separator, which `messages` formats via
`fiskalhr.f1.zki.format_iznos`. Never use floats for money.
"""

from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from fiskalhr.core.types import validate_oib

__all__ = [
    "BrojRacuna",
    "Greska",
    "NacinPlacanja",
    "Naknada",
    "OznakaSlijednosti",
    "Porez",
    "PorezOstalo",
    "Racun",
    "RacunOdgovor",
]

Oib = Annotated[str, AfterValidator(validate_oib)]
"""An OIB, checksum-validated (ISO 7064 MOD 11,10)."""


class NacinPlacanja(enum.StrEnum):
    """``NacinPlacanjaType`` — payment method."""

    GOTOVINA = "G"
    KARTICA = "K"
    TRANSAKCIJSKI_RACUN = "T"
    OSTALO = "O"


class OznakaSlijednosti(enum.StrEnum):
    """``OznakaSlijednostiType`` — receipt-number sequence scope.

    ``N`` — per payment device (naplatni uređaj);
    ``P`` — per business premises (poslovni prostor).
    """

    NAPLATNI_UREDJAJ = "N"
    POSLOVNI_PROSTOR = "P"


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Porez(_Model):
    """``PorezType`` — one tax line (PDV or porez na potrošnju)."""

    stopa: Decimal
    osnovica: Decimal
    iznos: Decimal


class PorezOstalo(Porez):
    """``PorezOstaloType`` — other named tax (e.g. porez na luksuz)."""

    naziv: str = Field(min_length=1, max_length=100)


class Naknada(_Model):
    """``NaknadaType`` — fee such as povratna naknada (``NazivN``/``IznosN``)."""

    naziv: str = Field(min_length=1, max_length=100)
    iznos: Decimal


class BrojRacuna(_Model):
    """``BrojRacunaType`` — the receipt number triple printed on the receipt."""

    br_ozn_rac: str = Field(min_length=1, max_length=20, pattern=r"^\d+$")
    ozn_pos_pr: str = Field(min_length=1, max_length=20, pattern=r"^[0-9a-zA-Z]+$")
    ozn_nap_ur: str = Field(min_length=1, max_length=20, pattern=r"^\d+$")


class Racun(_Model):
    """``RacunType`` — the receipt data submitted for fiscalization.

    Field order mirrors the schema's ``<sequence>``; `fiskalhr.f1.messages`
    relies on it when serialising.
    """

    oib: Oib
    u_sust_pdv: bool
    dat_vrijeme: datetime
    ozn_slijed: OznakaSlijednosti
    br_rac: BrojRacuna
    pdv: tuple[Porez, ...] | None = None
    pnp: tuple[Porez, ...] | None = None
    ostali_por: tuple[PorezOstalo, ...] | None = None
    iznos_oslob_pdv: Decimal | None = None
    iznos_marza: Decimal | None = None
    iznos_ne_podl_opor: Decimal | None = None
    naknade: tuple[Naknada, ...] | None = None
    iznos_ukupno: Decimal
    nacin_plac: NacinPlacanja
    oib_oper: Oib
    nak_dost: bool = False
    paragon_br_rac: str | None = Field(default=None, min_length=1, max_length=100)
    spec_namj: str | None = Field(default=None, min_length=1, max_length=1000)
    oib_primatelja_racuna: Oib | None = None
    """Receiver's OIB — mandatory for B2B cash/card receipts since 2026-01-01."""


class Greska(_Model):
    """``GreskaType`` — one server-reported error (code + Croatian message)."""

    sifra: str
    poruka: str


class RacunOdgovor(_Model):
    """Parsed ``RacunOdgovor`` — either a JIR or a list of errors."""

    id_poruke: str | None
    datum_vrijeme: datetime
    jir: str | None = None
    greske: tuple[Greska, ...] = ()

    @property
    def ok(self) -> bool:
        """Whether fiscalization succeeded (a JIR was assigned)."""
        return self.jir is not None and not self.greske
