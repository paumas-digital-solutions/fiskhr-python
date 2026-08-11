"""End-to-end F1 loop, entirely in-process via MockCis.

This is the Layer-3 test from the testing strategy: the real client code
path — ZKI, message build, XML-DSig signing, SOAP, response-signature
verification, parsing — against a mock that validates requests against the
official XSD and signs its responses.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from fiskalhr.core.certs import Certificate
from fiskalhr.core.errors import CisError, SignatureVerificationError, TransportError
from fiskalhr.f1.client import FiskalizacijaClient
from fiskalhr.f1.models import BrojRacuna, NacinPlacanja, OznakaSlijednosti, Porez, Racun
from fiskalhr.testing import MockCis
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
