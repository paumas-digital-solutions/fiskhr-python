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
    "KPD_EXEMPT_VRSTE",
    "ODOBRENJE",
    "PROFIL_P1",
    "Adresa",
    "ERacun",
    "KategorijaPdv",
    "Operater",
    "Popust",
    "PrethodniRacun",
    "Stavka",
    "Stranka",
    "Trosak",
    "hr_oznaka",
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

ODOBRENJE = "381"
"""UNCL 1001 code for a credit note."""

KPD_EXEMPT_VRSTE = frozenset(
    {"81", "83", "261", "262", "296", "308", "381", "386", "396", "420", "458", "532"}
)
"""Document types HR-BR-25 exempts from the per-item KPD requirement
(credit notes, advance invoices, corrections, …)."""

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


_HR_OZNAKE = {
    KategorijaPdv.NULTA_STOPA: "HR:Z",
    KategorijaPdv.OSLOBODJENO: "HR:E",
    KategorijaPdv.PRIJENOS_POREZNE_OBVEZE: "HR:AE",
    KategorijaPdv.NE_PODLIJEZE: "HR:O",
}


def hr_oznaka(kategorija: KategorijaPdv, stopa: Decimal) -> str | None:
    """HR VAT category mark (HR-BT-12 / HR-BT-22), constrained to the HR:*
    codelist; mandatory for E/O lines (HR-BR-16). For standard-rated lines
    it encodes the rate (HR:PDV25/13/5), so an off-list rate yields no mark.
    """
    if kategorija is KategorijaPdv.STANDARDNA:
        oznaka = f"HR:PDV{format(stopa.normalize(), 'f')}"
        return oznaka if oznaka in ("HR:PDV25", "HR:PDV13", "HR:PDV5") else None
    return _HR_OZNAKE[kategorija]


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


class PrethodniRacun(_Model):
    """Reference to a preceding invoice (BG-3), e.g. the invoice a credit
    note corrects. Both fields are mandatory per HR-BR-6."""

    broj: str = Field(min_length=1)
    """Preceding invoice number (BT-25)."""
    datum_izdavanja: date
    """Preceding invoice issue date (BT-26)."""


def _provjeri_kategoriju(kategorija: KategorijaPdv, stopa: Decimal, razlog: str | None) -> None:
    """The category/rate/reason consistency the HR rules demand, shared by
    lines (BG-25) and document-level allowances/charges (BG-20/21)."""
    if kategorija is KategorijaPdv.STANDARDNA:
        if stopa <= 0:
            raise ValueError("kategorija S requires pdv_stopa > 0 (HR-BR-S-10)")
    elif stopa != 0:
        raise ValueError(f"kategorija {kategorija.value} requires pdv_stopa == 0")
    exempt_like = (
        KategorijaPdv.OSLOBODJENO,
        KategorijaPdv.PRIJENOS_POREZNE_OBVEZE,
        KategorijaPdv.NE_PODLIJEZE,
    )
    if kategorija in exempt_like and not razlog:
        raise ValueError(
            f"kategorija {kategorija.value} requires razlog_oslobodjenja "
            "(HR-BR-16/HR-BR-36, HR-BR-13 for charges)"
        )


class _PopustTrosak(_Model):
    iznos: Decimal
    """Amount without PDV (BT-92 / BT-99)."""
    razlog: str = Field(min_length=1, max_length=1024)
    """Reason text (BT-97 / BT-104) — mandatory (EN BR-33/BR-38); doubles
    as the exemption reason for E/AE/O categories (HR-BR-13)."""
    kategorija: KategorijaPdv = KategorijaPdv.STANDARDNA
    pdv_stopa: Decimal = Decimal("0")
    razlog_kod: str | None = None
    """Reason code (BT-98 UNCL 5189 for allowances / BT-105 UNTDID 7161
    for charges)."""

    @model_validator(mode="after")
    def _consistent(self) -> _PopustTrosak:
        razlog: str | None = self.razlog
        _provjeri_kategoriju(self.kategorija, self.pdv_stopa, razlog)
        return self


class Popust(_PopustTrosak):
    """A document-level allowance (BG-20), e.g. an order-level discount."""


class Trosak(_PopustTrosak):
    """A document-level charge (BG-21), e.g. shipping. E/O charges carry
    the HR category mark and exemption reason (HR-BR-11/13)."""


class Stavka(_Model):
    """One invoice line (BG-25).

    ``kpd`` is the Klasifikacija proizvoda po djelatnostima code, mandatory
    for every item per HR-BR-25 (``ItemClassificationCode listID="CG"``) —
    except on document types the rule exempts (credit notes, advance
    invoices, …), which `ERacun` enforces with the document context.
    """

    naziv: str = Field(min_length=1, max_length=1023)
    kolicina: Decimal
    cijena: Decimal
    """Net unit price (BT-146)."""
    kpd: str | None = Field(default=None, min_length=1)
    pdv_stopa: Decimal = Decimal("0")
    kategorija: KategorijaPdv = KategorijaPdv.STANDARDNA
    razlog_oslobodjenja: str | None = None
    """Exemption reason (BT-120) — required for E / AE / O categories."""
    jedinica: str = "H87"
    """UN/ECE Rec 20 unit code (H87 = piece)."""
    opis: str | None = Field(default=None, max_length=4095)

    @model_validator(mode="after")
    def _consistent(self) -> Stavka:
        _provjeri_kategoriju(self.kategorija, self.pdv_stopa, self.razlog_oslobodjenja)
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
    """UNCL 1001 document type: 380 commercial invoice, 381 credit note
    (odobrenje — serialised as a UBL CreditNote), 386 advance invoice."""
    prethodni_racuni: tuple[PrethodniRacun, ...] = ()
    """Preceding-invoice references (BG-3, ``BillingReference``)."""
    popusti: tuple[Popust, ...] = ()
    """Document-level allowances (BG-20)."""
    troskovi: tuple[Trosak, ...] = ()
    """Document-level charges (BG-21)."""

    @property
    def je_odobrenje(self) -> bool:
        """True for a credit note (381), serialised as a UBL CreditNote."""
        return self.vrsta == ODOBRENJE

    @model_validator(mode="after")
    def _due_date_when_payable(self) -> ERacun:
        # HR-BR-4 negates the payable amount for credit notes, so a credit
        # never requires a due date.
        if self.je_odobrenje:
            return self
        if self.ukupno_s_pdv > 0 and self.datum_dospijeca is None:
            raise ValueError(
                "datum_dospijeca is required when the payable amount is positive (HR-BR-4)"
            )
        return self

    @model_validator(mode="after")
    def _kpd_when_required(self) -> ERacun:
        if self.vrsta in KPD_EXEMPT_VRSTE:
            return self
        for index, stavka in enumerate(self.stavke, start=1):
            if stavka.kpd is None:
                raise ValueError(
                    f"stavka {index} ({stavka.naziv!r}) needs a kpd code — mandatory "
                    f"for document type {self.vrsta} (HR-BR-25)"
                )
        return self

    @property
    def grupe_pdv(self) -> dict[tuple[KategorijaPdv, Decimal], Decimal]:
        """Taxable base per (category, rate) group — one ``TaxSubtotal``
        each. Per EN 16931 (BR-45): line nets of the group, minus its
        document-level allowances, plus its charges."""
        groups: dict[tuple[KategorijaPdv, Decimal], Decimal] = {}
        for stavka in self.stavke:
            key = (stavka.kategorija, stavka.pdv_stopa)
            groups[key] = groups.get(key, Decimal("0")) + stavka.neto
        for popust in self.popusti:
            key = (popust.kategorija, popust.pdv_stopa)
            groups[key] = groups.get(key, Decimal("0")) - popust.iznos
        for trosak in self.troskovi:
            key = (trosak.kategorija, trosak.pdv_stopa)
            groups[key] = groups.get(key, Decimal("0")) + trosak.iznos
        return groups

    def razlozi_oslobodjenja(self, kategorija: KategorijaPdv, stopa: Decimal) -> tuple[str, ...]:
        """Distinct exemption reasons of a (category, rate) group, from its
        lines and its document-level allowances/charges."""
        exempt_like = (
            KategorijaPdv.OSLOBODJENO,
            KategorijaPdv.PRIJENOS_POREZNE_OBVEZE,
            KategorijaPdv.NE_PODLIJEZE,
        )
        reasons = {
            s.razlog_oslobodjenja
            for s in self.stavke
            if (s.kategorija, s.pdv_stopa) == (kategorija, stopa) and s.razlog_oslobodjenja
        }
        if kategorija in exempt_like:
            for stavka_pt in (*self.popusti, *self.troskovi):
                if (stavka_pt.kategorija, stavka_pt.pdv_stopa) == (kategorija, stopa):
                    reasons.add(stavka_pt.razlog)
        return tuple(sorted(reasons))

    @property
    def ukupno_neto(self) -> Decimal:
        """Sum of line net amounts (BT-106)."""
        return sum((s.neto for s in self.stavke), Decimal("0.00"))

    @property
    def ukupno_popust(self) -> Decimal:
        """Sum of document-level allowances (BT-107)."""
        return sum((p.iznos for p in self.popusti), Decimal("0.00"))

    @property
    def ukupno_trosak(self) -> Decimal:
        """Sum of document-level charges (BT-108)."""
        return sum((t.iznos for t in self.troskovi), Decimal("0.00"))

    @property
    def osnovica(self) -> Decimal:
        """Invoice total without PDV (BT-109): lines - allowances + charges."""
        return self.ukupno_neto - self.ukupno_popust + self.ukupno_trosak

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
        return self.osnovica + self.ukupno_pdv
