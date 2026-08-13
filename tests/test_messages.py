from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

import pytest
from lxml import etree

from fiskalhr.core.certs import Certificate
from fiskalhr.core.errors import FiskalizacijaError
from fiskalhr.core.xmldsig import sign_enveloped
from fiskalhr.f1.messages import F73_NS, build_racun_zahtjev, parse_racun_odgovor
from fiskalhr.f1.models import (
    BrojRacuna,
    NacinPlacanja,
    Naknada,
    OznakaSlijednosti,
    Porez,
    PorezOstalo,
    Racun,
)
from fiskalhr.f1.service import schema_dir
from fiskalhr.f1.zki import izracunaj_zki
from tests.conftest import TEST_OIB, make_rsa_key, make_self_signed_cert


@pytest.fixture(scope="module")
def xsd() -> etree.XMLSchema:
    # The official schema; xmldsig-core-schema.xsd resolves relatively.
    return etree.XMLSchema(etree.parse(schema_dir() / "FiskalizacijaSchema.xsd"))


@pytest.fixture(scope="module")
def signer_cert() -> Certificate:
    key = make_rsa_key()
    return Certificate(private_key=key, certificate=make_self_signed_cert(key))


def _minimal_racun() -> Racun:
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


def _full_racun() -> Racun:
    return _minimal_racun().model_copy(
        update={
            "pdv": (
                Porez(stopa=Decimal("25.00"), osnovica=Decimal("100.00"), iznos=Decimal("25.00")),
            ),
            "pnp": (
                Porez(stopa=Decimal("3.00"), osnovica=Decimal("100.00"), iznos=Decimal("3.00")),
            ),
            "ostali_por": (
                PorezOstalo(
                    naziv="Porez na luksuz",
                    stopa=Decimal("15.00"),
                    osnovica=Decimal("100.00"),
                    iznos=Decimal("15.00"),
                ),
            ),
            "iznos_oslob_pdv": Decimal("10.00"),
            "iznos_marza": Decimal("5.00"),
            "iznos_ne_podl_opor": Decimal("2.00"),
            "naknade": (Naknada(naziv="Povratna naknada", iznos=Decimal("0.50")),),
            "nak_dost": True,
            "paragon_br_rac": "123/2026",
            "spec_namj": "test",
            "oib_primatelja_racuna": "00000000001",
        }
    )


def _zki(racun: Racun, cert: Certificate) -> str:
    return izracunaj_zki(
        cert.private_key,
        oib=racun.oib,
        datum_vrijeme=racun.dat_vrijeme,
        br_ozn_rac=racun.br_rac.br_ozn_rac,
        ozn_pos_pr=racun.br_rac.ozn_pos_pr,
        ozn_nap_ur=racun.br_rac.ozn_nap_ur,
        ukupan_iznos=racun.iznos_ukupno,
    )


@pytest.mark.parametrize("racun_factory", [_minimal_racun, _full_racun])
def test_built_zahtjev_validates_against_official_xsd(
    xsd: etree.XMLSchema,
    signer_cert: Certificate,
    racun_factory: object,
) -> None:
    racun = racun_factory()  # type: ignore[operator]
    root = build_racun_zahtjev(racun, _zki(racun, signer_cert))

    xsd.assertValid(root)


def test_signed_zahtjev_validates_against_official_xsd(
    xsd: etree.XMLSchema, signer_cert: Certificate
) -> None:
    # The ds:Signature element must land where the schema expects it.
    racun = _full_racun()
    root = build_racun_zahtjev(racun, _zki(racun, signer_cert))
    signed = sign_enveloped(root, signer_cert)

    xsd.assertValid(etree.fromstring(signed))


def test_zahtjev_field_values_and_order(signer_cert: Certificate) -> None:
    racun = _minimal_racun()
    message_id = uuid.uuid4()
    root = build_racun_zahtjev(racun, _zki(racun, signer_cert), id_poruke=message_id)

    def text(path: str) -> str | None:
        return root.findtext("/".join(f"{{{F73_NS}}}{part}" for part in path.split("/")))

    assert root.get("Id") == "RacunZahtjev"
    assert text("Zaglavlje/IdPoruke") == str(message_id)
    assert text("Zaglavlje/DatumVrijeme") == "03.08.2026T11:54:25"
    assert text("Racun/Oib") == TEST_OIB
    assert text("Racun/USustPdv") == "true"
    assert text("Racun/DatVrijeme") == "03.08.2026T11:54:25"
    assert text("Racun/OznSlijed") == "P"
    assert text("Racun/BrRac/BrOznRac") == "1"
    assert text("Racun/IznosUkupno") == "125.00"
    assert text("Racun/NacinPlac") == "K"
    assert text("Racun/NakDost") == "false"

    racun_el = root.find(f"{{{F73_NS}}}Racun")
    assert racun_el is not None
    child_names = [etree.QName(child).localname for child in racun_el]
    assert child_names == [
        "Oib",
        "USustPdv",
        "DatVrijeme",
        "OznSlijed",
        "BrRac",
        "IznosUkupno",
        "NacinPlac",
        "OibOper",
        "ZastKod",
        "NakDost",
    ]


def _odgovor(body: bytes) -> bytes:
    return (
        b'<tns:RacunOdgovor Id="RacunOdgovor"'
        b' xmlns:tns="http://www.apis-it.hr/fin/2012/types/f73">'
        b"<tns:Zaglavlje>"
        b"<tns:IdPoruke>9d1b3a2e-0000-4000-8000-0123456789ab</tns:IdPoruke>"
        b"<tns:DatumVrijeme>03.08.2026T11:54:26</tns:DatumVrijeme>"
        b"</tns:Zaglavlje>" + body + b"</tns:RacunOdgovor>"
    )


def test_parse_odgovor_with_jir(xsd: etree.XMLSchema) -> None:
    raw = _odgovor(b"<tns:Jir>9d1b3a2e-1111-4000-8000-0123456789ab</tns:Jir>")
    xsd.assertValid(etree.fromstring(raw))

    odgovor = parse_racun_odgovor(raw)
    assert odgovor.ok
    assert odgovor.jir == "9d1b3a2e-1111-4000-8000-0123456789ab"
    assert odgovor.greske == ()
    assert odgovor.datum_vrijeme == datetime(2026, 8, 3, 11, 54, 26)


def test_parse_odgovor_with_greske(xsd: etree.XMLSchema) -> None:
    raw = _odgovor(
        b"<tns:Greske><tns:Greska>"
        b"<tns:SifraGreske>s004</tns:SifraGreske>"
        b"<tns:PorukaGreske>Neispravan digitalni potpis.</tns:PorukaGreske>"
        b"</tns:Greska></tns:Greske>"
    )
    xsd.assertValid(etree.fromstring(raw))

    odgovor = parse_racun_odgovor(raw)
    assert not odgovor.ok
    assert odgovor.jir is None
    assert odgovor.greske[0].sifra == "s004"
    assert odgovor.greske[0].poruka == "Neispravan digitalni potpis."


def test_parse_rejects_wrong_root() -> None:
    with pytest.raises(FiskalizacijaError, match="expected RacunOdgovor"):
        parse_racun_odgovor(b"<wrong/>")


def test_parse_rejects_malformed_xml() -> None:
    with pytest.raises(FiskalizacijaError, match="not well-formed"):
        parse_racun_odgovor(b"<not-xml")
