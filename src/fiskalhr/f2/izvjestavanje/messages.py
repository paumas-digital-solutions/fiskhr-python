"""Building and parsing of eIzvještavanje messages.

Element order follows ``eIzvjestavanjeSchema.xsd`` exactly. Builders emit
messages *without* the signature — the client (or the mock) appends the
XAdES-B signature via `fiskalhr.core.xades.sign_xades_enveloped`.

The response ``Odgovor`` structure is identical to eFiskalizacija's, so
parsing reuses `fiskalhr.f2.fiskalizacija`'s response models.

``EvidentirajIsporukuZaKojuNijeIzdanERacun`` (deliveries for which no
eRačun was issued) is defined by the schema but not implemented yet.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from lxml import etree

from fiskalhr.f2.fiskalizacija.messages import format_datum_vrijeme
from fiskalhr.f2.fiskalizacija.models import EvidencijaGreska, EvidencijaOdgovor
from fiskalhr.f2.izvjestavanje.models import Naplata, Odbijanje

__all__ = [
    "EIZVJ_NS",
    "build_evidentiraj_naplatu_zahtjev",
    "build_evidentiraj_odbijanje_zahtjev",
    "build_ovlastenja_zahtjev",
    "parse_izvjestavanje_odgovor",
    "parse_ovlastenja_odgovor",
]

EIZVJ_NS = "http://www.porezna-uprava.gov.hr/fin/2024/types/eIzvjestavanje"

_NSMAP = {"eizv": EIZVJ_NS}


def _el(parent: etree._Element, name: str, text: str) -> etree._Element:
    element = etree.SubElement(parent, f"{{{EIZVJ_NS}}}{name}")
    element.text = text
    return element


def _root(name: str, id_zahtjeva: str, datum_vrijeme_slanja: datetime) -> etree._Element:
    root = etree.Element(f"{{{EIZVJ_NS}}}{name}", nsmap=_NSMAP)
    root.set(f"{{{EIZVJ_NS}}}id", id_zahtjeva)
    zaglavlje = etree.SubElement(root, f"{{{EIZVJ_NS}}}Zaglavlje")
    _el(zaglavlje, "datumVrijemeSlanja", format_datum_vrijeme(datum_vrijeme_slanja))
    return root


def build_evidentiraj_naplatu_zahtjev(
    naplate: Sequence[Naplata],
    *,
    id_zahtjeva: str,
    datum_vrijeme_slanja: datetime,
) -> etree._Element:
    """Build an (unsigned) ``EvidentirajNaplatuZahtjev`` (1-100 payments)."""
    if not 1 <= len(naplate) <= 100:
        raise ValueError(f"a message carries 1-100 naplate, got {len(naplate)}")
    root = _root("EvidentirajNaplatuZahtjev", id_zahtjeva, datum_vrijeme_slanja)
    for naplata in naplate:
        n = etree.SubElement(root, f"{{{EIZVJ_NS}}}Naplata")
        _el(n, "brojDokumenta", naplata.broj)
        _el(n, "datumIzdavanja", naplata.datum_izdavanja.isoformat())
        _el(n, "oibPorezniBrojIzdavatelja", naplata.oib_izdavatelja)
        _el(n, "oibPorezniBrojPrimatelja", naplata.oib_primatelja)
        _el(n, "datumNaplate", naplata.datum_naplate.isoformat())
        _el(n, "naplaceniIznos", f"{naplata.naplaceni_iznos:.2f}")
        _el(n, "nacinPlacanja", naplata.nacin_placanja.value)
    return root


def build_evidentiraj_odbijanje_zahtjev(
    odbijanja: Sequence[Odbijanje],
    *,
    id_zahtjeva: str,
    datum_vrijeme_slanja: datetime,
) -> etree._Element:
    """Build an (unsigned) ``EvidentirajOdbijanjeZahtjev`` (1-100 rejections)."""
    if not 1 <= len(odbijanja) <= 100:
        raise ValueError(f"a message carries 1-100 odbijanja, got {len(odbijanja)}")
    root = _root("EvidentirajOdbijanjeZahtjev", id_zahtjeva, datum_vrijeme_slanja)
    for odbijanje in odbijanja:
        o = etree.SubElement(root, f"{{{EIZVJ_NS}}}Odbijanje")
        _el(o, "brojDokumenta", odbijanje.broj)
        _el(o, "datumIzdavanja", odbijanje.datum_izdavanja.isoformat())
        _el(o, "oibPorezniBrojIzdavatelja", odbijanje.oib_izdavatelja)
        _el(o, "oibPorezniBrojPrimatelja", odbijanje.oib_primatelja)
        _el(o, "datumOdbijanja", odbijanje.datum_odbijanja.isoformat())
        _el(o, "vrstaRazlogaOdbijanja", odbijanje.vrsta_razloga.value)
        _el(o, "razlogOdbijanja", odbijanje.razlog)
    return root


def build_ovlastenja_zahtjev(
    oib: str,
    *,
    id_zahtjeva: str,
    datum_vrijeme_slanja: datetime,
) -> etree._Element:
    """Build an (unsigned) ``OvlastenjaFiskalizacijeZahtjev``.

    Asks which OIBs the given taxpayer is authorised to report for.
    """
    root = _root("OvlastenjaFiskalizacijeZahtjev", id_zahtjeva, datum_vrijeme_slanja)
    _el(root, "oib", oib)
    return root


def parse_izvjestavanje_odgovor(element: etree._Element) -> EvidencijaOdgovor:
    """Parse an ``EvidentirajNaplatuOdgovor`` / ``EvidentirajOdbijanjeOdgovor``."""
    expected = (
        f"{{{EIZVJ_NS}}}EvidentirajNaplatuOdgovor",
        f"{{{EIZVJ_NS}}}EvidentirajOdbijanjeOdgovor",
        f"{{{EIZVJ_NS}}}EvidentirajIsporukuZaKojuNijeIzdanERacunOdgovor",
    )
    if element.tag not in expected:
        raise ValueError(f"expected an eIzvjestavanje odgovor, got {element.tag}")

    def text(path: str) -> str | None:
        found = element.find(path, namespaces={"e": EIZVJ_NS})
        return found.text if found is not None else None

    id_zahtjeva = text("e:Odgovor/e:idZahtjeva")
    prihvacen = text("e:Odgovor/e:prihvacenZahtjev")
    if id_zahtjeva is None or prihvacen is None:
        raise ValueError("response lacks Odgovor/idZahtjeva or prihvacenZahtjev")

    greska = None
    if element.find("e:Odgovor/e:greska", namespaces={"e": EIZVJ_NS}) is not None:
        sifra = text("e:Odgovor/e:greska/e:sifra")
        redni = text("e:Odgovor/e:greska/e:redniBrojZapisa")
        opis = text("e:Odgovor/e:greska/e:opis")
        if sifra is None or redni is None or opis is None:
            raise ValueError("response greska lacks sifra, redniBrojZapisa, or opis")
        greska = EvidencijaGreska(sifra=sifra, redni_broj_zapisa=int(redni), opis=opis)

    return EvidencijaOdgovor(
        id_zahtjeva=id_zahtjeva,
        prihvacen=prihvacen in ("true", "1"),
        greska=greska,
    )


def parse_ovlastenja_odgovor(element: etree._Element) -> tuple[str, ...]:
    """Parse an ``OvlastenjaFiskalizacijeOdgovor`` into the authorised OIBs."""
    expected = f"{{{EIZVJ_NS}}}OvlastenjaFiskalizacijeOdgovor"
    if element.tag != expected:
        raise ValueError(f"expected {expected}, got {element.tag}")
    return tuple(
        el.text for el in element.findall(f"{{{EIZVJ_NS}}}ovlasteniOib") if el.text is not None
    )
