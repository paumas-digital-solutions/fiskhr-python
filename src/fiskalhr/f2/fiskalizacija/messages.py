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


def _el(parent: etree._Element, name: str, text: str, ns: str = EFISK_NS) -> etree._Element:
    element = etree.SubElement(parent, f"{{{ns}}}{name}")
    element.text = text
    return element


def _opt(parent: etree._Element, name: str, text: str | None, ns: str = EFISK_NS) -> None:
    if text is not None:
        _el(parent, name, text, ns)


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


def _eracun_element(
    e: EvidencijaERacun,
    ns: str = EFISK_NS,
    *,
    root_name: str = "ERacun",
    valuta_name: str = "valutaERacuna",
    prethodni_name: str = "PrethodniERacun",
    stavka_name: str = "StavkaERacuna",
) -> etree._Element:
    """Serialise the invoice digest. The eIzvještavanje ``Racun`` type is
    field-identical to eFiskalizacija's ``ERacun`` — only the namespace and
    these element names differ, hence the parameters."""
    el = etree.Element(f"{{{ns}}}{root_name}", nsmap={"tns": ns})
    _el(el, "brojDokumenta", e.broj, ns)
    _el(el, "datumIzdavanja", e.datum_izdavanja.isoformat(), ns)
    _el(el, "vrstaDokumenta", e.vrsta_dokumenta, ns)
    _el(el, valuta_name, e.valuta, ns)
    if e.datum_dospijeca is not None:
        _el(el, "datumDospijecaPlacanja", e.datum_dospijeca.isoformat(), ns)
    _el(el, "vrstaPoslovnogProcesa", e.vrsta_poslovnog_procesa, ns)
    _opt(el, "referencaNaUgovor", e.referenca_na_ugovor, ns)
    if e.datum_isporuke is not None:
        _el(el, "datumIsporuke", e.datum_isporuke.isoformat(), ns)
    for prethodni in e.prethodni_eracuni:
        p = etree.SubElement(el, f"{{{ns}}}{prethodni_name}")
        _el(p, "brojDokumenta", prethodni.broj, ns)
        _el(p, "datumIzdavanja", prethodni.datum_izdavanja.isoformat(), ns)

    izdavatelj = etree.SubElement(el, f"{{{ns}}}Izdavatelj")
    _el(izdavatelj, "ime", e.izdavatelj.ime, ns)
    _el(izdavatelj, "oibPorezniBroj", e.izdavatelj.oib, ns)
    _el(izdavatelj, "oibOperatera", e.izdavatelj.oib_operatera, ns)

    primatelj = etree.SubElement(el, f"{{{ns}}}Primatelj")
    _el(primatelj, "ime", e.primatelj.ime, ns)
    _el(primatelj, "oibPorezniBroj", e.primatelj.oib, ns)

    for prijenos in e.prijenosi_sredstava:
        ps = etree.SubElement(el, f"{{{ns}}}PrijenosSredstava")
        _el(ps, "identifikatorRacunaZaPlacanje", prijenos.iban, ns)
        _opt(ps, "nazivRacunaZaPlacanje", prijenos.naziv_racuna, ns)
        _opt(ps, "identifikatorPruzateljaPlatnihUsluga", prijenos.pruzatelj_platnih_usluga, ns)

    ukupno = etree.SubElement(el, f"{{{ns}}}DokumentUkupanIznos")
    _el(ukupno, "neto", _iznos(e.ukupan_iznos.neto), ns)
    if e.ukupan_iznos.popust is not None:
        _el(ukupno, "popust", _iznos(e.ukupan_iznos.popust), ns)
    if e.ukupan_iznos.trosak is not None:
        _el(ukupno, "trosak", _iznos(e.ukupan_iznos.trosak), ns)
    _el(ukupno, "iznosBezPdv", _iznos(e.ukupan_iznos.iznos_bez_pdv), ns)
    _el(ukupno, "pdv", _iznos(e.ukupan_iznos.pdv), ns)
    _el(ukupno, "iznosSPdv", _iznos(e.ukupan_iznos.iznos_s_pdv), ns)
    if e.ukupan_iznos.placeni_iznos is not None:
        _el(ukupno, "placeniIznos", _iznos(e.ukupan_iznos.placeni_iznos), ns)
    _el(ukupno, "iznosKojiDospijevaZaPlacanje", _iznos(e.ukupan_iznos.iznos_koji_dospijeva), ns)

    for raspodjela in e.raspodjele_pdv:
        r = etree.SubElement(el, f"{{{ns}}}RaspodjelaPdv")
        _el(r, "kategorijaPdv", raspodjela.kategorija.value, ns)
        _el(r, "oporeziviIznos", _iznos(raspodjela.osnovica), ns)
        _el(r, "iznosPoreza", _iznos(raspodjela.iznos), ns)
        if raspodjela.stopa is not None:
            _el(r, "stopa", _broj(raspodjela.stopa), ns)
        _opt(r, "razlogOslobodenja", raspodjela.razlog_oslobodjenja_kod, ns)
        _opt(r, "tekstRazlogaOslobodenja", raspodjela.razlog_oslobodjenja, ns)
        _opt(r, "hrOznakaKategorijaPdv", raspodjela.hr_oznaka, ns)

    for popust in e.popusti:
        pop = etree.SubElement(el, f"{{{ns}}}DokumentPopust")
        _el(pop, "iznosPopust", _iznos(popust.iznos), ns)
        _el(pop, "kategorijaPdv", popust.kategorija.value, ns)
        if popust.stopa is not None:
            _el(pop, "stopaPdv", _broj(popust.stopa), ns)
        _opt(pop, "tekstRazlogaPopusta", popust.razlog, ns)
        _opt(pop, "razlogPopusta", popust.razlog_kod, ns)

    for trosak in e.troskovi:
        tr = etree.SubElement(el, f"{{{ns}}}DokumentTrosak")
        _el(tr, "iznosTrosak", _iznos(trosak.iznos), ns)
        _el(tr, "kategorijaPdv", trosak.kategorija.value, ns)
        _opt(tr, "hrOznakaPorezneKategorije", trosak.hr_oznaka, ns)
        if trosak.stopa is not None:
            _el(tr, "stopaPdv", _broj(trosak.stopa), ns)
        _opt(tr, "tekstRazlogaOslobodenjaPdv", trosak.razlog_oslobodjenja, ns)
        _opt(tr, "razlogOslobodenjaPdv", trosak.razlog_oslobodjenja_kod, ns)

    for stavka in e.stavke:
        s = etree.SubElement(el, f"{{{ns}}}{stavka_name}")
        _el(s, "kolicina", _broj(stavka.kolicina), ns)
        _el(s, "jedinicaMjere", stavka.jedinica, ns)
        _el(s, "neto", _iznos(stavka.neto), ns)
        _el(s, "artiklNetoCijena", _broj(stavka.cijena), ns)
        if stavka.bruto_cijena is not None:
            _el(s, "artiklBrutoCijena", _broj(stavka.bruto_cijena), ns)
        if stavka.osnovna_kolicina is not None:
            _el(s, "artiklOsnovnaKolicina", _broj(stavka.osnovna_kolicina), ns)
        _opt(s, "artiklJedinicaMjereZaOsnovnuKolicinu", stavka.jedinica_osnovne_kolicine, ns)
        _el(s, "artiklKategorijaPdv", stavka.kategorija.value, ns)
        if stavka.stopa is not None:
            _el(s, "artiklStopaPdv", _broj(stavka.stopa), ns)
        _el(s, "artiklNaziv", stavka.naziv, ns)
        _opt(s, "artiklOpis", stavka.opis, ns)
        _opt(s, "artiklHrOznakaKategorijaPdv", stavka.hr_oznaka, ns)
        if stavka.kpd is not None:
            k = etree.SubElement(s, f"{{{ns}}}ArtiklIdentifikatorKlasifikacija")
            _el(k, "identifikatorKlasifikacije", stavka.kpd, ns)
            _el(k, "identifikatorSheme", "CG", ns)

    _el(el, "indikatorKopije", "true" if e.indikator_kopije else "false", ns)
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
