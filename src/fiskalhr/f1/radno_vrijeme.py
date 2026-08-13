"""Working-hours (radno vrijeme) registration — new in schema v1.10.

Models, serialisation, and parsing for ``PrijaviRadnoVrijemeZahtjev``,
``ObrisiRadnoVrijemeZahtjev``, and ``DohvatiRadnoVrijemeZahtjev``. These
messages register/delete/fetch a business premises' working hours; they
carry no receipt and therefore no ZKI — they are simply signed and sent.

Schedule structure per the schema (spec v2.7, radno-vrijeme chapters):

- up to 3 ``Redovno`` (regular) blocks, each valid from ``DatumOd``, with a
  schedule that is exactly one of: ``PoDogovoru`` (by arrangement),
  ``Jednokratno`` (single daily interval, ≤8 entries), ``Dvokratno`` (split
  shift, ≤16 entries), or ``ParniNeparni`` (even/odd date pattern, ≤16);
- up to 10 ``Iznimke`` (exceptions) for specific dates, each either one
  ``Jednokratno`` interval or exactly two ``Dvokratno`` parts.

``DanUTjednu``: 1-7 are Monday-Sunday, **8 is a public holiday** (praznik,
državni blagdan).

The bulk method ``PrijaviRadnoVrijemeZaPoslovnice`` registers hours for
1-100 premises in one message (`Poslovnica`, each with one regular block or
one exception); the response reports per-premises outcomes
(`PoslovniceOdgovor`).
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import Annotated, Union

from lxml import etree
from pydantic import Field, field_validator

from fiskalhr.core.errors import FiskalizacijaError
from fiskalhr.f1.messages import DATUM_VRIJEME_FORMAT, F73_NS
from fiskalhr.f1.models import Greska, Oib, PorukaOdgovora, _Model

__all__ = [
    "BrisanjeRadnogVremena",
    "DanUTjednu",
    "DioDvokratnog",
    "Dvokratno",
    "DvokratnoIznimka",
    "Iznimka",
    "Jednokratno",
    "JednokratnoIznimka",
    "ParNepar",
    "ParniNeparni",
    "PoDogovoru",
    "Poslovnica",
    "PoslovnicaOdgovor",
    "PoslovniceOdgovor",
    "RadnoVrijeme",
    "RadnoVrijemeOdgovor",
    "Redovno",
    "VrstaRadnogVremena",
    "build_dohvati_radno_vrijeme_zahtjev",
    "build_obrisi_radno_vrijeme_zahtjev",
    "build_prijavi_radno_vrijeme_za_poslovnice_zahtjev",
    "build_prijavi_radno_vrijeme_zahtjev",
    "parse_dohvati_radno_vrijeme_odgovor",
    "parse_prijavi_radno_vrijeme_za_poslovnice_odgovor",
]

DATUM_FORMAT = "%d.%m.%Y"
"""``DatumType`` — dates without time."""

Vrijeme = Annotated[str, Field(pattern=r"^([01][0-9]:[0-5][0-9]|2[0-3]:[0-5][0-9]|24:00)$")]
"""``VrijemeType`` — ``HH:MM``, up to ``24:00``."""


class DanUTjednu(enum.StrEnum):
    """``DanUTjednuType`` — 1-7 Monday-Sunday, 8 public holiday."""

    PONEDJELJAK = "1"
    UTORAK = "2"
    SRIJEDA = "3"
    CETVRTAK = "4"
    PETAK = "5"
    SUBOTA = "6"
    NEDJELJA = "7"
    PRAZNIK = "8"


class ParNepar(enum.StrEnum):
    """``ParNeparType`` — even (parni) / odd (neparni) dates."""

    PARNI = "P"
    NEPARNI = "N"


class DioDvokratnog(enum.StrEnum):
    """``DioDvokratnogType`` — first or second part of a split shift."""

    PRVI = "1"
    DRUGI = "2"


class VrstaRadnogVremena(enum.StrEnum):
    """Filter for ``DohvatiRadnoVrijemeZahtjev``."""

    REDOVNO = "REDOVNO"
    IZNIMKE = "IZNIMKE"
    SVE = "SVE"


class PoDogovoru(_Model):
    """Working hours "by arrangement" — serialised as the fixed ``DA`` marker."""


class Jednokratno(_Model):
    """One continuous daily interval for a weekday."""

    dan_u_tjednu: DanUTjednu
    vrijeme_od: Vrijeme
    vrijeme_do: Vrijeme


class Dvokratno(_Model):
    """One part of a split shift for a weekday."""

    dan_u_tjednu: DanUTjednu
    dio: DioDvokratnog
    vrijeme_od: Vrijeme
    vrijeme_do: Vrijeme


class ParniNeparni(_Model):
    """Interval that applies on even or odd dates for a weekday."""

    dan_u_tjednu: DanUTjednu
    par_nepar: ParNepar
    vrijeme_od: Vrijeme
    vrijeme_do: Vrijeme


Raspored = Union[  # noqa: UP007 — Annotated unions read better spelled out
    PoDogovoru,
    tuple[Jednokratno, ...],
    tuple[Dvokratno, ...],
    tuple[ParniNeparni, ...],
]


class Redovno(_Model):
    """One regular-schedule block, valid from ``datum_od``.

    ``datum_do`` appears only in fetched schedules (``dohvat``), never when
    registering. The schedule is exactly one of the ``Raspored`` variants.
    """

    datum_od: date
    datum_do: date | None = None
    napomena: str | None = Field(default=None, min_length=1, max_length=200)
    raspored: Raspored

    @field_validator("raspored")
    @classmethod
    def _bounded(cls, value: Raspored) -> Raspored:
        if isinstance(value, tuple):
            if not value:
                raise ValueError("raspored tuple must not be empty")
            limit = 8 if isinstance(value[0], Jednokratno) else 16
            if len(value) > limit:
                raise ValueError(f"at most {limit} entries allowed for this schedule kind")
        return value


class JednokratnoIznimka(_Model):
    """Exception-day single interval (no weekday — the date is explicit)."""

    vrijeme_od: Vrijeme
    vrijeme_do: Vrijeme


class DvokratnoIznimka(_Model):
    """Exception-day split-shift part."""

    dio: DioDvokratnog
    vrijeme_od: Vrijeme
    vrijeme_do: Vrijeme


class Iznimka(_Model):
    """``IznimkeType`` — hours for one specific date."""

    datum: date
    raspored: JednokratnoIznimka | tuple[DvokratnoIznimka, DvokratnoIznimka]


class RadnoVrijeme(_Model):
    """``RadnoVrijemeType`` — up to 3 regular blocks, up to 10 exceptions."""

    redovno: tuple[Redovno, ...] = Field(default=(), max_length=3)
    iznimke: tuple[Iznimka, ...] = Field(default=(), max_length=10)


class BrisanjeRadnogVremena(_Model):
    """``RadnoVrijemeBrisanjeType`` — deletion by dates.

    ``redovno_od`` deletes regular blocks by their ``DatumOd``; ``iznimke``
    deletes exceptions by their date.
    """

    redovno_od: tuple[date, ...] = Field(default=(), max_length=3)
    iznimke: tuple[date, ...] = Field(default=(), max_length=10)


class Poslovnica(_Model):
    """``PoslovnicaType`` — one premises entry in the bulk registration:
    its oznaka plus either one regular block or one exception."""

    ozn_pos_pr: str
    raspored: Redovno | Iznimka


class PoslovnicaOdgovor(_Model):
    """``PoslovnicaOdgovorType`` — per-premises outcome of the bulk call."""

    ozn_pos_pr: str
    poruka: PorukaOdgovora | None = None
    greske: tuple[Greska, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.greske


class PoslovniceOdgovor(_Model):
    """Parsed ``PrijaviRadnoVrijemeZaPoslovniceOdgovor``.

    ``greske`` carries message-level errors (the whole request was
    rejected); otherwise ``poslovnice`` holds one outcome per premises —
    the service can accept some and reject others in the same call.
    """

    id_poruke: str | None
    datum_vrijeme: datetime
    poslovnice: tuple[PoslovnicaOdgovor, ...] = ()
    greske: tuple[Greska, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.greske and all(p.ok for p in self.poslovnice)


class RadnoVrijemeOdgovor(_Model):
    """Parsed ``DohvatiRadnoVrijemeOdgovor``."""

    id_poruke: str | None
    datum_vrijeme: datetime
    oib: str
    ozn_pos_pr: str
    radno_vrijeme: RadnoVrijeme
    greske: tuple[Greska, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.greske


# ---------------------------------------------------------------------------
# Serialisation


def _tag(name: str) -> str:
    return f"{{{F73_NS}}}{name}"


def _el(parent: etree._Element, name: str, text: str | None = None) -> etree._Element:
    element = etree.SubElement(parent, _tag(name))
    if text is not None:
        element.text = text
    return element


def _root(name: str, id_poruke: uuid.UUID | None, datum_vrijeme: datetime) -> etree._Element:
    root = etree.Element(_tag(name), attrib={"Id": name}, nsmap={"tns": F73_NS})
    zaglavlje = _el(root, "Zaglavlje")
    _el(zaglavlje, "IdPoruke", str(id_poruke if id_poruke is not None else uuid.uuid4()))
    _el(zaglavlje, "DatumVrijeme", datum_vrijeme.strftime(DATUM_VRIJEME_FORMAT))
    return root


def _interval(parent: etree._Element, vrijeme_od: str, vrijeme_do: str) -> None:
    _el(parent, "RadnoVrijemeOd", vrijeme_od)
    _el(parent, "RadnoVrijemeDo", vrijeme_do)


def _fill_redovno(parent: etree._Element, redovno: Redovno) -> None:
    element = _el(parent, "Redovno")
    _el(element, "DatumOd", redovno.datum_od.strftime(DATUM_FORMAT))
    if redovno.datum_do is not None:
        _el(element, "DatumDo", redovno.datum_do.strftime(DATUM_FORMAT))
    if redovno.napomena is not None:
        _el(element, "Napomena", redovno.napomena)

    raspored = redovno.raspored
    if isinstance(raspored, PoDogovoru):
        _el(_el(element, "PoDogovoru"), "RedovnoPoDogovoru", "DA")
        return
    for entry in raspored:
        if isinstance(entry, Jednokratno):
            item = _el(element, "Jednokratno")
            _el(item, "DanUTjednu", entry.dan_u_tjednu.value)
        elif isinstance(entry, Dvokratno):
            item = _el(element, "Dvokratno")
            _el(item, "DanUTjednu", entry.dan_u_tjednu.value)
            _el(item, "DioDvokratnog", entry.dio.value)
        else:
            item = _el(element, "ParniNeparni")
            _el(item, "DanUTjednu", entry.dan_u_tjednu.value)
            _el(item, "ParNepar", entry.par_nepar.value)
        _interval(item, entry.vrijeme_od, entry.vrijeme_do)


def _fill_iznimka(parent: etree._Element, iznimka: Iznimka, name: str = "Iznimke") -> None:
    # RadnoVrijemeType calls the element "Iznimke"; PoslovnicaType calls the
    # same IznimkeType "Iznimka".
    element = _el(parent, name)
    _el(element, "Datum", iznimka.datum.strftime(DATUM_FORMAT))
    if isinstance(iznimka.raspored, JednokratnoIznimka):
        item = _el(element, "Jednokratno")
        _interval(item, iznimka.raspored.vrijeme_od, iznimka.raspored.vrijeme_do)
    else:
        for part in iznimka.raspored:
            item = _el(element, "Dvokratno")
            _el(item, "DioDvokratnog", part.dio.value)
            _interval(item, part.vrijeme_od, part.vrijeme_do)


def _poslovni_prostor(root: etree._Element, oib: str, ozn_pos_pr: str) -> etree._Element:
    element = _el(root, "PoslovniProstor")
    _el(element, "Oib", oib)
    _el(element, "OznPosPr", ozn_pos_pr)
    return element


def build_prijavi_radno_vrijeme_zahtjev(
    oib: Oib,
    ozn_pos_pr: str,
    radno_vrijeme: RadnoVrijeme,
    oib_oper: Oib,
    *,
    datum_vrijeme: datetime,
    id_poruke: uuid.UUID | None = None,
) -> etree._Element:
    """Build a ``PrijaviRadnoVrijemeZahtjev`` (register working hours)."""
    root = _root("PrijaviRadnoVrijemeZahtjev", id_poruke, datum_vrijeme)
    prostor = _poslovni_prostor(root, oib, ozn_pos_pr)
    rv_element = _el(prostor, "RadnoVrijeme")
    for redovno in radno_vrijeme.redovno:
        _fill_redovno(rv_element, redovno)
    for iznimka in radno_vrijeme.iznimke:
        _fill_iznimka(rv_element, iznimka)
    _el(root, "OibOper", oib_oper)
    return root


def build_prijavi_radno_vrijeme_za_poslovnice_zahtjev(
    oib: Oib,
    poslovnice: tuple[Poslovnica, ...] | list[Poslovnica],
    oib_oper: Oib,
    *,
    datum_vrijeme: datetime,
    id_poruke: uuid.UUID | None = None,
) -> etree._Element:
    """Build a ``PrijaviRadnoVrijemeZaPoslovniceZahtjev`` (bulk, 1-100
    premises in one message)."""
    if not 1 <= len(poslovnice) <= 100:
        raise ValueError(f"a message carries 1-100 poslovnice, got {len(poslovnice)}")
    root = _root("PrijaviRadnoVrijemeZaPoslovniceZahtjev", id_poruke, datum_vrijeme)
    _el(root, "Oib", oib)
    prostori = _el(root, "PoslovniProstori")
    for poslovnica in poslovnice:
        element = _el(prostori, "Poslovnica")
        _el(element, "OznPosPr", poslovnica.ozn_pos_pr)
        if isinstance(poslovnica.raspored, Iznimka):
            _fill_iznimka(element, poslovnica.raspored, name="Iznimka")
        else:
            _fill_redovno(element, poslovnica.raspored)
    _el(root, "OibOper", oib_oper)
    return root


def build_obrisi_radno_vrijeme_zahtjev(
    oib: Oib,
    ozn_pos_pr: str,
    brisanje: BrisanjeRadnogVremena,
    oib_oper: Oib,
    *,
    datum_vrijeme: datetime,
    id_poruke: uuid.UUID | None = None,
) -> etree._Element:
    """Build an ``ObrisiRadnoVrijemeZahtjev`` (delete working hours by date)."""
    root = _root("ObrisiRadnoVrijemeZahtjev", id_poruke, datum_vrijeme)
    prostor = _poslovni_prostor(root, oib, ozn_pos_pr)
    brisanje_element = _el(prostor, "BrisanjeRadnogVremena")
    for datum_od in brisanje.redovno_od:
        _el(_el(brisanje_element, "Redovno"), "DatumOd", datum_od.strftime(DATUM_FORMAT))
    for datum in brisanje.iznimke:
        _el(_el(brisanje_element, "Iznimke"), "Datum", datum.strftime(DATUM_FORMAT))
    _el(root, "OibOper", oib_oper)
    return root


def build_dohvati_radno_vrijeme_zahtjev(
    oib: Oib,
    ozn_pos_pr: str,
    vrsta: VrstaRadnogVremena,
    oib_oper: Oib,
    *,
    datum_vrijeme: datetime,
    id_poruke: uuid.UUID | None = None,
) -> etree._Element:
    """Build a ``DohvatiRadnoVrijemeZahtjev`` (fetch active working hours)."""
    root = _root("DohvatiRadnoVrijemeZahtjev", id_poruke, datum_vrijeme)
    _el(root, "Oib", oib)
    _el(root, "OznPosPr", ozn_pos_pr)
    _el(root, "VrstaRadnogVremena", vrsta.value)
    _el(root, "OibOper", oib_oper)
    return root


# ---------------------------------------------------------------------------
# Parsing


def _parse_date(text: str | None) -> date:
    if not text:
        raise FiskalizacijaError("missing date value in radno vrijeme response")
    return datetime.strptime(text, DATUM_FORMAT).date()


def _parse_interval(element: etree._Element) -> tuple[str, str]:
    return (
        element.findtext(_tag("RadnoVrijemeOd")) or "",
        element.findtext(_tag("RadnoVrijemeDo")) or "",
    )


def _parse_redovno(element: etree._Element) -> Redovno:
    raspored: Raspored
    if element.find(_tag("PoDogovoru")) is not None:
        raspored = PoDogovoru()
    elif jednokratna := element.findall(_tag("Jednokratno")):
        raspored = tuple(
            Jednokratno(
                dan_u_tjednu=DanUTjednu(item.findtext(_tag("DanUTjednu")) or ""),
                vrijeme_od=_parse_interval(item)[0],
                vrijeme_do=_parse_interval(item)[1],
            )
            for item in jednokratna
        )
    elif dvokratna := element.findall(_tag("Dvokratno")):
        raspored = tuple(
            Dvokratno(
                dan_u_tjednu=DanUTjednu(item.findtext(_tag("DanUTjednu")) or ""),
                dio=DioDvokratnog(item.findtext(_tag("DioDvokratnog")) or ""),
                vrijeme_od=_parse_interval(item)[0],
                vrijeme_do=_parse_interval(item)[1],
            )
            for item in dvokratna
        )
    else:
        raspored = tuple(
            ParniNeparni(
                dan_u_tjednu=DanUTjednu(item.findtext(_tag("DanUTjednu")) or ""),
                par_nepar=ParNepar(item.findtext(_tag("ParNepar")) or ""),
                vrijeme_od=_parse_interval(item)[0],
                vrijeme_do=_parse_interval(item)[1],
            )
            for item in element.findall(_tag("ParniNeparni"))
        )
    datum_do = element.findtext(_tag("DatumDo"))
    return Redovno(
        datum_od=_parse_date(element.findtext(_tag("DatumOd"))),
        datum_do=_parse_date(datum_do) if datum_do else None,
        napomena=element.findtext(_tag("Napomena")),
        raspored=raspored,
    )


def _parse_iznimka(element: etree._Element) -> Iznimka:
    raspored: JednokratnoIznimka | tuple[DvokratnoIznimka, DvokratnoIznimka]
    jednokratno = element.find(_tag("Jednokratno"))
    if jednokratno is not None:
        od, do = _parse_interval(jednokratno)
        raspored = JednokratnoIznimka(vrijeme_od=od, vrijeme_do=do)
    else:
        parts = [
            DvokratnoIznimka(
                dio=DioDvokratnog(item.findtext(_tag("DioDvokratnog")) or ""),
                vrijeme_od=_parse_interval(item)[0],
                vrijeme_do=_parse_interval(item)[1],
            )
            for item in element.findall(_tag("Dvokratno"))
        ]
        if len(parts) != 2:
            raise FiskalizacijaError("Iznimke must carry exactly two Dvokratno parts")
        raspored = (parts[0], parts[1])
    return Iznimka(datum=_parse_date(element.findtext(_tag("Datum"))), raspored=raspored)


def parse_dohvati_radno_vrijeme_odgovor(xml: bytes | etree._Element) -> RadnoVrijemeOdgovor:
    """Parse a ``DohvatiRadnoVrijemeOdgovor`` into models."""
    # Late import to avoid a cycle: messages does not know about this module.
    from fiskalhr.f1.messages import _parse_greske, _parse_zaglavlje

    root = etree.fromstring(xml) if isinstance(xml, bytes) else xml
    if root.tag != _tag("DohvatiRadnoVrijemeOdgovor"):
        raise FiskalizacijaError(f"expected DohvatiRadnoVrijemeOdgovor, got {root.tag!r}")
    id_poruke, datum_vrijeme = _parse_zaglavlje(root, "DohvatiRadnoVrijemeOdgovor")

    prostor = root.find(_tag("PoslovniProstor"))
    if prostor is None:
        raise FiskalizacijaError("DohvatiRadnoVrijemeOdgovor has no PoslovniProstor")
    rv_element = prostor.find(_tag("RadnoVrijeme"))
    radno_vrijeme = RadnoVrijeme(
        redovno=tuple(_parse_redovno(el) for el in rv_element.findall(_tag("Redovno")))
        if rv_element is not None
        else (),
        iznimke=tuple(_parse_iznimka(el) for el in rv_element.findall(_tag("Iznimke")))
        if rv_element is not None
        else (),
    )
    return RadnoVrijemeOdgovor(
        id_poruke=id_poruke,
        datum_vrijeme=datum_vrijeme,
        oib=prostor.findtext(_tag("Oib")) or "",
        ozn_pos_pr=prostor.findtext(_tag("OznPosPr")) or "",
        radno_vrijeme=radno_vrijeme,
        greske=_parse_greske(root),
    )


def parse_prijavi_radno_vrijeme_za_poslovnice_odgovor(
    xml: bytes | etree._Element,
) -> PoslovniceOdgovor:
    """Parse a ``PrijaviRadnoVrijemeZaPoslovniceOdgovor`` into models."""
    # Late import to avoid a cycle: messages does not know about this module.
    from fiskalhr.f1.messages import _parse_greske, _parse_zaglavlje

    root = etree.fromstring(xml) if isinstance(xml, bytes) else xml
    expected = "PrijaviRadnoVrijemeZaPoslovniceOdgovor"
    if root.tag != _tag(expected):
        raise FiskalizacijaError(f"expected {expected}, got {root.tag!r}")
    id_poruke, datum_vrijeme = _parse_zaglavlje(root, expected)

    poslovnice = []
    odgovori = root.find(_tag("PoslovniProstoriOdgovor"))
    if odgovori is not None:
        for element in odgovori.findall(_tag("PoslovnicaOdgovor")):
            poruka_el = element.find(_tag("PorukaOdgovora"))
            poruka = None
            if poruka_el is not None:
                poruka = PorukaOdgovora(
                    sifra=(poruka_el.findtext(_tag("SifraPoruke")) or "").strip(),
                    poruka=(poruka_el.findtext(_tag("Poruka")) or "").strip(),
                )
            poslovnice.append(
                PoslovnicaOdgovor(
                    ozn_pos_pr=element.findtext(_tag("OznPosPr")) or "",
                    poruka=poruka,
                    greske=_parse_greske(element),
                )
            )
    return PoslovniceOdgovor(
        id_poruke=id_poruke,
        datum_vrijeme=datum_vrijeme,
        poslovnice=tuple(poslovnice),
        greske=_parse_greske(root),
    )
