"""FINA delivery adapter, end to end against the in-process mock."""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import rsa
from lxml import etree

from fiskalhr.core.certs import Certificate
from fiskalhr.core.environment import Environment
from fiskalhr.core.errors import TransportError
from fiskalhr.core.transport import SOAP_ENV_NS
from fiskalhr.core.wsse import WSSE_NS
from fiskalhr.f2.fiskalizacija import evidencija_iz_xml
from fiskalhr.f2.posrednik import (
    FINA_SERVICE_URLS,
    FinaPosrednik,
    FinaServis,
    Posrednik,
    PosrednikError,
    RazlogOdbijanja,
    StatusIsporuke,
)
from fiskalhr.f2.ubl import ERacunBuilder, sign_eracun, to_xml
from fiskalhr.testing import MockPosrednik

OIB_IZDAVATELJ = "12345678903"
OIB_PRIMATELJ = "00000000001"
BROJ = "2026-42-P1-1"


@pytest.fixture
def certificate(rsa_key: rsa.RSAPrivateKey, self_signed_cert: x509.Certificate) -> Certificate:
    return Certificate(private_key=rsa_key, certificate=self_signed_cert)


def _document(vrsta: str = "380") -> etree._Element:
    builder = (
        ERacunBuilder()
        .izdavatelj(
            oib=OIB_IZDAVATELJ,
            naziv="Tvrtka d.o.o.",
            ulica="Ulica 1",
            grad="Zagreb",
            postanski_broj="10000",
        )
        .primatelj(
            oib=OIB_PRIMATELJ,
            naziv="Kupac d.o.o.",
            ulica="Ulica 2",
            grad="Rijeka",
            postanski_broj="51000",
        )
        .operater(oib=OIB_IZDAVATELJ, oznaka="Operater1")
        .broj(BROJ)
        .datum_izdavanja(date(2026, 8, 13), time(12, 0))
        .dospijece(date(2026, 9, 12))
        .stavka(naziv="Licenca", kpd="62.20.20", kolicina=1, cijena="100.00", pdv_stopa=25)
    )
    if vrsta == "381":
        builder = builder.odobrenje(BROJ, date(2026, 8, 13))
    return to_xml(builder.build())


def _signed(certificate: Certificate, vrsta: str = "380") -> etree._Element:
    return sign_eracun(_document(vrsta), certificate)


def _posrednik(certificate: Certificate, mock: MockPosrednik) -> FinaPosrednik:
    return FinaPosrednik(
        certificate, oib=OIB_IZDAVATELJ, env=Environment.DEMO, transport=mock.transport()
    )


def test_fina_posrednik_satisfies_the_protocol(certificate: Certificate) -> None:
    posrednik = _posrednik(certificate, MockPosrednik())

    assert isinstance(posrednik, Posrednik)


def test_echo_round_trips(certificate: Certificate) -> None:
    posrednik = _posrednik(certificate, MockPosrednik())

    assert posrednik.echo("zdravo") == "zdravo"


def test_sending_delivers_the_signed_document(certificate: Certificate) -> None:
    mock = MockPosrednik()
    posrednik = _posrednik(certificate, mock)

    isporuka = posrednik.posalji(
        _signed(certificate), primatelj_oib=OIB_PRIMATELJ, broj_racuna=BROJ
    )

    assert isporuka.prihvacen
    assert isporuka.id_posrednika is not None
    assert isporuka.broj_racuna == BROJ
    # The mock decodes what actually arrived, signature and all.
    delivered = mock.primljeni[BROJ]
    assert delivered.find(".//{http://www.w3.org/2000/09/xmldsig#}SignatureValue") is not None


def test_every_request_is_wsse_signed(certificate: Certificate) -> None:
    mock = MockPosrednik()
    posrednik = _posrednik(certificate, mock)

    posrednik.posalji(_signed(certificate), primatelj_oib=OIB_PRIMATELJ, broj_racuna=BROJ)

    envelope = mock.zahtjevi[-1]
    security = envelope.find(f"{{{SOAP_ENV_NS}}}Header/{{{WSSE_NS}}}Security")
    assert security is not None


def test_rejection_comes_back_as_a_result_not_an_exception(certificate: Certificate) -> None:
    """A rejected invoice is a business outcome with a deadline attached,
    not a transport failure — the caller has to be able to act on it."""
    mock = MockPosrednik(
        odbij={BROJ: [("E101", "Primatelj nije registriran"), ("E102", "Neispravan OIB")]}
    )
    posrednik = _posrednik(certificate, mock)

    isporuka = posrednik.posalji(
        _signed(certificate), primatelj_oib=OIB_PRIMATELJ, broj_racuna=BROJ
    )

    assert not isporuka.prihvacen
    assert isporuka.greske == (
        ("E101", "Primatelj nije registriran"),
        ("E102", "Neispravan OIB"),
    )


def test_unsigned_documents_are_refused_before_sending(certificate: Certificate) -> None:
    mock = MockPosrednik()
    posrednik = _posrednik(certificate, mock)

    with pytest.raises(PosrednikError, match="requires the eRačun XML to be signed"):
        posrednik.posalji(_document(), primatelj_oib=OIB_PRIMATELJ, broj_racuna=BROJ)

    assert mock.zahtjevi == []  # nothing was sent


def test_issuer_oib_must_match_the_certificate(certificate: Certificate) -> None:
    """FINA refuses these remotely; catching it here names both OIBs."""
    mock = MockPosrednik()
    posrednik = FinaPosrednik(
        certificate, oib=OIB_PRIMATELJ, env=Environment.DEMO, transport=mock.transport()
    )

    with pytest.raises(PosrednikError, match="but this client sends as"):
        posrednik.posalji(_signed(certificate), primatelj_oib=OIB_PRIMATELJ, broj_racuna=BROJ)

    assert mock.zahtjevi == []


def test_credit_notes_go_in_the_credit_note_envelope(certificate: Certificate) -> None:
    mock = MockPosrednik()
    posrednik = _posrednik(certificate, mock)

    posrednik.posalji(_signed(certificate, "381"), primatelj_oib=OIB_PRIMATELJ, broj_racuna=BROJ)

    request = mock.zahtjevi[-1]
    names = {
        etree.QName(element).localname for element in request.iter() if isinstance(element.tag, str)
    }
    assert "CreditNoteEnvelope" in names
    assert "InvoiceEnvelope" not in names


def test_status_query_reports_the_delivery_state(certificate: Certificate) -> None:
    mock = MockPosrednik(status=StatusIsporuke.ODBIJEN)
    posrednik = _posrednik(certificate, mock)

    odgovor = posrednik.status(BROJ, godina=2026)

    assert odgovor.status is StatusIsporuke.ODBIJEN
    assert odgovor.status_kod == "REJECTED"
    assert odgovor.vrijeme is not None


def test_unknown_status_codes_are_reported_verbatim(certificate: Certificate) -> None:
    """FINA can add a status without this library knowing it first."""
    mock = MockPosrednik()
    mock.status = "SOMETHING_NEW"
    posrednik = _posrednik(certificate, mock)

    odgovor = posrednik.status(BROJ, godina=2026)

    assert odgovor.status is None
    assert odgovor.status_kod == "SOMETHING_NEW"


def test_message_level_rejection_raises(certificate: Certificate) -> None:
    class RejectingMock(MockPosrednik):
        def _ack_root(
            self, name: str, request: etree._Element, *, message_type: int
        ) -> etree._Element:
            root = super()._ack_root(name, request, message_type=message_type)
            for element in root.iter():
                if isinstance(element.tag, str):
                    local = etree.QName(element).localname
                    if local == "AckStatus":
                        element.text = "MSG_NOT_VALID"
                    elif local == "AckStatusCode":
                        element.text = "42"
            return root

    posrednik = _posrednik(certificate, RejectingMock())

    with pytest.raises(PosrednikError, match="MSG_NOT_VALID") as raised:
        posrednik.echo()

    assert raised.value.code == "42"


def test_soap_faults_surface_as_transport_errors(certificate: Certificate) -> None:
    def faulting(_request: httpx.Request) -> httpx.Response:
        envelope = (
            f'<soapenv:Envelope xmlns:soapenv="{SOAP_ENV_NS}"><soapenv:Body>'
            f"<soapenv:Fault><faultcode>soapenv:Server</faultcode>"
            f"<faultstring>servis nedostupan</faultstring></soapenv:Fault>"
            f"</soapenv:Body></soapenv:Envelope>"
        ).encode()
        return httpx.Response(500, content=envelope)

    posrednik = FinaPosrednik(
        certificate, oib=OIB_IZDAVATELJ, transport=httpx.MockTransport(faulting)
    )

    with pytest.raises(TransportError, match="servis nedostupan"):
        posrednik.echo()


def test_fina_reports_fiscalization_itself(certificate: Certificate) -> None:
    """Sending through FINA also files the invoice with the Tax
    Administration, so a caller must not report it a second time."""
    posrednik = _posrednik(certificate, MockPosrednik())

    assert posrednik.fiskalizira is True


def test_endpoints_differ_between_environments() -> None:
    demo = FINA_SERVICE_URLS[(FinaServis.SLANJE, Environment.DEMO)]
    production = FINA_SERVICE_URLS[(FinaServis.SLANJE, Environment.PRODUCTION)]

    assert demo.startswith("https://prezdigitalneusluge.fina.hr/")
    assert production.startswith("https://webservisi.fina.hr/")
    assert demo != production


def test_sender_oib_defaults_to_the_certificate(certificate: Certificate) -> None:
    posrednik = FinaPosrednik(certificate, transport=MockPosrednik().transport())

    assert posrednik.oib == certificate.oib


# --- Incoming invoices ---


def test_lists_incoming_invoices(certificate: Certificate) -> None:
    mock = MockPosrednik()
    mock.dodaj_ulazni("500123", _document())
    posrednik = _posrednik(certificate, mock)

    ulazni = posrednik.ulazni_racuni()

    assert len(ulazni) == 1
    assert ulazni[0].id_posrednika == "500123"
    assert ulazni[0].broj_racuna == BROJ
    assert ulazni[0].izdavatelj_naziv == "Dobavljac d.o.o."
    # The list carries 9934:oib; the OIB alone is what a caller wants.
    assert ulazni[0].izdavatelj_oib == "12345678903"
    assert ulazni[0].iznos == Decimal("125.00")


def test_an_empty_inbox_is_not_an_error(certificate: Certificate) -> None:
    posrednik = _posrednik(certificate, MockPosrednik())

    assert posrednik.ulazni_racuni() == ()


def test_collects_an_incoming_invoice_with_its_pdf(certificate: Certificate) -> None:
    mock = MockPosrednik()
    mock.dodaj_ulazni("500123", _document(), pdf=b"%PDF-1.7 fake")
    posrednik = _posrednik(certificate, mock)

    primljeni = posrednik.preuzmi("500123")

    assert primljeni.id_posrednika == "500123"
    assert etree.QName(primljeni.dokument).localname == "Invoice"
    assert primljeni.pdf == b"%PDF-1.7 fake"


def test_a_collected_invoice_can_be_reported_as_incoming(certificate: Certificate) -> None:
    """The point of collecting one: it has to become a reportable digest."""
    mock = MockPosrednik()
    mock.dodaj_ulazni("500123", _document())
    posrednik = _posrednik(certificate, mock)

    primljeni = posrednik.preuzmi("500123")
    evidencija = evidencija_iz_xml(primljeni.dokument)

    assert evidencija.broj == BROJ
    assert evidencija.izdavatelj.oib == OIB_IZDAVATELJ


def test_collects_a_credit_note(certificate: Certificate) -> None:
    mock = MockPosrednik()
    mock.dodaj_ulazni("500124", _document("381"))
    posrednik = _posrednik(certificate, mock)

    primljeni = posrednik.preuzmi("500124")

    assert etree.QName(primljeni.dokument).localname == "CreditNote"


def test_confirming_accepting_and_rejecting_set_the_right_status(
    certificate: Certificate,
) -> None:
    mock = MockPosrednik()
    posrednik = _posrednik(certificate, mock)

    posrednik.potvrdi_primitak("500123")
    posrednik.prihvati("500124", napomena="U redu")
    posrednik.odbij("500125", razlog=RazlogOdbijanja.PDV, napomena="Kriva stopa PDV-a")

    assert mock.statusi == [
        ("500123", "RECEIVING_CONFIRMED", None, None),
        ("500124", "APPROVED", None, "U redu"),
        ("500125", "REJECTED", "VAT_REASON", "Kriva stopa PDV-a"),
    ]


def test_inbound_calls_go_to_the_zaprimanje_service(certificate: Certificate) -> None:
    """Sending and receiving are different FINA services at different URLs;
    routing an inbound call to the send endpoint would 404 in production."""
    seen: list[str] = []

    def recording(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return MockPosrednik()._handle(request)

    posrednik = FinaPosrednik(
        certificate, oib=OIB_IZDAVATELJ, transport=httpx.MockTransport(recording)
    )
    posrednik.ulazni_racuni()
    posrednik.echo()

    assert "B2BFinaInvoiceWebService" in seen[0]
    assert "SendB2BOutgoingInvoicePKIWebService" in seen[1]


def test_incoming_requests_use_the_buyer_header(certificate: Certificate) -> None:
    """The receive leg heads its messages HeaderBuyer with a bare OIB, while
    the send leg uses HeaderSupplier with the 9934: scheme prefix."""
    mock = MockPosrednik()
    posrednik = _posrednik(certificate, mock)

    posrednik.ulazni_racuni()

    request = mock.zahtjevi[-1]
    names = {
        etree.QName(element).localname for element in request.iter() if isinstance(element.tag, str)
    }
    assert "HeaderBuyer" in names
    assert "HeaderSupplier" not in names
    buyer_id = next(
        element.text
        for element in request.iter()
        if isinstance(element.tag, str) and etree.QName(element).localname == "BuyerID"
    )
    assert buyer_id == OIB_IZDAVATELJ  # bare, not "9934:..."


def test_collecting_an_unknown_invoice_fails(certificate: Certificate) -> None:
    posrednik = _posrednik(certificate, MockPosrednik())

    with pytest.raises(TransportError, match="unknown incoming invoice"):
        posrednik.preuzmi("999999")
