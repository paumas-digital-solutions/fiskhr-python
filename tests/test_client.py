"""End-to-end F1 loop, entirely in-process via MockCis.

This is the Layer-3 test from the testing strategy: the real client code
path — ZKI, message build, XML-DSig signing, SOAP, response-signature
verification, parsing — against a mock that validates requests against the
official XSD and signs its responses.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from fiskhr.core.certs import Certificate
from fiskhr.core.environment import Environment
from fiskhr.core.errors import (
    CisError,
    FiskalizacijaError,
    SignatureVerificationError,
    TransportError,
)
from fiskhr.f1.client import FiskalizacijaClient
from fiskhr.f1.models import (
    BrojRacuna,
    NacinPlacanja,
    Napojnica,
    OznakaSlijednosti,
    Porez,
    Racun,
)
from fiskhr.f1.radno_vrijeme import (
    BrisanjeRadnogVremena,
    PoDogovoru,
    RadnoVrijeme,
    Redovno,
)
from fiskhr.testing import MockCis
from tests.conftest import TEST_OIB, make_rsa_key, make_self_signed_cert


@pytest.fixture(scope="module")
def taxpayer_cert() -> Certificate:
    key = make_rsa_key()
    return Certificate(private_key=key, certificate=make_self_signed_cert(key))


@pytest.fixture
def racun() -> Racun:
    return Racun(
        oib=TEST_OIB,
        u_sust_pdv=True,
        dat_vrijeme=datetime(2026, 8, 3, 11, 54, 25),
        ozn_slijed=OznakaSlijednosti.POSLOVNI_PROSTOR,
        br_rac=BrojRacuna(br_ozn_rac="1", ozn_pos_pr="POSL1", ozn_nap_ur="12"),
        pdv=(Porez(stopa=Decimal("25.00"), osnovica=Decimal("100.00"), iznos=Decimal("25.00")),),
        iznos_ukupno=Decimal("125.00"),
        nacin_plac=NacinPlacanja.KARTICA,
        oib_oper=TEST_OIB,
    )


def _client(cert: Certificate, mock: MockCis, **kwargs: object) -> FiskalizacijaClient:
    return FiskalizacijaClient(cert, transport=mock.transport(), **kwargs)  # type: ignore[arg-type]


def test_fiskaliziraj_returns_jir(taxpayer_cert: Certificate, racun: Racun) -> None:
    mock = MockCis()
    with _client(taxpayer_cert, mock) as client:
        odgovor = client.fiskaliziraj(racun)

    assert odgovor.ok
    assert odgovor.jir is not None
    assert len(mock.requests) == 1  # and the mock XSD-validated + verified it


def test_fiskaliziraj_raises_structured_cis_error(taxpayer_cert: Certificate, racun: Racun) -> None:
    mock = MockCis(force_greske=("s005",))
    with _client(taxpayer_cert, mock) as client, pytest.raises(CisError) as exc_info:
        client.fiskaliziraj(racun)

    error = exc_info.value
    assert error.code == "s005"
    assert error.message_hr is not None
    assert "OIB" in error.message_hr
    assert error.greske[0][0] == "s005"


def test_unsigned_response_is_rejected_by_default(taxpayer_cert: Certificate, racun: Racun) -> None:
    mock = MockCis(sign_responses=False)
    with _client(taxpayer_cert, mock) as client, pytest.raises(SignatureVerificationError):
        client.fiskaliziraj(racun)


def test_unverified_response_needs_loud_opt_in(taxpayer_cert: Certificate, racun: Racun) -> None:
    mock = MockCis(sign_responses=False)
    with _client(taxpayer_cert, mock, allow_unverified_response=True) as client:
        odgovor = client.fiskaliziraj(racun)
    assert odgovor.ok


def test_soap_fault_raises_transport_error(taxpayer_cert: Certificate, racun: Racun) -> None:
    mock = MockCis(soap_fault="service down for maintenance")
    with _client(taxpayer_cert, mock) as client, pytest.raises(TransportError, match="maintenance"):
        client.fiskaliziraj(racun)


def test_explicit_zki_is_sent_verbatim(taxpayer_cert: Certificate, racun: Racun) -> None:
    mock = MockCis()
    with _client(taxpayer_cert, mock) as client:
        zki = client.izracunaj_zki(racun)
        client.fiskaliziraj(racun, zki=zki)

    sent = mock.requests[0]
    ns = "{http://www.apis-it.hr/fin/2012/types/f73}"
    assert sent.findtext(f"{ns}Racun/{ns}ZastKod") == zki


def test_echo_roundtrip(taxpayer_cert: Certificate) -> None:
    mock = MockCis()
    with _client(taxpayer_cert, mock) as client:
        assert client.echo("proba") == "proba"


def test_napojnica_roundtrip(taxpayer_cert: Certificate, racun: Racun) -> None:
    mock = MockCis()
    napojnica = Napojnica(iznos=Decimal("2.00"), nacin_placanja=NacinPlacanja.GOTOVINA)
    with _client(taxpayer_cert, mock) as client:
        odgovor = client.fiskaliziraj_napojnicu(racun, napojnica)

    assert odgovor.ok
    assert odgovor.poruka is not None


def test_promijeni_nacin_placanja_roundtrip(taxpayer_cert: Certificate, racun: Racun) -> None:
    mock = MockCis()
    with _client(taxpayer_cert, mock) as client:
        odgovor = client.promijeni_nacin_placanja(racun, NacinPlacanja.TRANSAKCIJSKI_RACUN)

    assert odgovor.ok


def test_promijeni_podatke_racuna_roundtrip(taxpayer_cert: Certificate, racun: Racun) -> None:
    mock = MockCis()
    with _client(taxpayer_cert, mock) as client:
        odgovor = client.promijeni_podatke_racuna(
            racun,
            promijenjeni_nacin_plac=NacinPlacanja.OSTALO,
            promijenjeni_oib_primatelja_racuna="",
        )

    assert odgovor.ok
    assert odgovor.poruka is not None
    assert odgovor.poruka.sifra == "p005"


def test_napojnica_rejection_raises_cis_error(taxpayer_cert: Certificate, racun: Racun) -> None:
    mock = MockCis(force_greske=("s010",))
    napojnica = Napojnica(iznos=Decimal("2.00"), nacin_placanja=NacinPlacanja.KARTICA)
    with _client(taxpayer_cert, mock) as client, pytest.raises(CisError) as exc_info:
        client.fiskaliziraj_napojnicu(racun, napojnica)
    assert exc_info.value.code == "s010"


def test_provjera_roundtrip(taxpayer_cert: Certificate, racun: Racun) -> None:
    mock = MockCis()
    with _client(taxpayer_cert, mock) as client:
        odgovor = client.provjeri(racun)

    assert odgovor.ok
    assert odgovor.greske == ()


def test_provjera_reports_greske_without_raising(taxpayer_cert: Certificate, racun: Racun) -> None:
    # provjera returns the error list — that IS the result, no CisError.
    mock = MockCis(force_greske=("s001",))
    with _client(taxpayer_cert, mock) as client:
        odgovor = client.provjeri(racun)

    assert not odgovor.ok
    assert odgovor.greske[0].sifra == "s001"


def test_radno_vrijeme_roundtrips(taxpayer_cert: Certificate) -> None:
    mock = MockCis()
    message_time = datetime(2026, 8, 12, 9, 0, 0)
    radno_vrijeme = RadnoVrijeme(
        redovno=(Redovno(datum_od=date(2026, 9, 1), raspored=PoDogovoru()),)
    )
    with _client(taxpayer_cert, mock) as client:
        prijava = client.prijavi_radno_vrijeme(
            TEST_OIB, "POSL1", radno_vrijeme, TEST_OIB, datum_vrijeme=message_time
        )
        assert prijava.ok

        dohvat = client.dohvati_radno_vrijeme(
            TEST_OIB, "POSL1", TEST_OIB, datum_vrijeme=message_time
        )
        assert dohvat.ok
        assert dohvat.ozn_pos_pr == "POSL1"
        assert len(dohvat.radno_vrijeme.redovno) == 1

        brisanje = client.obrisi_radno_vrijeme(
            TEST_OIB,
            "POSL1",
            BrisanjeRadnogVremena(redovno_od=(date(2026, 9, 1),)),
            TEST_OIB,
            datum_vrijeme=message_time,
        )
        assert brisanje.ok

    assert len(mock.requests) == 3  # each XSD-validated and signature-verified


def test_provjera_is_demo_only(taxpayer_cert: Certificate, racun: Racun) -> None:
    mock = MockCis()
    client = FiskalizacijaClient(
        taxpayer_cert, env=Environment.PRODUCTION, transport=mock.transport()
    )
    with client, pytest.raises(FiskalizacijaError, match="demo environment"):
        client.provjeri(racun)
