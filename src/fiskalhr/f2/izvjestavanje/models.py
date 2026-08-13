"""eIzvještavanje data models (Pydantic v2), mirroring eIzvjestavanjeSchema.xsd.

Payments (``Naplata``) and rejections (``Odbijanje``) reference an already
fiscalized eRačun by its identifier — document number, issue date, and the
two OIBs. The ``za_eracun`` constructors fill that identifier from a
`fiskalhr.f2.ubl.ERacun`, so reporting a payment for an invoice built with
`ERacunBuilder` is one call.

To *cancel* previously reported payment data, the spec says to re-send it
with negative amounts (ch. 4.1.2).
"""

from __future__ import annotations

import enum
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from fiskalhr.f2.ubl.models import ERacun, Oib

__all__ = [
    "NacinPlacanjaNaplate",
    "Naplata",
    "Odbijanje",
    "RazlogOdbijanja",
]


class NacinPlacanjaNaplate(enum.StrEnum):
    """How the payment was made (``nacinPlacanja`` codebook)."""

    TRANSAKCIJSKI_RACUN = "T"
    OBRACUNSKO_PLACANJE = "O"
    OSTALO = "Z"


class RazlogOdbijanja(enum.StrEnum):
    """Rejection reason category (``razlogOdbijanja`` codebook)."""

    NEUSKLADJENOST = "N"
    """Data mismatch that does not affect the tax computation."""
    NEUSKLADJENOST_POREZ = "U"
    """Data mismatch that affects the tax computation."""
    OSTALO = "O"


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _Identifikator(_Model):
    """The eRačun identifier every report references."""

    broj: str = Field(min_length=1, max_length=100)
    """Document number (BT-1)."""
    datum_izdavanja: date
    oib_izdavatelja: Oib
    oib_primatelja: Oib


class Naplata(_Identifikator):
    """One reported payment (``Naplata``), sent by the invoice's issuer."""

    datum_naplate: date
    naplaceni_iznos: Decimal
    nacin_placanja: NacinPlacanjaNaplate = NacinPlacanjaNaplate.TRANSAKCIJSKI_RACUN

    @classmethod
    def za_eracun(
        cls,
        racun: ERacun,
        *,
        datum_naplate: date,
        naplaceni_iznos: Decimal | None = None,
        nacin_placanja: NacinPlacanjaNaplate = NacinPlacanjaNaplate.TRANSAKCIJSKI_RACUN,
    ) -> Naplata:
        """A payment report for an invoice built with `ERacunBuilder`.

        ``naplaceni_iznos`` defaults to the invoice's payable amount
        (paid in full).
        """
        return cls(
            broj=racun.broj,
            datum_izdavanja=racun.datum_izdavanja,
            oib_izdavatelja=racun.izdavatelj.oib,
            oib_primatelja=racun.primatelj.oib,
            datum_naplate=datum_naplate,
            naplaceni_iznos=(
                naplaceni_iznos if naplaceni_iznos is not None else racun.ukupno_s_pdv
            ),
            nacin_placanja=nacin_placanja,
        )


class Odbijanje(_Identifikator):
    """One reported rejection (``Odbijanje``), sent by the recipient."""

    datum_odbijanja: date
    vrsta_razloga: RazlogOdbijanja
    razlog: str = Field(min_length=1, max_length=1024)

    @classmethod
    def za_eracun(
        cls,
        racun: ERacun,
        *,
        datum_odbijanja: date,
        vrsta_razloga: RazlogOdbijanja,
        razlog: str,
    ) -> Odbijanje:
        """A rejection report for a received invoice."""
        return cls(
            broj=racun.broj,
            datum_izdavanja=racun.datum_izdavanja,
            oib_izdavatelja=racun.izdavatelj.oib,
            oib_primatelja=racun.primatelj.oib,
            datum_odbijanja=datum_odbijanja,
            vrsta_razloga=vrsta_razloga,
            razlog=razlog,
        )
