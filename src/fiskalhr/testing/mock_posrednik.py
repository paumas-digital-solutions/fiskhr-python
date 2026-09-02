"""In-process FINA e-Račun mock, for testing an integration offline.

The F2 delivery counterpart of `fiskalhr.testing.MockCis`: it answers
`fiskalhr.f2.posrednik.FinaPosrednik` without a network, a FINA contract, or
a certificate from them. It verifies the WS-Security signature on every
request, so a mistake in the envelope fails here rather than silently
passing until the demo environment rejects it.

What it deliberately does *not* do is validate against FINA's XSDs — they
are not vendored (`docs/specs/SOURCES.md`), so unlike `MockCis` this mock
checks structure it was told about rather than structure a schema defines.

    mock = MockPosrednik()
    posrednik = FinaPosrednik(cert, oib=..., transport=mock.transport())
    isporuka = posrednik.posalji(document, primatelj_oib=..., broj_racuna="1")

Force a rejection to exercise the unhappy path:

    mock = MockPosrednik(odbij={"1": [("E101", "Primatelj nije registriran")]})
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime

import httpx
from lxml import etree

from fiskalhr.core.transport import SOAP_ENV_NS
from fiskalhr.core.wsse import WSSE_NS
from fiskalhr.f2.posrednik.base import StatusIsporuke
from fiskalhr.f2.posrednik.messages import IWSC

__all__ = ["MockPosrednik"]

_ACK_NS = "http://fina.hr/eracun/b2b/pki/Ack/v0.1"
_DS_NS = "http://www.w3.org/2000/09/xmldsig#"


class MockPosrednik:
    """A FINA e-Račun service that never leaves the process.

    Args:
        odbij: Invoice numbers to reject, mapped to the ``(code, message)``
            pairs to reject them with.
        status: Delivery status to report from ``status()``. A plain string
            is accepted too, to simulate a code this library does not know.
        require_signature: Whether to insist on a WS-Security signature over
            the request. On by default — that is most of what this mock is
            for.

    Attributes:
        primljeni: Every invoice received, by invoice number, as the decoded
            UBL document. Assert against it to check what was actually sent.
    """

    def __init__(
        self,
        *,
        odbij: dict[str, list[tuple[str, str]]] | None = None,
        status: StatusIsporuke | str = StatusIsporuke.ZAPRIMLJEN,
        require_signature: bool = True,
    ) -> None:
        self.odbij = odbij or {}
        self.status = status
        self.require_signature = require_signature
        self.primljeni: dict[str, etree._Element] = {}
        self.zahtjevi: list[etree._Element] = []
        self._next_id = 1000

    def transport(self) -> httpx.MockTransport:
        """An httpx transport to hand to `FinaPosrednik(transport=...)`."""
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        envelope = etree.fromstring(request.content)
        self.zahtjevi.append(envelope)
        self._verify_signature(envelope)

        body = envelope.find(f"{{{SOAP_ENV_NS}}}Body")
        if body is None or len(body) == 0:
            return self._fault("request had no body")
        message = body[0]
        name = etree.QName(message).localname

        if name == "EchoMsg":
            return self._echo(message)
        if name == "SendB2BOutgoingInvoiceMsg":
            return self._send(message)
        if name == "GetB2BOutgoingInvoiceStatusMsg":
            return self._status(message)
        return self._fault(f"unknown operation {name}")

    def _verify_signature(self, envelope: etree._Element) -> None:
        if not self.require_signature:
            return
        security = envelope.find(f"{{{SOAP_ENV_NS}}}Header/{{{WSSE_NS}}}Security")
        if security is None or security.find(f"{{{_DS_NS}}}Signature") is None:
            raise AssertionError("request carried no WS-Security signature")

    def _echo(self, message: etree._Element) -> httpx.Response:
        text = _text(message, "Echo") or ""
        response = self._ack_root("EchoAckMsg", message, message_type=10000)
        data = etree.SubElement(response, f"{{{_ACK_NS}}}EchoData")
        etree.SubElement(data, f"{{{_ACK_NS}}}Echo").text = text
        return self._respond(response)

    def _send(self, message: etree._Element) -> httpx.Response:
        broj = _text(message, "SupplierInvoiceID") or ""
        encoded = _text(message, "InvoiceEnvelope") or _text(message, "CreditNoteEnvelope")
        if encoded:
            self.primljeni[broj] = etree.fromstring(base64.b64decode(encoded))

        response = self._ack_root("SendB2BOutgoingInvoiceAckMsg", message, message_type=10001)
        envelope = etree.SubElement(response, f"{{{_ACK_NS}}}B2BOutgoingInvoiceEnvelope")
        processing = etree.SubElement(envelope, f"{{{_ACK_NS}}}B2BOutgoingInvoiceProcessing")

        errors = self.odbij.get(broj)
        if errors:
            incorrect = etree.SubElement(processing, f"{{{_ACK_NS}}}IncorrectB2BOutgoingInvoice")
            etree.SubElement(incorrect, f"{{{_ACK_NS}}}SupplierInvoiceID").text = broj
            etree.SubElement(incorrect, f"{{{_ACK_NS}}}ErrorCode").text = ";".join(
                code for code, _ in errors
            )
            etree.SubElement(incorrect, f"{{{_ACK_NS}}}ErrorMessage").text = ";".join(
                text for _, text in errors
            )
            return self._respond(response)

        correct = etree.SubElement(processing, f"{{{_ACK_NS}}}CorrectB2BOutgoingInvoice")
        etree.SubElement(correct, f"{{{_ACK_NS}}}SupplierInvoiceID").text = broj
        self._next_id += 1
        etree.SubElement(correct, f"{{{_ACK_NS}}}InvoiceID").text = str(self._next_id)
        return self._respond(response)

    def _status(self, message: etree._Element) -> httpx.Response:
        broj = _text(message, "SupplierInvoiceID") or ""
        response = self._ack_root("GetB2BOutgoingInvoiceStatusAckMsg", message, message_type=10011)
        wrapper = etree.SubElement(response, f"{{{_ACK_NS}}}B2BOutgoingInvoiceStatus")
        etree.SubElement(wrapper, f"{{{_ACK_NS}}}SupplierInvoiceID").text = broj
        etree.SubElement(wrapper, f"{{{_ACK_NS}}}InvoiceID").text = str(self._next_id)
        status = etree.SubElement(wrapper, f"{{{_ACK_NS}}}DocumentStatus")
        # str() so a test can pin an unknown code the enum does not carry.
        etree.SubElement(status, f"{{{_ACK_NS}}}StatusCode").text = str(self.status)
        etree.SubElement(status, f"{{{_ACK_NS}}}StatusTimestamp").text = (
            datetime.now(UTC).replace(microsecond=0, tzinfo=None).isoformat()
        )
        return self._respond(response)

    def _ack_root(self, name: str, request: etree._Element, *, message_type: int) -> etree._Element:
        root = etree.Element(f"{{{_ACK_NS}}}{name}", nsmap={"v0": _ACK_NS, "v01": IWSC})
        ack = etree.SubElement(root, f"{{{IWSC}}}MessageAck")
        etree.SubElement(ack, f"{{{IWSC}}}MessageID").text = "mock-" + str(message_type)
        etree.SubElement(ack, f"{{{IWSC}}}MessageAckID").text = _text(request, "MessageID") or ""
        etree.SubElement(ack, f"{{{IWSC}}}MessageType").text = str(message_type)
        etree.SubElement(ack, f"{{{IWSC}}}AckStatus").text = "ACCEPTED"
        etree.SubElement(ack, f"{{{IWSC}}}AckStatusCode").text = "0"
        return root

    def _respond(self, payload: etree._Element) -> httpx.Response:
        envelope = etree.Element(f"{{{SOAP_ENV_NS}}}Envelope", nsmap={"soapenv": SOAP_ENV_NS})
        body = etree.SubElement(envelope, f"{{{SOAP_ENV_NS}}}Body")
        body.append(payload)
        return httpx.Response(200, content=etree.tostring(envelope))

    def _fault(self, reason: str) -> httpx.Response:
        envelope = etree.Element(f"{{{SOAP_ENV_NS}}}Envelope", nsmap={"soapenv": SOAP_ENV_NS})
        body = etree.SubElement(envelope, f"{{{SOAP_ENV_NS}}}Body")
        fault = etree.SubElement(body, f"{{{SOAP_ENV_NS}}}Fault")
        etree.SubElement(fault, "faultcode").text = "soapenv:Client"
        etree.SubElement(fault, "faultstring").text = reason
        return httpx.Response(500, content=etree.tostring(envelope))


def _text(parent: etree._Element, name: str) -> str | None:
    for element in parent.iter():
        if isinstance(element.tag, str) and etree.QName(element).localname == name:
            return element.text
    return None
