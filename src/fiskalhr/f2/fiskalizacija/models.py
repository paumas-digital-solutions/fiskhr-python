"""eFiskalizacija data models (Pydantic v2), mirroring eFiskalizacijaSchema.xsd.

The ``EvidentirajERacun`` message does not carry the eRačun itself — it
carries a structured digest of it (identifiers, parties, totals, the VAT
breakdown, and per-line data). `EvidencijaERacun.from_eracuna` derives that
digest from a `fiskalhr.f2.ubl.ERacun`, so the same model that produced the
UBL document also feeds fiscalization; every field can equally be supplied
directly for invoices produced elsewhere.

On exemption reasons: the spec's checks table (ch. 3.3) pairs the VATEX
code (``razlogOslobodenja``) with the reason text
(``tekstRazlogaOslobodenja``) for the AE category. The official examples
ship AE breakdowns with the text alone, so this model requires only the
text and treats the VATEX code as optional — the demo environment is the
authority on how strictly the pairing is enforced.
"""

from __future__ import annotations

import enum
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from fiskalhr.f2.ubl.models import ERacun, KategorijaPdv, Oib, hr_oznaka

__all__ = [
    "DokumentUkupanIznos",
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
]


class VrstaERacuna(enum.StrEnum):
    """Which side of the exchange is reporting (``Zaglavlje/vrstaERacuna``)."""

    IZLAZNI = "I"
    """Outgoing — reported by the issuer during issuance."""
    ULAZNI = "U"
    """Incoming — reported by the recipient upon receipt."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PrethodniERacun(_Model):
    """Reference to a preceding invoice (BG-3), e.g. for corrections."""

    broj: str = Field(min_length=1, max_length=100)
    datum_izdavanja: date


class Izdavatelj(_Model):
    """Issuer identification (BG-4 + the operator's OIB, HR-BT-5)."""

    ime: str = Field(min_length=1, max_length=1024)
    oib: Oib
    oib_operatera: Oib


class Primatelj(_Model):
    """Recipient identification (BG-7)."""

    ime: str = Field(min_length=1, max_length=1024)
    oib: Oib


class PrijenosSredstava(_Model):
    """Credit-transfer payment instructions (BG-17). ``iban`` is BT-84;
    the service checks it is an IBAN."""

    iban: str = Field(min_length=1, max_length=200)
    naziv_racuna: str | None = Field(default=None, max_length=500)
    pruzatelj_platnih_usluga: str | None = Field(default=None, max_length=200)


class DokumentUkupanIznos(_Model):
    """Document totals (BG-22)."""

    neto: Decimal
    """Sum of line net amounts (BT-106)."""
    popust: Decimal | None = None
    """Sum of document-level allowances (BT-107)."""
    trosak: Decimal | None = None
    """Sum of document-level charges (BT-108)."""
    iznos_bez_pdv: Decimal
    """Invoice total without PDV (BT-109)."""
    pdv: Decimal
    """Invoice total PDV (BT-110)."""
    iznos_s_pdv: Decimal
    """Invoice total with PDV (BT-112)."""
    placeni_iznos: Decimal | None = None
    """Prepaid amount (BT-113)."""
    iznos_koji_dospijeva: Decimal
    """Amount due for payment (BT-115)."""


class RaspodjelaPdv(_Model):
    """One VAT breakdown group (BG-23)."""

    kategorija: KategorijaPdv
    osnovica: Decimal
    """Taxable amount for the group (BT-116)."""
    iznos: Decimal
    """PDV amount for the group (BT-117)."""
    stopa: Decimal | None = None
    razlog_oslobodjenja_kod: str | None = None
    """VATEX exemption reason code (BT-121)."""
    razlog_oslobodjenja: str | None = None
    """Exemption reason text (BT-120)."""
    hr_oznaka: str | None = None
    """HR VAT category mark (HR-BT-22), e.g. ``HR:PDV25`` / ``HR:E``."""


class StavkaEvidencije(_Model):
    """One reported invoice line (mirrors ``StavkaERacuna``)."""

    kolicina: Decimal
    jedinica: str = Field(pattern=r"^[A-Z0-9]{2,3}$")
    neto: Decimal
    """Line net amount (BT-131)."""
    cijena: Decimal
    """Item net price (BT-146)."""
    bruto_cijena: Decimal | None = None
    """Item gross price before discounts (BT-148)."""
    osnovna_kolicina: Decimal | None = None
    """Item price base quantity (BT-149)."""
    jedinica_osnovne_kolicine: str | None = Field(default=None, pattern=r"^[A-Z0-9]{2,3}$")
    kategorija: KategorijaPdv
    stopa: Decimal | None = None
    naziv: str = Field(min_length=1, max_length=1024)
    opis: str | None = Field(default=None, max_length=4096)
    hr_oznaka: str | None = None
    """HR VAT category mark of the line (HR-BT-12)."""
    kpd: str | None = Field(default=None, max_length=10)
    """KPD (CPA) classification code, reported with scheme ``CG``."""


class EvidencijaERacun(_Model):
    """The reported digest of one eRačun (``ERacun`` complex type)."""

    broj: str = Field(min_length=1, max_length=100)
    """Document number (BT-1) — with issue date and issuer OIB, the
    eRačun identifier the service deduplicates on."""
    datum_izdavanja: date
    vrsta_dokumenta: str = "380"
    """UNTDID 1001 document type code (BT-3)."""
    valuta: str = Field(default="EUR", pattern=r"^[A-Z]{3}$")
    datum_dospijeca: date | None = None
    vrsta_poslovnog_procesa: str = Field(default="P1", max_length=200)
    """Business process (BT-23), the ``ProfileID`` of the invoice."""
    referenca_na_ugovor: str | None = Field(default=None, max_length=1024)
    datum_isporuke: date | None = None
    prethodni_eracuni: tuple[PrethodniERacun, ...] = ()
    izdavatelj: Izdavatelj
    primatelj: Primatelj
    prijenosi_sredstava: tuple[PrijenosSredstava, ...] = ()
    ukupan_iznos: DokumentUkupanIznos
    raspodjele_pdv: tuple[RaspodjelaPdv, ...] = Field(min_length=1)
    stavke: tuple[StavkaEvidencije, ...] = Field(min_length=1)
    indikator_kopije: bool = False

    @classmethod
    def from_eracuna(cls, racun: ERacun) -> EvidencijaERacun:
        """Derive the fiscalization digest from a UBL `ERacun` model.

        Totals, the VAT breakdown (including HR category marks and
        exemption reasons), and line data all come from the same computed
        properties that feed the UBL serialisation, so the reported values
        match the document by construction.
        """
        raspodjele = []
        for (kategorija, stopa), osnovica in racun.grupe_pdv.items():
            reasons = sorted(
                {
                    s.razlog_oslobodjenja
                    for s in racun.stavke
                    if (s.kategorija, s.pdv_stopa) == (kategorija, stopa) and s.razlog_oslobodjenja
                }
            )
            raspodjele.append(
                RaspodjelaPdv(
                    kategorija=kategorija,
                    osnovica=osnovica,
                    iznos=(osnovica * stopa / 100).quantize(Decimal("0.01")),
                    stopa=stopa,
                    razlog_oslobodjenja="; ".join(reasons) if reasons else None,
                    hr_oznaka=hr_oznaka(kategorija, stopa),
                )
            )
        stavke = tuple(
            StavkaEvidencije(
                kolicina=s.kolicina,
                jedinica=s.jedinica,
                neto=s.neto,
                cijena=s.cijena,
                kategorija=s.kategorija,
                stopa=s.pdv_stopa,
                naziv=s.naziv,
                opis=s.opis,
                hr_oznaka=hr_oznaka(s.kategorija, s.pdv_stopa),
                kpd=s.kpd,
            )
            for s in racun.stavke
        )
        return cls(
            broj=racun.broj,
            datum_izdavanja=racun.datum_izdavanja,
            vrsta_dokumenta=racun.vrsta,
            valuta=racun.valuta,
            datum_dospijeca=racun.datum_dospijeca,
            vrsta_poslovnog_procesa=racun.profil,
            datum_isporuke=racun.datum_isporuke,
            izdavatelj=Izdavatelj(
                ime=racun.izdavatelj.naziv,
                oib=racun.izdavatelj.oib,
                oib_operatera=racun.operater.oib,
            ),
            primatelj=Primatelj(ime=racun.primatelj.naziv, oib=racun.primatelj.oib),
            prijenosi_sredstava=(
                (PrijenosSredstava(iban=racun.iban),) if racun.iban is not None else ()
            ),
            ukupan_iznos=DokumentUkupanIznos(
                neto=racun.ukupno_neto,
                iznos_bez_pdv=racun.ukupno_neto,
                pdv=racun.ukupno_pdv,
                iznos_s_pdv=racun.ukupno_s_pdv,
                iznos_koji_dospijeva=racun.ukupno_s_pdv,
            ),
            raspodjele_pdv=tuple(raspodjele),
            stavke=stavke,
        )


class EvidencijaGreska(_Model):
    """Error detail in a rejection (``Odgovor/greska``)."""

    sifra: str
    redni_broj_zapisa: int
    """1-based index of the ``ERacun`` record the error refers to."""
    opis: str


class EvidencijaOdgovor(_Model):
    """Parsed ``EvidentirajERacunOdgovor``."""

    id_zahtjeva: str
    """Server-assigned UUID of the received request."""
    prihvacen: bool
    greska: EvidencijaGreska | None = None
