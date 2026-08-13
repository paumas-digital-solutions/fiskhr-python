"""XSD-validation and shape tests for the follow-up message types:
napojnica, payment-method change, receipt-data change, and provjera.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest
from lxml import etree

from fiskhr.core.certs import Certificate
from fiskhr.core.xmldsig import sign_enveloped
from fiskhr.f1.messages import (
    F73_NS,
    build_napojnica_zahtjev,
    build_promijeni_nac_plac_zahtjev,
    build_promijeni_podatke_racuna_zahtjev,
    build_provjera_zahtjev,
    parse_promjena_odgovor,
)
from fiskhr.f1.models import (
    BrojRacuna,
    NacinPlacanja,
    Napojnica,
    OznakaSlijednosti,
    Racun,
)
from fiskhr.f1.service import schema_dir
from tests.conftest import TEST_OIB, make_rsa_key, make_self_signed_cert

NS = f"{{{F73_NS}}}"


@pytest.fixture(scope="module")
def xsd() -> etree.XMLSchema:
    return etree.XMLSchema(etree.parse(schema_dir() / "FiskalizacijaSchema.xsd"))


@pytest.fixture(scope="module")
def signer_cert() -> Certificate:
    key = make_rsa_key()
    return Certificate(private_key=key, certificate=make_self_signed_cert(key))


def _racun() -> Racun:
    return Racun(
        oib=TEST_OIB,
        u_sust_pdv=True,
        dat_vrijeme=datetime(2026, 8, 3, 11, 54, 25),
        ozn_slijed=OznakaSlijednosti.POSLOVNI_PROSTOR,
        br_rac=BrojRacuna(br_ozn_rac="1", ozn_pos_pr="POSL1", ozn_nap_ur="12"),
        iznos_ukupno=Decimal("125.00"),
        nacin_plac=NacinPlacanja.KARTICA,
        oib_oper=TEST_OIB,
    )


ZKI = "a1e6b1428f0cc755f0c82aa7a1327e35"  # shape-valid ZKI for schema tests


def _all_zahtjevi() -> list[etree._Element]:
    racun = _racun()
    return [
        build_provjera_zahtjev(racun, ZKI),
        build_napojnica_zahtjev(
            racun, ZKI, Napojnica(iznos=Decimal("2.00"), nacin_placanja=NacinPlacanja.GOTOVINA)
        ),
        build_promijeni_nac_plac_zahtjev(racun, ZKI, NacinPlacanja.TRANSAKCIJSKI_RACUN),
        build_promijeni_podatke_racuna_zahtjev(racun, ZKI, NacinPlacanja.OSTALO, "00000000001"),
    ]


def test_all_zahtjevi_validate_against_official_xsd(xsd: etree.XMLSchema) -> None:
    for zahtjev in _all_zahtjevi():
        xsd.assertValid(zahtjev)


def test_all_signed_zahtjevi_validate_against_official_xsd(
    xsd: etree.XMLSchema, signer_cert: Certificate
) -> None:
    for zahtjev in _all_zahtjevi():
        xsd.assertValid(etree.fromstring(sign_enveloped(zahtjev, signer_cert)))


def test_empty_oib_promjena_is_schema_valid(xsd: etree.XMLSchema) -> None:
    # OibPromjenaType explicitly allows the empty string (clear the OIB).
    zahtjev = build_promijeni_podatke_racuna_zahtjev(_racun(), ZKI, NacinPlacanja.OSTALO, "")
    xsd.assertValid(zahtjev)


def test_napojnica_uses_lowercase_element_names() -> None:
    zahtjev = build_napojnica_zahtjev(
        _racun(), ZKI, Napojnica(iznos=Decimal("2.50"), nacin_placanja=NacinPlacanja.KARTICA)
    )
    napojnica = zahtjev.find(f"{NS}Racun/{NS}Napojnica")
    assert napojnica is not None
    assert napojnica.findtext(f"{NS}iznosNapojnice") == "2.50"
    assert napojnica.findtext(f"{NS}nacinPlacanjaNapojnice") == "K"


def test_change_fields_come_last_in_sequence() -> None:
    zahtjev = build_promijeni_podatke_racuna_zahtjev(
        _racun(), ZKI, NacinPlacanja.GOTOVINA, "00000000001"
    )
    racun_el = zahtjev.find(f"{NS}Racun")
    assert racun_el is not None
    names = [etree.QName(child).localname for child in racun_el]
    assert names[-2:] == ["PromijenjeniNacinPlac", "PromijenjeniOibPrimateljaRacuna"]


def test_parse_promjena_odgovor_success() -> None:
    raw = (
        b'<tns:NapojnicaOdgovor Id="NapojnicaOdgovor"'
        b' xmlns:tns="http://www.apis-it.hr/fin/2012/types/f73">'
        b"<tns:Zaglavlje>"
        b"<tns:IdPoruke>9d1b3a2e-0000-4000-8000-0123456789ab</tns:IdPoruke>"
        b"<tns:DatumVrijeme>03.08.2026T11:54:26</tns:DatumVrijeme>"
        b"</tns:Zaglavlje>"
        b"<tns:PorukaOdgovora>"
        b"<tns:SifraPoruke>p001</tns:SifraPoruke>"
        b"<tns:Poruka>Uspje\xc5\xa1no.</tns:Poruka>"
        b"</tns:PorukaOdgovora>"
        b"</tns:NapojnicaOdgovor>"
    )
    odgovor = parse_promjena_odgovor(raw, expected="NapojnicaOdgovor")
    assert odgovor.ok
    assert odgovor.poruka is not None
    assert odgovor.poruka.sifra == "p001"
