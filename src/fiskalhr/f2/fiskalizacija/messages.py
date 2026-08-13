"""Building and parsing of eFiskalizacija messages.

Element order follows ``eFiskalizacijaSchema.xsd`` exactly. Builders emit
the message *without* the signature — the schema requires one, and the
client (or `fiskalhr.testing.MockEFiskalizacija`) appends it via
`fiskalhr.core.xades.sign_xades_enveloped` before the document goes out.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from lxml import etree

from fiskalhr.f2.fiskalizacija.models import (
    EvidencijaERacun,
    EvidencijaGreska,
    EvidencijaOdgovor,
    VrstaERacuna,
)

__all__ = [
    "EFISK_NS",
    "build_evidentiraj_eracun_zahtjev",
    "format_datum_vrijeme",
    "parse_evidentiraj_eracun_odgovor",
]

EFISK_NS = "http://www.porezna-uprava.gov.hr/fin/2024/types/eFiskalizacija"

_NSMAP = {"efis": EFISK_NS}


def format_datum_vrijeme(value: datetime) -> str:
    """``datumVrijemeSlanja`` format: ISO 8601 with exactly four fractional
    digits (spec ch. 3.1.2.1), e.g. ``2026-08-13T12:00:36.1424``."""
    return f"{value:%Y-%m-%dT%H:%M:%S}.{value.microsecond // 100:04d}"


def _iznos(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):.2f}"


def _broj(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _el(parent: etree._Element, name: str, text: str) -> etree._Element:
    element = etree.SubElement(parent, f"{{{EFISK_NS}}}{name}")
    element.text = text
    return element


def _opt(parent: etree._Element, name: str, text: str | None) -> None:
    if text is not None:
        _el(parent, name, text)


def build_evidentiraj_eracun_zahtjev(
    eracuni: Sequence[EvidencijaERacun],
    *,
    vrsta: VrstaERacuna,
    id_zahtjeva: str,
    datum_vrijeme_slanja: datetime,
) -> etree._Element:
    """Build an (unsigned) ``EvidentirajERacunZahtjev``.

    Args:
        eracuni: 1-100 invoice digests; the schema caps a message at 100.
        vrsta: Whether these are outgoing (issuer reports) or incoming
            (recipient reports) eRačuni.
        id_zahtjeva: Value for the root's ``id`` attribute, referenced by
            the signature. Any non-empty string; the client uses a UUID.
        datum_vrijeme_slanja: Send timestamp (``≥ 2026-01-01`` per schema).
    """
    if not 1 <= len(eracuni) <= 100:
        raise ValueError(f"a message carries 1-100 eRačuni, got {len(eracuni)}")

    root = etree.Element(f"{{{EFISK_NS}}}EvidentirajERacunZahtjev", nsmap=_NSMAP)
    root.set(f"{{{EFISK_NS}}}id", id_zahtjeva)

    zaglavlje = etree.SubElement(root, f"{{{EFISK_NS}}}Zaglavlje")
    _el(zaglavlje, "datumVrijemeSlanja", format_datum_vrijeme(datum_vrijeme_slanja))
    _el(zaglavlje, "vrstaERacuna", vrsta.value)

    for eracun in eracuni:
        root.append(_eracun_element(eracun))
    return root


def _eracun_element(e: EvidencijaERacun) -> etree._Element:
    el = etree.Element(f"{{{EFISK_NS}}}ERacun", nsmap=_NSMAP)
    _el(el, "brojDokumenta", e.broj)
    _el(el, "datumIzdavanja", e.datum_izdavanja.isoformat())
    _el(el, "vrstaDokumenta", e.vrsta_dokumenta)
    _el(el, "valutaERacuna", e.valuta)
    if e.datum_dospijeca is not None:
        _el(el, "datumDospijecaPlacanja", e.datum_dospijeca.isoformat())
    _el(el, "vrstaPoslovnogProcesa", e.vrsta_poslovnog_procesa)
    _opt(el, "referencaNaUgovor", e.referenca_na_ugovor)
    if e.datum_isporuke is not None:
        _el(el, "datumIsporuke", e.datum_isporuke.isoformat())
    for prethodni in e.prethodni_eracuni:
        p = etree.SubElement(el, f"{{{EFISK_NS}}}PrethodniERacun")
        _el(p, "brojDokumenta", prethodni.broj)
        _el(p, "datumIzdavanja", prethodni.datum_izdavanja.isoformat())

    izdavatelj = etree.SubElement(el, f"{{{EFISK_NS}}}Izdavatelj")
    _el(izdavatelj, "ime", e.izdavatelj.ime)
    _el(izdavatelj, "oibPorezniBroj", e.izdavatelj.oib)
    _el(izdavatelj, "oibOperatera", e.izdavatelj.oib_operatera)

    primatelj = etree.SubElement(el, f"{{{EFISK_NS}}}Primatelj")
    _el(primatelj, "ime", e.primatelj.ime)
    _el(primatelj, "oibPorezniBroj", e.primatelj.oib)

    for prijenos in e.prijenosi_sredstava:
        ps = etree.SubElement(el, f"{{{EFISK_NS}}}PrijenosSredstava")
        _el(ps, "identifikatorRacunaZaPlacanje", prijenos.iban)
        _opt(ps, "nazivRacunaZaPlacanje", prijenos.naziv_racuna)
        _opt(ps, "identifikatorPruzateljaPlatnihUsluga", prijenos.pruzatelj_platnih_usluga)

    ukupno = etree.SubElement(el, f"{{{EFISK_NS}}}DokumentUkupanIznos")
    _el(ukupno, "neto", _iznos(e.ukupan_iznos.neto))
    if e.ukupan_iznos.popust is not None:
        _el(ukupno, "popust", _iznos(e.ukupan_iznos.popust))
    if e.ukupan_iznos.trosak is not None:
        _el(ukupno, "trosak", _iznos(e.ukupan_iznos.trosak))
    _el(ukupno, "iznosBezPdv", _iznos(e.ukupan_iznos.iznos_bez_pdv))
    _el(ukupno, "pdv", _iznos(e.ukupan_iznos.pdv))
    _el(ukupno, "iznosSPdv", _iznos(e.ukupan_iznos.iznos_s_pdv))
    if e.ukupan_iznos.placeni_iznos is not None:
        _el(ukupno, "placeniIznos", _iznos(e.ukupan_iznos.placeni_iznos))
    _el(ukupno, "iznosKojiDospijevaZaPlacanje", _iznos(e.ukupan_iznos.iznos_koji_dospijeva))

    for raspodjela in e.raspodjele_pdv:
        r = etree.SubElement(el, f"{{{EFISK_NS}}}RaspodjelaPdv")
        _el(r, "kategorijaPdv", raspodjela.kategorija.value)
        _el(r, "oporeziviIznos", _iznos(raspodjela.osnovica))
        _el(r, "iznosPoreza", _iznos(raspodjela.iznos))
        if raspodjela.stopa is not None:
            _el(r, "stopa", _broj(raspodjela.stopa))
        _opt(r, "razlogOslobodenja", raspodjela.razlog_oslobodjenja_kod)
        _opt(r, "tekstRazlogaOslobodenja", raspodjela.razlog_oslobodjenja)
        _opt(r, "hrOznakaKategorijaPdv", raspodjela.hr_oznaka)

    for stavka in e.stavke:
        s = etree.SubElement(el, f"{{{EFISK_NS}}}StavkaERacuna")
        _el(s, "kolicina", _broj(stavka.kolicina))
        _el(s, "jedinicaMjere", stavka.jedinica)
        _el(s, "neto", _iznos(stavka.neto))
        _el(s, "artiklNetoCijena", _broj(stavka.cijena))
        if stavka.bruto_cijena is not None:
            _el(s, "artiklBrutoCijena", _broj(stavka.bruto_cijena))
        if stavka.osnovna_kolicina is not None:
            _el(s, "artiklOsnovnaKolicina", _broj(stavka.osnovna_kolicina))
        _opt(s, "artiklJedinicaMjereZaOsnovnuKolicinu", stavka.jedinica_osnovne_kolicine)
        _el(s, "artiklKategorijaPdv", stavka.kategorija.value)
        if stavka.stopa is not None:
            _el(s, "artiklStopaPdv", _broj(stavka.stopa))
        _el(s, "artiklNaziv", stavka.naziv)
        _opt(s, "artiklOpis", stavka.opis)
        _opt(s, "artiklHrOznakaKategorijaPdv", stavka.hr_oznaka)
        if stavka.kpd is not None:
            k = etree.SubElement(s, f"{{{EFISK_NS}}}ArtiklIdentifikatorKlasifikacija")
            _el(k, "identifikatorKlasifikacije", stavka.kpd)
            _el(k, "identifikatorSheme", "CG")

    _el(el, "indikatorKopije", "true" if e.indikator_kopije else "false")
    return el


def parse_evidentiraj_eracun_odgovor(element: etree._Element) -> EvidencijaOdgovor:
    """Parse an ``EvidentirajERacunOdgovor`` into `EvidencijaOdgovor`."""
    expected = f"{{{EFISK_NS}}}EvidentirajERacunOdgovor"
    if element.tag != expected:
        raise ValueError(f"expected {expected}, got {element.tag}")

    def text(path: str) -> str | None:
        found = element.find(path, namespaces={"e": EFISK_NS})
        return found.text if found is not None else None

    id_zahtjeva = text("e:Odgovor/e:idZahtjeva")
    prihvacen = text("e:Odgovor/e:prihvacenZahtjev")
    if id_zahtjeva is None or prihvacen is None:
        raise ValueError("response lacks Odgovor/idZahtjeva or prihvacenZahtjev")

    greska = None
    greska_el = element.find("e:Odgovor/e:greska", namespaces={"e": EFISK_NS})
    if greska_el is not None:
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
