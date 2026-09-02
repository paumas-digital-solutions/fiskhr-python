"""Reading a received eRačun into a reportable digest.

The corpus is the whole point of these tests: an incoming invoice is
whatever a supplier sent, so the parser is exercised against all twenty
official examples — advance invoices, credit notes, an issuer outside the
VAT system, document-level allowances and charges — rather than against
documents this library produced itself.

One substitution is needed to do that. The official examples use
``12345678901`` as the supplier OIB, which fails its ISO 7064 checksum (the
Tax Administration's samples are illustrative, not valid records), and the
reporting models validate a received invoice as strictly as a built one.
The fixtures below swap it for a checksum-valid OIB and leave everything
else byte-for-byte as shipped.
"""

from __future__ import annotations

import pathlib
from decimal import Decimal

import pytest
from lxml import etree

from fiskalhr.f2.fiskalizacija import EvidencijaERacun
from fiskalhr.f2.fiskalizacija.parse import ERacunParseError, evidencija_iz_xml
from fiskalhr.f2.ubl.models import KategorijaPdv

CORPUS = pathlib.Path(__file__).parent / "conformance" / "f2" / "eracuni"

DUMMY_OIB = b"12345678901"
VALID_OIB = b"12345678903"


def _example(name: str) -> bytes:
    return (CORPUS / name).read_bytes().replace(DUMMY_OIB, VALID_OIB)


def _names() -> list[str]:
    return sorted(path.name for path in CORPUS.glob("*.xml"))


@pytest.mark.parametrize("name", _names())
def test_every_official_example_parses(name: str) -> None:
    evidencija = evidencija_iz_xml(_example(name))

    assert isinstance(evidencija, EvidencijaERacun)
    assert evidencija.broj
    assert evidencija.stavke
    assert evidencija.raspodjele_pdv


def test_reads_the_invoice_rather_than_recomputing_it() -> None:
    """A received invoice's own totals are reported, not re-derived —
    a discrepancy is the sender's, and must stay visible."""
    evidencija = evidencija_iz_xml(_example("eRacun-PDV25.xml"))

    assert evidencija.ukupan_iznos.neto == Decimal("100.00")
    assert evidencija.ukupan_iznos.pdv == Decimal("25.00")
    assert evidencija.ukupan_iznos.iznos_s_pdv == Decimal("125.00")
    assert evidencija.ukupan_iznos.iznos_koji_dospijeva == Decimal("125.00")


def test_parses_parties_and_the_operator() -> None:
    evidencija = evidencija_iz_xml(_example("eRacun-PDV25.xml"))

    assert evidencija.izdavatelj.oib == "12345678903"
    assert evidencija.izdavatelj.ime == "TVRTKA A d.o.o."
    assert evidencija.izdavatelj.oib_operatera == "12345678903"
    assert evidencija.primatelj.oib == "11111111119"


def test_parses_an_issuer_outside_the_vat_system() -> None:
    """``Nije u sustavu PDV`` carries a bare OIB under TaxScheme FRE, not
    the HR-prefixed VAT identifier the builder always emits."""
    evidencija = evidencija_iz_xml(_example("eRacun-Nije_u_sustavu_PDV.xml"))

    assert evidencija.izdavatelj.oib == "12345678903"
    assert evidencija.raspodjele_pdv[0].kategorija is not KategorijaPdv.STANDARDNA


def test_parses_an_advance_invoice_prepaid_amount() -> None:
    """BT-113 — a construct the builder cannot yet produce, which is
    precisely why a received invoice is parsed into the digest."""
    evidencija = evidencija_iz_xml(_example("Finalni_racun-predujam.xml"))

    assert evidencija.ukupan_iznos.placeni_iznos == Decimal("500.00")
    assert evidencija.prethodni_eracuni  # references the advance invoice


def test_parses_a_credit_note() -> None:
    evidencija = evidencija_iz_xml(_example("Odobrenje.xml"))

    assert evidencija.vrsta_dokumenta == "381"
    assert evidencija.stavke  # CreditNoteLine, not InvoiceLine


def test_parses_document_level_allowances_and_charges() -> None:
    evidencija = evidencija_iz_xml(_example("eRacun-PDV-NEOP-PP-trosak.xml"))

    assert evidencija.troskovi
    assert evidencija.troskovi[0].iznos > 0


def test_parses_line_details() -> None:
    evidencija = evidencija_iz_xml(_example("eRacun-PDV25.xml"))
    stavka = evidencija.stavke[0]

    assert stavka.naziv == "Proizvod"
    assert stavka.kpd == "62.20.20"
    assert stavka.jedinica == "H87"
    assert stavka.kolicina == Decimal("1.000")
    assert stavka.neto == Decimal("100.00")
    assert stavka.kategorija is KategorijaPdv.STANDARDNA
    assert stavka.stopa == Decimal("25")
    assert stavka.hr_oznaka == "HR:PDV25"


def test_an_invalid_oib_is_reported_readably() -> None:
    """Unpatched, the official samples carry a checksum-invalid OIB. The
    error has to name the field, not dump a pydantic traceback."""
    unpatched = (CORPUS / "eRacun-PDV25.xml").read_bytes()

    with pytest.raises(ERacunParseError, match="oib") as raised:
        evidencija_iz_xml(unpatched)

    assert "checksum" in str(raised.value)


def test_rejects_a_document_that_is_not_an_eracun() -> None:
    with pytest.raises(ERacunParseError, match="LegalMonetaryTotal"):
        evidencija_iz_xml(
            b"<Invoice xmlns='urn:oasis:names:specification:ubl:schema:xsd:Invoice-2'/>"
        )


def test_rejects_malformed_xml() -> None:
    with pytest.raises(ERacunParseError, match="well-formed"):
        evidencija_iz_xml(b"<broken")


def test_accepts_an_element_as_well_as_bytes() -> None:
    element = etree.fromstring(_example("eRacun-PDV25.xml"))

    assert evidencija_iz_xml(element).broj == evidencija_iz_xml(_example("eRacun-PDV25.xml")).broj


def test_parsing_agrees_with_deriving_the_digest_from_the_model() -> None:
    """The digest of an invoice must not depend on which side it is seen
    from: deriving it from the model this library built and parsing it back
    out of that model's own XML have to produce the same report."""
    from datetime import date, time

    from fiskalhr.f2.ubl import ERacunBuilder, to_xml

    racun = (
        ERacunBuilder()
        .izdavatelj(
            oib="12345678903",
            naziv="Tvrtka d.o.o.",
            ulica="Ulica 1",
            grad="Zagreb",
            postanski_broj="10000",
        )
        .primatelj(
            oib="00000000001",
            naziv="Kupac d.o.o.",
            ulica="Ulica 2",
            grad="Rijeka",
            postanski_broj="51000",
        )
        .operater(oib="12345678903", oznaka="Operater1")
        .broj("2026-42-P1-1")
        .datum_izdavanja(date(2026, 8, 13), time(12, 0))
        .dospijece(date(2026, 9, 12))
        .placanje(iban="HR1210010051863000160", poziv_na_broj="HR00 42")
        .stavka(naziv="Licenca", kpd="62.20.20", kolicina=2, cijena="50.00", pdv_stopa=25)
        .trosak(iznos="10.00", razlog="Dostava", pdv_stopa=25)
        .popust(iznos="5.00", razlog="Rabat", pdv_stopa=25)
        .build()
    )

    derived = EvidencijaERacun.from_eracuna(racun)
    parsed = evidencija_iz_xml(etree.tostring(to_xml(racun)))

    assert parsed.model_dump() == derived.model_dump()
