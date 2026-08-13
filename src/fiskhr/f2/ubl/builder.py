"""Fluent builder for eRačun documents — the API from the project plan."""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal
from typing import Any

from lxml import etree

from fiskhr.f2.ubl.models import (
    ODOBRENJE,
    Adresa,
    ERacun,
    KategorijaPdv,
    Operater,
    Popust,
    PrethodniRacun,
    Stavka,
    Stranka,
    Trosak,
)
from fiskhr.f2.ubl.xml import to_xml

__all__ = ["ERacunBuilder"]


class ERacunBuilder:
    """Accumulates invoice data and produces a validated `ERacun`.

    Example::

        eracun = (
            ERacunBuilder()
            .izdavatelj(oib="...", naziv="Tvrtka d.o.o.",
                        ulica="Ulica 1", grad="Zagreb", postanski_broj="10000")
            .primatelj(oib="...", naziv="Kupac d.o.o.",
                       ulica="Ulica 2", grad="Rijeka", postanski_broj="51000")
            .operater(oib="...", oznaka="Operater1")
            .broj("2026-0042-P1-1")
            .datum_izdavanja(date(2026, 8, 13), time(12, 0, 0))
            .datum_isporuke(date(2026, 7, 31))
            .dospijece(date(2026, 9, 12))
            .placanje(iban="HR...", poziv_na_broj="HR00 42")
            .stavka(naziv="Licenca", kpd="62.01.29", kolicina=1,
                    cijena=Decimal("100.00"), pdv_stopa=25)
            .build()
        )
        xml = eracun.to_xml()  # via fiskhr.f2.ubl.to_xml(eracun)

    All validation lives in the models; `build` simply assembles them, so
    errors carry Pydantic's field-level context.
    """

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._stavke: list[Stavka] = []
        self._prethodni: list[PrethodniRacun] = []
        self._popusti: list[Popust] = []
        self._troskovi: list[Trosak] = []

    def izdavatelj(
        self,
        *,
        oib: str,
        naziv: str,
        ulica: str,
        grad: str,
        postanski_broj: str,
        drzava: str = "HR",
        elektronicka_adresa: str | None = None,
        pravni_oblik: str | None = None,
    ) -> ERacunBuilder:
        self._data["izdavatelj"] = Stranka(
            oib=oib,
            naziv=naziv,
            adresa=Adresa(ulica=ulica, grad=grad, postanski_broj=postanski_broj, drzava=drzava),
            elektronicka_adresa=elektronicka_adresa,
            pravni_oblik=pravni_oblik,
        )
        return self

    def primatelj(
        self,
        *,
        oib: str,
        naziv: str,
        ulica: str,
        grad: str,
        postanski_broj: str,
        drzava: str = "HR",
        elektronicka_adresa: str | None = None,
    ) -> ERacunBuilder:
        self._data["primatelj"] = Stranka(
            oib=oib,
            naziv=naziv,
            adresa=Adresa(ulica=ulica, grad=grad, postanski_broj=postanski_broj, drzava=drzava),
            elektronicka_adresa=elektronicka_adresa,
        )
        return self

    def operater(self, *, oib: str, oznaka: str) -> ERacunBuilder:
        self._data["operater"] = Operater(oib=oib, oznaka=oznaka)
        return self

    def broj(self, broj: str) -> ERacunBuilder:
        self._data["broj"] = broj
        return self

    def datum_izdavanja(self, datum: date, vrijeme: time) -> ERacunBuilder:
        self._data["datum_izdavanja"] = datum
        self._data["vrijeme_izdavanja"] = vrijeme
        return self

    def datum_isporuke(self, datum: date) -> ERacunBuilder:
        self._data["datum_isporuke"] = datum
        return self

    def dospijece(self, datum: date) -> ERacunBuilder:
        self._data["datum_dospijeca"] = datum
        return self

    def placanje(
        self,
        *,
        iban: str | None = None,
        poziv_na_broj: str | None = None,
        nacin: str = "30",
        opis: str | None = None,
    ) -> ERacunBuilder:
        self._data["iban"] = iban
        self._data["poziv_na_broj"] = poziv_na_broj
        self._data["nacin_placanja"] = nacin
        self._data["opis_placanja"] = opis
        return self

    def napomena(self, tekst: str) -> ERacunBuilder:
        self._data["napomena"] = tekst
        return self

    def vrsta(self, kod: str) -> ERacunBuilder:
        """UNCL 1001 document type; 381 produces a UBL CreditNote."""
        self._data["vrsta"] = kod
        return self

    def prethodni_racun(self, broj: str, datum_izdavanja: date) -> ERacunBuilder:
        """Reference a preceding invoice (BG-3); repeatable."""
        self._prethodni.append(PrethodniRacun(broj=broj, datum_izdavanja=datum_izdavanja))
        return self

    def odobrenje(self, broj_racuna: str, datum_izdavanja: date) -> ERacunBuilder:
        """Make this a credit note (381) for the referenced invoice.

        Amounts stay positive — a UBL CreditNote credits what its lines
        state. KPD codes become optional on the lines (HR-BR-25), and no
        due date is required (HR-BR-4).
        """
        return self.vrsta(ODOBRENJE).prethodni_racun(broj_racuna, datum_izdavanja)

    def stavka(
        self,
        *,
        naziv: str,
        kpd: str | None = None,
        kolicina: Decimal | int | str,
        cijena: Decimal | int | str,
        pdv_stopa: Decimal | int | str = 0,
        kategorija: KategorijaPdv = KategorijaPdv.STANDARDNA,
        razlog_oslobodjenja: str | None = None,
        jedinica: str = "H87",
        opis: str | None = None,
    ) -> ERacunBuilder:
        self._stavke.append(
            Stavka(
                naziv=naziv,
                kpd=kpd,
                kolicina=Decimal(str(kolicina)),
                cijena=Decimal(str(cijena)),
                pdv_stopa=Decimal(str(pdv_stopa)),
                kategorija=kategorija,
                razlog_oslobodjenja=razlog_oslobodjenja,
                jedinica=jedinica,
                opis=opis,
            )
        )
        return self

    def popust(
        self,
        *,
        iznos: Decimal | int | str,
        razlog: str,
        kategorija: KategorijaPdv = KategorijaPdv.STANDARDNA,
        pdv_stopa: Decimal | int | str = 0,
        razlog_kod: str | None = None,
    ) -> ERacunBuilder:
        """A document-level allowance (BG-20); joins its VAT group's base."""
        self._popusti.append(
            Popust(
                iznos=Decimal(str(iznos)),
                razlog=razlog,
                kategorija=kategorija,
                pdv_stopa=Decimal(str(pdv_stopa)),
                razlog_kod=razlog_kod,
            )
        )
        return self

    def trosak(
        self,
        *,
        iznos: Decimal | int | str,
        razlog: str,
        kategorija: KategorijaPdv = KategorijaPdv.STANDARDNA,
        pdv_stopa: Decimal | int | str = 0,
        razlog_kod: str | None = None,
    ) -> ERacunBuilder:
        """A document-level charge (BG-21), e.g. shipping or a fee."""
        self._troskovi.append(
            Trosak(
                iznos=Decimal(str(iznos)),
                razlog=razlog,
                kategorija=kategorija,
                pdv_stopa=Decimal(str(pdv_stopa)),
                razlog_kod=razlog_kod,
            )
        )
        return self

    def build(self) -> ERacun:
        """Assemble the `ERacun`; raises Pydantic errors for anything missing."""
        return ERacun(
            **self._data,
            stavke=tuple(self._stavke),
            prethodni_racuni=tuple(self._prethodni),
            popusti=tuple(self._popusti),
            troskovi=tuple(self._troskovi),
        )

    def to_xml(self) -> etree._Element:
        """Convenience: ``build()`` then serialise."""
        return to_xml(self.build())
