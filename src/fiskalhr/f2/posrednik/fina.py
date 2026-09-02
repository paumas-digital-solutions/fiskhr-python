"""``FinaPosrednik`` — the reference `Posrednik` adapter.

FINA is an informacijski posrednik: it takes a signed eRačun and delivers it
to the recipient's access point. What makes this adapter thicker than a SOAP
wrapper is that FINA authenticates three ways at once, and all three have to
line up:

1. **2-way TLS** with a FINA-issued client certificate;
2. **a WS-Security signature** over the SOAP body (`fiskalhr.core.wsse`);
3. **a XAdES signature inside the invoice** (`fiskalhr.f2.ubl.sign_eracun`),
   whose OIB FINA checks against the certificate the invoice was signed
   with. A mismatch is refused before the message enters their system.

This adapter checks (3) itself, before sending: an unsigned invoice, or one
whose issuer OIB disagrees with the certificate, fails locally with an
explanation rather than as an opaque rejection.

**Fiscalization.** FINA reports invoices sent through it to the Tax
Administration on the sender's behalf, so ``fiskalizira`` is True and a
caller should not also report the same invoice with
`fiskalhr.f2.fiskalizacija.EFiskalizacijaClient` — that would file it twice.
"""

from __future__ import annotations

import uuid

import httpx
from lxml import etree

from fiskalhr.core.certs import Certificate
from fiskalhr.core.environment import Environment
from fiskalhr.core.transport import SoapClient, build_envelope, unwrap_soap
from fiskalhr.core.types import validate_oib
from fiskalhr.core.wsse import sign_envelope_wsse
from fiskalhr.f2.posrednik.base import Isporuka, PosrednikError, StatusOdgovor
from fiskalhr.f2.posrednik.messages import (
    build_echo,
    build_send_invoice,
    build_status_query,
    parse_echo,
    parse_send_ack,
    parse_status_ack,
)
from fiskalhr.f2.posrednik.service import FINA_SERVICE_URLS, FinaServis
from fiskalhr.f2.ubl.xml import CAC, CBC, SIG

__all__ = ["FinaPosrednik"]

_SOAP_ACTIONS = {
    "echo": "http://fina.hr/eracun/b2b/Echo",
    "send": "http://fina.hr/eracun/b2b/SendB2BOutgoingInvoice",
    "status": "http://fina.hr/eracun/b2b/GetB2BOutgoingInvoiceStatus",
}


class FinaPosrednik:
    """Delivery through FINA's e-Račun B2B service.

    Args:
        certificate: The FINA-issued certificate. Used for all three of the
            TLS handshake, the WS-Security signature, and the OIB check
            against the invoice. Demo and production certificates are not
            interchangeable, and neither are the environments.
        oib: The sender's OIB (``SupplierID``). Defaults to the one in the
            certificate subject.
        env: Which environment to talk to; selects the endpoint.
        timeout: Per-request timeout in seconds.
        transport: Optional httpx transport, injectable for testing —
            `fiskalhr.testing.MockPosrednik` plugs in here.

    Raises:
        ValueError: If no OIB was given and none could be read from the
            certificate.
    """

    fiskalizira = True
    """FINA reports invoices sent through it to the Tax Administration; do
    not report the same invoice again with ``EFiskalizacijaClient``."""

    def __init__(
        self,
        certificate: Certificate,
        *,
        oib: str | None = None,
        env: Environment = Environment.DEMO,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        resolved = oib if oib is not None else certificate.oib
        if resolved is None:
            raise ValueError(
                "cannot determine the sender OIB: the certificate subject carries none, "
                "so pass oib= explicitly"
            )
        self.certificate = certificate
        self.oib = validate_oib(resolved)
        self.env = env
        self._slanje = SoapClient(
            FINA_SERVICE_URLS[(FinaServis.SLANJE, env)],
            timeout=timeout,
            client_certificate=certificate if transport is None else None,
            transport=transport,
        )

    def echo(self, text: str = "ping") -> str:
        """Round-trip a string. Proves TLS, credentials and signing at once."""
        request = build_echo(text, message_id=_message_id(), oib=self.oib)
        return parse_echo(self._call(request, action="echo"))

    def posalji(
        self, document: etree._Element, *, primatelj_oib: str, broj_racuna: str
    ) -> Isporuka:
        """Deliver one signed eRačun.

        Args:
            document: A signed UBL Invoice or CreditNote. Sign it with
                `fiskalhr.f2.ubl.sign_eracun` first — FINA requires it.
            primatelj_oib: The recipient's OIB.
            broj_racuna: The invoice number in the sender's system.

        Raises:
            PosrednikError: The document is unsigned, its issuer OIB does
                not match the certificate, or FINA rejected the message.
            TransportError: FINA could not be reached.
        """
        self._check_signed(document)
        self._check_issuer(document)
        request = build_send_invoice(
            document,
            message_id=_message_id(),
            oib=self.oib,
            primatelj_oib=validate_oib(primatelj_oib),
            broj_racuna=broj_racuna,
        )
        return parse_send_ack(self._call(request, action="send"))

    def status(self, broj_racuna: str, *, godina: int) -> StatusOdgovor:
        """Ask where a previously sent invoice has got to.

        Args:
            broj_racuna: The invoice number in the sender's system.
            godina: Its year — FINA addresses invoices by number *and*
                year, so the number alone is not enough.
        """
        request = build_status_query(
            broj_racuna, godina=godina, message_id=_message_id(), oib=self.oib
        )
        return parse_status_ack(self._call(request, action="status"))

    def _call(self, request: etree._Element, *, action: str) -> etree._Element:
        envelope = sign_envelope_wsse(build_envelope(request), self.certificate)
        return self._post(envelope, soap_action=_SOAP_ACTIONS[action])

    def _post(self, envelope: etree._Element, *, soap_action: str) -> etree._Element:
        """POST an already-signed envelope.

        `SoapClient.call` builds and wraps the envelope itself, which would
        discard the WS-Security header, so the signed envelope goes out
        directly through the same client — keeping its TLS context, timeout
        and retry policy.
        """
        body = etree.tostring(envelope, xml_declaration=True, encoding="UTF-8")
        response = self._slanje.post_envelope(body, soap_action=soap_action)
        return unwrap_soap(response)

    def _check_signed(self, document: etree._Element) -> None:
        """The signature slot exists on every built document but is empty
        until `sign_eracun` fills it, so presence of the element proves
        nothing — its `SignatureInformation` has to have content."""
        signatures = document.find(f".//{{{SIG}}}UBLDocumentSignatures")
        signed = signatures is not None and any(len(child) > 0 for child in signatures)
        if not signed:
            raise PosrednikError(
                "FINA requires the eRačun XML to be signed: call "
                "fiskalhr.f2.ubl.sign_eracun(document, certificate) before sending"
            )

    def _check_issuer(self, document: etree._Element) -> None:
        """FINA refuses a document whose OIB is not the certificate's.

        Catching it here turns an opaque remote rejection into a local
        error naming both OIBs.
        """
        issuer = document.find(
            f"{{{CAC}}}AccountingSupplierParty/{{{CAC}}}Party/"
            f"{{{CAC}}}PartyTaxScheme/{{{CBC}}}CompanyID"
        )
        if issuer is None or not issuer.text:
            return
        oib = issuer.text.removeprefix("HR")
        if oib != self.oib:
            raise PosrednikError(
                f"the invoice is issued by OIB {oib} but this client sends as {self.oib}; "
                "FINA rejects a message whose invoice OIB differs from the certificate's"
            )

    def close(self) -> None:
        self._slanje.close()

    def __enter__(self) -> FinaPosrednik:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def _message_id() -> str:
    """A unique ``MessageID`` per request, as FINA requires."""
    return str(uuid.uuid4())
