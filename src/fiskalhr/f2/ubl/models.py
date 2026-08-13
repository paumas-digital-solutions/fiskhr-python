"""eRačun data models (Pydantic v2), mapped to EN 16931 / HR CIUS 2025.

Field names follow the plan's convention: Croatian domain terms in
snake_case, mapped to their business terms (BT-x) in docstrings. Amounts
are ``Decimal`` end to end; serialisation formats them per the schema.

The models enforce what the HR rules demand at construction time (OIB
checksums, KPD presence, category/rate consistency, exemption reasons), so
most invalid invoices fail fast in Python — `fiskalhr.f2.validation` then
provides the authoritative check against the official Schematron.
"""

from __future__ import annotations

import enum
from datetime import date, time
from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from fiskalhr.core.types import validate_oib

__all__ = [
    "CUSTOMIZATION_ID",
    "PROFIL_P1",
    "Adresa",
    "ERacun",
    "KategorijaPdv",
    "Operater",
    "Stavka",
    "Stranka",
]

CUSTOMIZATION_ID = (
    "urn:cen.eu:en16931:2017#compliant#"
    "urn:mfin.gov.hr:cius-2025:1.0#conformant#urn:mfin.gov.hr:ext-2025:1.0"
)
"""``CustomizationID`` (BT-24) required by HR-BR-5."""

PROFIL_P1 = "P1"
"""Default ``ProfileID`` (BT-23); HR-BR-34 allows P1-P12 or ``P99:<oznaka>``."""

OIB_ENDPOINT_SCHEME = "9934"
"""``EndpointID/@schemeID`` for Croatian OIB electronic addresses."""

Oib = Annotated[str, AfterValidator(validate_oib)]


class KategorijaPdv(enum.StrEnum):
    """VAT category code (BT-151 / UNCL 5305 subset used by HR CIUS).

    HR rules tie the rate to the category: ``S`` requires a rate above zero
    (HR-BR-S-10); ``Z``, ``E``, ``AE`` and ``O`` require zero (…-10 rules).
    """

    STANDARDNA = "S"
    NULTA_STOPA = "Z"
    OSLOBODJENO = "E"
    PRIJENOS_POREZNE_OBVEZE = "AE"
    NE_PODLIJEZE = "O"


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Adresa(_Model):
    """Postal address (BG-5 / BG-8)."""

    ulica: str = Field(min_length=1)
    grad: str = Field(min_length=1)
    postanski_broj: str = Field(min_length=1)
    drzava: str = Field(default="HR", pattern=r"^[A-Z]{2}$")


class Stranka(_Model):
    """A party — seller (BG-4) or buyer (BG-7).

    ``elektronicka_adresa`` (BT-34/BT-49, mandatory per HR-BR-7/10)
    defaults to the party's OIB under scheme 9934 when omitted.
    """

    oib: Oib
    naziv: str = Field(min_length=1)
    adresa: Adresa
    elektronicka_adresa: str | None = None
    pravni_oblik: str | None = None
    """``CompanyLegalForm`` (BT-33) — court registration, capital, etc."""

    @property
    def endpoint(self) -> str:
        return self.elektronicka_adresa if self.elektronicka_adresa is not None else self.oib


class Operater(_Model):
    """The operator issuing the invoice (HR-BT-4 oznaka, HR-BT-5 OIB).

    Mandatory per HR-BR-37 and HR-BR-9; serialised as ``SellerContact``.
    """

    oib: Oib
    oznaka: str = Field(min_length=1)


class Stavka(_Model):
    """One invoice line (BG-25).

    ``kpd`` is the Klasifikacija proizvoda po djelatnostima code, mandatory
    for every item per HR-BR-25 (``ItemClassificationCode listID="CG"``).
    """

    naziv: str = Field(min_length=1, max_length=1023)
    kolicina: Decimal
    cijena: Decimal
    """Net unit price (BT-146)."""
    kpd: str = Field(min_length=1)
    pdv_stopa: Decimal = Decimal("0")
    kategorija: KategorijaPdv = KategorijaPdv.STANDARDNA
    razlog_oslobodjenja: str | None = None
    """Exemption reason (BT-120) — required for E / AE / O categories."""
    jedinica: str = "H87"
    """UN/ECE Rec 20 unit code (H87 = piece)."""
    opis: str | None = Field(default=None, max_length=4095)

    @model_validator(mode="after")
    def _consistent(self) -> Stavka:
        if self.kategorija is KategorijaPdv.STANDARDNA:
            if self.pdv_stopa <= 0:
                raise ValueError("kategorija S requires pdv_stopa > 0 (HR-BR-S-10)")
        elif self.pdv_stopa != 0:
            raise ValueError(f"kategorija {self.kategorija.value} requires pdv_stopa == 0")
        exempt_like = (
            KategorijaPdv.OSLOBODJENO,
            KategorijaPdv.PRIJENOS_POREZNE_OBVEZE,
            KategorijaPdv.NE_PODLIJEZE,
        )
        if self.kategorija in exempt_like and not self.razlog_oslobodjenja:
            raise ValueError(
                f"kategorija {self.kategorija.value} requires razlog_oslobodjenja "
                "(HR-BR-16/HR-BR-36)"
            )
        return self

    @property
    def neto(self) -> Decimal:
        """Line net amount (BT-131), rounded to 2 decimals."""
        return (self.kolicina * self.cijena).quantize(Decimal("0.01"))


class ERacun(_Model):
    """An eRačun (UBL Invoice) ready for serialisation.

    Totals are computed, never supplied: per-category tax subtotals group
    lines by (kategorija, stopa); the payable amount is net + PDV.
    """

    broj: str = Field(min_length=1, pattern=r"^\S+$")  # HR-BR-1: no whitespace
    datum_izdavanja: date
    vrijeme_izdavanja: time
    """HR-BT-2, mandatory per HR-BR-2."""
    izdavatelj: Stranka
    primatelj: Stranka
    operater: Operater
    stavke: tuple[Stavka, ...] = Field(min_length=1)
    datum_dospijeca: date | None = None
    datum_isporuke: date | None = None
    """Actual delivery date (BT-72) — the tax-relevant date."""
    valuta: str = Field(default="EUR", pattern=r"^[A-Z]{3}$")
    nacin_placanja: str = "30"
    """UNCL 4461 payment means code (30 = credit transfer)."""
    iban: str | None = None
    poziv_na_broj: str | None = None
    """Remittance information (BT-83), e.g. ``HR00 123456``."""
    opis_placanja: str | None = None
    napomena: str | None = None
    profil: str = PROFIL_P1
    vrsta: str = "380"
    """UNCL 1001 invoice type (380 commercial invoice)."""

    @model_validator(mode="after")
    def _due_date_when_payable(self) -> ERacun:
        if self.ukupno_s_pdv > 0 and self.datum_dospijeca is None:
            raise ValueError(
                "datum_dospijeca is required when the payable amount is positive (HR-BR-4)"
            )
        return self

    @property
    def grupe_pdv(self) -> dict[tuple[KategorijaPdv, Decimal], Decimal]:
        """Taxable base per (category, rate) group — one ``TaxSubtotal`` each."""
        groups: dict[tuple[KategorijaPdv, Decimal], Decimal] = {}
        for stavka in self.stavke:
            key = (stavka.kategorija, stavka.pdv_stopa)
            groups[key] = groups.get(key, Decimal("0")) + stavka.neto
        return groups

    @property
    def ukupno_neto(self) -> Decimal:
        """Sum of line net amounts (BT-106 / BT-109)."""
        return sum((s.neto for s in self.stavke), Decimal("0.00"))

    @property
    def ukupno_pdv(self) -> Decimal:
        """Total VAT (BT-110): sum of per-group amounts, each rounded."""
        total = Decimal("0.00")
        for (_, stopa), osnovica in self.grupe_pdv.items():
            total += (osnovica * stopa / 100).quantize(Decimal("0.01"))
        return total

    @property
    def ukupno_s_pdv(self) -> Decimal:
        """Amount payable (BT-112 / BT-115)."""
        return self.ukupno_neto + self.ukupno_pdv
