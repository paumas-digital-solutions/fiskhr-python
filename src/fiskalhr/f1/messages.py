"""XML serialisation of F1 messages (FiskalizacijaSchema.xsd v1.10).

Builds ``RacunZahtjev`` request documents and parses ``RacunOdgovor``
responses. Element names and order come verbatim from the schema's
``<sequence>`` definitions — tests validate every built document against the
vendored XSD, so a drift here fails loudly.

Signing is not done here: `fiskalhr.core.xmldsig.sign_enveloped` signs the
built document (its root carries ``Id="RacunZahtjev"`` for the signature
reference), and the client layer orchestrates build → sign → send → verify.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from lxml import etree

from fiskalhr.core.errors import FiskalizacijaError
from fiskalhr.f1.models import Greska, Naknada, Porez, PorezOstalo, Racun, RacunOdgovor
from fiskalhr.f1.zki import format_iznos

__all__ = [
    "F73_NS",
    "build_echo_request",
    "build_racun_zahtjev",
    "parse_echo_response",
    "parse_racun_odgovor",
]

F73_NS = "http://www.apis-it.hr/fin/2012/types/f73"
_NSMAP = {"tns": F73_NS}

DATUM_VRIJEME_FORMAT = "%d.%m.%YT%H:%M:%S"
"""``DatumVrijemeType`` — note the ``T`` separator, unlike the ZKI format."""


def _tag(name: str) -> str:
    return f"{{{F73_NS}}}{name}"


def _el(parent: etree._Element, name: str, text: str | None = None) -> etree._Element:
    element = etree.SubElement(parent, _tag(name))
    if text is not None:
        element.text = text
    return element


def _bool(value: bool) -> str:
    return "true" if value else "false"


def _porez_list(parent: etree._Element, name: str, porezi: tuple[Porez, ...]) -> None:
    wrapper = _el(parent, name)
    for porez in porezi:
        element = _el(wrapper, "Porez")
        if isinstance(porez, PorezOstalo):
            _el(element, "Naziv", porez.naziv)
        _el(element, "Stopa", format_iznos(porez.stopa))
        _el(element, "Osnovica", format_iznos(porez.osnovica))
        _el(element, "Iznos", format_iznos(porez.iznos))


def _naknade(parent: etree._Element, naknade: tuple[Naknada, ...]) -> None:
    wrapper = _el(parent, "Naknade")
    for naknada in naknade:
        element = _el(wrapper, "Naknada")
        _el(element, "NazivN", naknada.naziv)
        _el(element, "IznosN", format_iznos(naknada.iznos))


def build_racun_zahtjev(
    racun: Racun,
    zast_kod: str,
    *,
    id_poruke: uuid.UUID | None = None,
    datum_vrijeme: datetime | None = None,
) -> etree._Element:
    """Build an (unsigned) ``RacunZahtjev`` document.

    Args:
        racun: The receipt data.
        zast_kod: The ZKI for this receipt (`fiskalhr.f1.zki.izracunaj_zki`),
            computed by the caller so it exists even if this message is never
            sent — the receipt must print it regardless.
        id_poruke: Message UUID (``IdPoruke``); generated if omitted.
        datum_vrijeme: Message timestamp (``DatumVrijeme``, local Croatian
            time); defaults to the receipt's ``dat_vrijeme``. Pass explicitly
            for late submission (naknadna dostava), where send time and issue
            time legitimately differ.

    Returns:
        The root element, carrying ``Id="RacunZahtjev"`` ready for signing.
    """
    root = etree.Element(_tag("RacunZahtjev"), attrib={"Id": "RacunZahtjev"}, nsmap=_NSMAP)

    zaglavlje = _el(root, "Zaglavlje")
    _el(zaglavlje, "IdPoruke", str(id_poruke if id_poruke is not None else uuid.uuid4()))
    message_time = datum_vrijeme if datum_vrijeme is not None else racun.dat_vrijeme
    _el(zaglavlje, "DatumVrijeme", message_time.strftime(DATUM_VRIJEME_FORMAT))

    element = _el(root, "Racun")
    _el(element, "Oib", racun.oib)
    _el(element, "USustPdv", _bool(racun.u_sust_pdv))
    _el(element, "DatVrijeme", racun.dat_vrijeme.strftime(DATUM_VRIJEME_FORMAT))
    _el(element, "OznSlijed", racun.ozn_slijed.value)

    br_rac = _el(element, "BrRac")
    _el(br_rac, "BrOznRac", racun.br_rac.br_ozn_rac)
    _el(br_rac, "OznPosPr", racun.br_rac.ozn_pos_pr)
    _el(br_rac, "OznNapUr", racun.br_rac.ozn_nap_ur)

    if racun.pdv is not None:
        _porez_list(element, "Pdv", racun.pdv)
    if racun.pnp is not None:
        _porez_list(element, "Pnp", racun.pnp)
    if racun.ostali_por is not None:
        _porez_list(element, "OstaliPor", racun.ostali_por)
    if racun.iznos_oslob_pdv is not None:
        _el(element, "IznosOslobPdv", format_iznos(racun.iznos_oslob_pdv))
    if racun.iznos_marza is not None:
        _el(element, "IznosMarza", format_iznos(racun.iznos_marza))
    if racun.iznos_ne_podl_opor is not None:
        _el(element, "IznosNePodlOpor", format_iznos(racun.iznos_ne_podl_opor))
    if racun.naknade is not None:
        _naknade(element, racun.naknade)

    _el(element, "IznosUkupno", format_iznos(racun.iznos_ukupno))
    _el(element, "NacinPlac", racun.nacin_plac.value)
    _el(element, "OibOper", racun.oib_oper)
    _el(element, "ZastKod", zast_kod)
    _el(element, "NakDost", _bool(racun.nak_dost))
    if racun.paragon_br_rac is not None:
        _el(element, "ParagonBrRac", racun.paragon_br_rac)
    if racun.spec_namj is not None:
        _el(element, "SpecNamj", racun.spec_namj)
    if racun.oib_primatelja_racuna is not None:
        _el(element, "OibPrimateljaRacuna", racun.oib_primatelja_racuna)

    return root


def build_echo_request(text: str) -> etree._Element:
    """Build an ``EchoRequest`` — the unsigned connectivity-test message."""
    root = etree.Element(_tag("EchoRequest"), nsmap=_NSMAP)
    root.text = text
    return root


def parse_echo_response(xml: bytes | etree._Element) -> str:
    """Parse an ``EchoResponse`` and return its text."""
    root = etree.fromstring(xml) if isinstance(xml, bytes) else xml
    if root.tag != _tag("EchoResponse"):
        raise FiskalizacijaError(f"expected EchoResponse, got {root.tag!r}")
    return root.text or ""


def parse_racun_odgovor(xml: bytes | etree._Element) -> RacunOdgovor:
    """Parse a ``RacunOdgovor`` response document.

    Signature verification is the caller's job (`core.xmldsig`), done
    *before* parsing is trusted.

    Raises:
        FiskalizacijaError: If the document is not a well-formed
            ``RacunOdgovor``.
    """
    if isinstance(xml, bytes):
        try:
            root = etree.fromstring(xml)
        except etree.XMLSyntaxError as exc:
            raise FiskalizacijaError(f"response is not well-formed XML: {exc}") from exc
    else:
        root = xml

    if root.tag != _tag("RacunOdgovor"):
        raise FiskalizacijaError(f"expected RacunOdgovor, got {root.tag!r}")

    zaglavlje = root.find(_tag("Zaglavlje"))
    if zaglavlje is None:
        raise FiskalizacijaError("RacunOdgovor has no Zaglavlje")
    datum_vrijeme_el = zaglavlje.find(_tag("DatumVrijeme"))
    if datum_vrijeme_el is None or not datum_vrijeme_el.text:
        raise FiskalizacijaError("RacunOdgovor has no Zaglavlje/DatumVrijeme")
    id_poruke_el = zaglavlje.find(_tag("IdPoruke"))

    jir_el = root.find(_tag("Jir"))
    greske = tuple(
        Greska(
            sifra=(greska.findtext(_tag("SifraGreske")) or "").strip(),
            poruka=(greska.findtext(_tag("PorukaGreske")) or "").strip(),
        )
        for greska in root.findall(f"{_tag('Greske')}/{_tag('Greska')}")
    )

    return RacunOdgovor(
        id_poruke=id_poruke_el.text if id_poruke_el is not None else None,
        datum_vrijeme=datetime.strptime(datum_vrijeme_el.text, DATUM_VRIJEME_FORMAT),
        jir=jir_el.text if jir_el is not None else None,
        greske=greske,
    )
