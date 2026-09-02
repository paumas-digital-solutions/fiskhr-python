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
The same holds for an incoming invoice once its status is set.

**Two services, one client.** Sending goes to
``SendB2BOutgoingInvoicePKIWebService`` and everything about incoming
invoices to ``B2BFinaInvoiceWebService``, at a different URL. Both take the
same certificate and the same signatures, so this adapter holds a client for
each and routes by operation.
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
from fiskalhr.f2.posrednik.base import (
    Isporuka,
    PosrednikError,
    PrimljeniERacun,
    RazlogOdbijanja,
    StatusIsporuke,
    StatusOdgovor,
    UlazniRacun,
)
from fiskalhr.f2.posrednik.messages import (
    build_echo,
    build_incoming_invoice,
    build_incoming_list,
    build_incoming_status,
    build_send_invoice,
    build_status_query,
    parse_echo,
    parse_incoming_invoice,
    parse_incoming_list,
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
    "incoming_list": "http://fina.hr/eracun/b2b/GetB2BIncomingInvoiceList",
    "incoming_get": "http://fina.hr/eracun/b2b/GetB2BIncomingInvoice",
    "incoming_status": "http://fina.hr/eracun/b2b/ChangeB2BIncomingInvoiceStatus",
}

_INBOUND = frozenset({"incoming_list", "incoming_get", "incoming_status"})
"""Operations served by B2BFinaInvoiceWebService rather than the send
service — a different endpoint, same certificate and signing."""


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
        self._zaprimanje = SoapClient(
            FINA_SERVICE_URLS[(FinaServis.ZAPRIMANJE, env)],
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

    def ulazni_racuni(self) -> tuple[UlazniRacun, ...]:
        """List the incoming eRačuni waiting to be collected.

        Summaries only — `preuzmi` fetches a document. An empty tuple is the
        normal answer when nothing is waiting.
        """
        request = build_incoming_list(message_id=_message_id(), oib=self.oib)
        return parse_incoming_list(self._call(request, action="incoming_list"))

    def preuzmi(self, id_posrednika: str) -> PrimljeniERacun:
        """Collect one incoming eRačun, with its PDF when one was sent.

        Args:
            id_posrednika: FINA's ``InvoiceID``, from `ulazni_racuni`.

        Raises:
            PosrednikError: FINA rejected the request, or the document it
                returned is not well-formed.
        """
        request = build_incoming_invoice(id_posrednika, message_id=_message_id(), oib=self.oib)
        return parse_incoming_invoice(self._call(request, action="incoming_get"))

    def potvrdi_primitak(self, id_posrednika: str) -> None:
        """Confirm receipt of an incoming eRačun (``RECEIVING_CONFIRMED``)."""
        self._promijeni_status(id_posrednika, StatusIsporuke.ZAPRIMANJE_POTVRDJENO)

    def prihvati(self, id_posrednika: str, *, napomena: str | None = None) -> None:
        """Accept an incoming eRačun (``APPROVED``)."""
        self._promijeni_status(id_posrednika, StatusIsporuke.PRIHVACEN, napomena=napomena)

    def odbij(
        self,
        id_posrednika: str,
        *,
        razlog: RazlogOdbijanja,
        napomena: str | None = None,
    ) -> None:
        """Reject an incoming eRačun (``REJECTED``), telling FINA why.

        This tells the *supplier*. The Tax Administration has to be told
        separately, with
        `fiskalhr.f2.izvjestavanje.EIzvjestavanjeClient.evidentiraj_odbijanje`
        — unless FINA files that for you (`fiskalizira`). The two codebooks
        differ: FINA asks whether VAT is the reason, the Tax Administration
        whether the mismatch changes the tax computation.
        """
        self._promijeni_status(
            id_posrednika, StatusIsporuke.ODBIJEN, razlog=razlog, napomena=napomena
        )

    def _promijeni_status(
        self,
        id_posrednika: str,
        status: StatusIsporuke,
        *,
        razlog: RazlogOdbijanja | None = None,
        napomena: str | None = None,
    ) -> None:
        request = build_incoming_status(
            id_posrednika,
            status=status.value,
            razlog=razlog.value if razlog is not None else None,
            napomena=napomena,
            message_id=_message_id(),
            oib=self.oib,
        )
        # A status change answers with an acknowledgement and nothing else;
        # parsing it is only about surfacing a rejection.
        self._call(request, action="incoming_status")

    def _call(self, request: etree._Element, *, action: str) -> etree._Element:
        envelope = sign_envelope_wsse(build_envelope(request), self.certificate)
        client = self._zaprimanje if action in _INBOUND else self._slanje
        return self._post(envelope, client, soap_action=_SOAP_ACTIONS[action])

    def _post(
        self, envelope: etree._Element, client: SoapClient, *, soap_action: str
    ) -> etree._Element:
        """POST an already-signed envelope.

        `SoapClient.call` builds and wraps the envelope itself, which would
        discard the WS-Security header, so the signed envelope goes out
        directly through the same client — keeping its TLS context, timeout
        and retry policy.
        """
        body = etree.tostring(envelope, xml_declaration=True, encoding="UTF-8")
        return unwrap_soap(client.post_envelope(body, soap_action=soap_action))

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
        self._zaprimanje.close()

    def __enter__(self) -> FinaPosrednik:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def _message_id() -> str:
    """A unique ``MessageID`` per request, as FINA requires."""
    return str(uuid.uuid4())
