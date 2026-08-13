"""eIzvještavanje (payments/rejections): messages, client, mock.

Signed requests must validate against the official eIzvjestavanjeSchema.xsd.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from lxml import etree

from fiskhr.core.certs import Certificate
from fiskhr.core.errors import CisError
from fiskhr.core.xades import sign_xades_enveloped
from fiskhr.f2.fiskalizacija import EvidencijaERacun
from fiskhr.f2.izvjestavanje import (
    EIzvjestavanjeClient,
    NacinPlacanjaNaplate,
    Naplata,
    Odbijanje,
    RazlogOdbijanja,
    build_evidentiraj_isporuku_zahtjev,
    build_evidentiraj_naplatu_zahtjev,
    build_evidentiraj_odbijanje_zahtjev,
    build_ovlastenja_zahtjev,
)
from fiskhr.f2.service import eizvjestavanje_schema_path
from fiskhr.f2.ubl import ERacun, ERacunBuilder
from fiskhr.testing import MockEIzvjestavanje
from tests.conftest import make_self_signed_cert

SLANJE = datetime(2026, 8, 13, 14, 30, 0, 0)


@pytest.fixture(scope="module")
def xsd() -> etree.XMLSchema:
    return etree.XMLSchema(etree.parse(eizvjestavanje_schema_path()))


@pytest.fixture(scope="module")
def certificate() -> Certificate:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return Certificate(private_key=key, certificate=make_self_signed_cert(key))


def _eracun() -> ERacun:
    return (
        ERacunBuilder()
        .izdavatelj(
            oib="12345678903",
            naziv="Paumas j.d.o.o.",
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
        .datum_izdavanja(date(2026, 8, 13), time(12, 0, 0))
        .dospijece(date(2026, 9, 12))
        .stavka(naziv="Licenca", kpd="62.20.20", kolicina=1, cijena="100.00", pdv_stopa=25)
        .build()
    )


def _naplata() -> Naplata:
    return Naplata.za_eracun(_eracun(), datum_naplate=date(2026, 9, 1))


def test_naplata_za_eracun_defaults_to_payable_amount() -> None:
    naplata = _naplata()
    assert naplata.broj == "2026-42-P1-1"
    assert naplata.oib_izdavatelja == "12345678903"
    assert naplata.oib_primatelja == "00000000001"
    assert naplata.naplaceni_iznos == Decimal("125.00")
    assert naplata.nacin_placanja is NacinPlacanjaNaplate.TRANSAKCIJSKI_RACUN


def test_signed_naplata_zahtjev_validates(xsd: etree.XMLSchema, certificate: Certificate) -> None:
    zahtjev = build_evidentiraj_naplatu_zahtjev(
        (_naplata(),), id_zahtjeva="req-1", datum_vrijeme_slanja=SLANJE
    )
    assert xsd.validate(sign_xades_enveloped(zahtjev, certificate)), xsd.error_log


def test_signed_odbijanje_zahtjev_validates(xsd: etree.XMLSchema, certificate: Certificate) -> None:
    odbijanje = Odbijanje.za_eracun(
        _eracun(),
        datum_odbijanja=date(2026, 8, 20),
        vrsta_razloga=RazlogOdbijanja.NEUSKLADJENOST_POREZ,
        razlog="Pogresna stopa PDV-a na stavci 1",
    )
    zahtjev = build_evidentiraj_odbijanje_zahtjev(
        (odbijanje,), id_zahtjeva="req-2", datum_vrijeme_slanja=SLANJE
    )
    assert xsd.validate(sign_xades_enveloped(zahtjev, certificate)), xsd.error_log


def test_signed_ovlastenja_zahtjev_validates(
    xsd: etree.XMLSchema, certificate: Certificate
) -> None:
    zahtjev = build_ovlastenja_zahtjev(
        "12345678903", id_zahtjeva="req-3", datum_vrijeme_slanja=SLANJE
    )
    assert xsd.validate(sign_xades_enveloped(zahtjev, certificate)), xsd.error_log


def test_client_reports_naplata_end_to_end(certificate: Certificate) -> None:
    mock = MockEIzvjestavanje()
    client = EIzvjestavanjeClient(certificate, transport=mock.transport())

    odgovor = client.evidentiraj_naplatu(_naplata())

    assert odgovor.prihvacen
    assert len(mock.requests) == 1


def test_client_raises_cis_error_on_rejection(certificate: Certificate) -> None:
    mock = MockEIzvjestavanje(force_greska="S009")
    client = EIzvjestavanjeClient(certificate, transport=mock.transport())

    odbijanje = Odbijanje.za_eracun(
        _eracun(),
        datum_odbijanja=date(2026, 8, 20),
        vrsta_razloga=RazlogOdbijanja.OSTALO,
        razlog="Racun nije naruceni",
    )
    with pytest.raises(CisError) as excinfo:
        client.evidentiraj_odbijanje(odbijanje)
    assert excinfo.value.code == "S009"


def test_signed_isporuka_zahtjev_validates(xsd: etree.XMLSchema, certificate: Certificate) -> None:
    zahtjev = build_evidentiraj_isporuku_zahtjev(
        (EvidencijaERacun.from_eracuna(_eracun()),),
        id_zahtjeva="req-4",
        datum_vrijeme_slanja=SLANJE,
    )
    zaglavlje = zahtjev.find(
        "e:Zaglavlje/e:vrstaRacuna",
        namespaces={"e": "http://www.porezna-uprava.gov.hr/fin/2024/types/eIzvjestavanje"},
    )
    assert zaglavlje is not None
    assert zaglavlje.text == "IR"
    assert xsd.validate(sign_xades_enveloped(zahtjev, certificate)), xsd.error_log


def test_client_reports_isporuka_end_to_end(certificate: Certificate) -> None:
    mock = MockEIzvjestavanje()
    client = EIzvjestavanjeClient(certificate, transport=mock.transport())

    odgovor = client.evidentiraj_isporuku(_eracun())

    assert odgovor.prihvacen


def test_client_fetches_ovlastenja(certificate: Certificate) -> None:
    mock = MockEIzvjestavanje(ovlasteni_oibi=("12345678903", "00000000001"))
    client = EIzvjestavanjeClient(certificate, transport=mock.transport())

    assert client.ovlastenja("12345678903") == ("12345678903", "00000000001")


def test_zahtjev_caps_at_100_records() -> None:
    with pytest.raises(ValueError, match="1-100"):
        build_evidentiraj_naplatu_zahtjev((), id_zahtjeva="x", datum_vrijeme_slanja=SLANJE)
