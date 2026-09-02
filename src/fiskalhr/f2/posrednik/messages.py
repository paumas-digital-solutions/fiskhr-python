"""FINA e-Račun B2B message construction and parsing.

FINA's WSDL and XSDs are not vendored (this is a public repository; see
`docs/specs/SOURCES.md`), so the message shapes below are transcribed from
them rather than validated against them. Every element here comes from
``SendB2BOutgoingInvoiceMsg.xsd``, ``GetB2BOutgoingInvoiceStatusMsg.xsd``,
``EchoMsg.xsd`` and the shared ``InvoiceWebServiceComponents.xsd``; the
tests pin the produced XML so a change is visible in review.

Shared shape of every message: a header (``HeaderSupplier`` for the sending
side) plus a ``Data`` element whose contents differ per message. Documents
travel base64-encoded inside "envelope" elements. Every response carries a
``MessageAck`` whose ``AckStatus`` says whether the *message* was
well-formed — which is separate from whether the *invoice* was accepted.
"""

from __future__ import annotations

import base64
from datetime import datetime

from lxml import etree

from fiskalhr.f2.posrednik.base import (
    Isporuka,
    PosrednikError,
    StatusIsporuke,
    StatusOdgovor,
)

__all__ = [
    "IWSC",
    "MessageType",
    "build_echo",
    "build_send_invoice",
    "build_status_query",
    "parse_echo",
    "parse_send_ack",
    "parse_status_ack",
]

IWSC = "http://fina.hr/eracun/b2b/invoicewebservicecomponents/v0.1"
_ECHO = "http://fina.hr/eracun/b2b/pki/Echo/v0.1"
_SEND = "http://fina.hr/eracun/b2b/pki/SendB2BOutgoingInvoice/v0.1"
_STATUS = "http://fina.hr/eracun/b2b/pki/GetB2BOutgoingInvoiceStatus/v0.1"

OIB_SCHEME = "9934"
"""Identifier scheme for a Croatian OIB, as ``9934:<oib>``."""

_UBL = "UBL"
_CUSTOMIZATION_ID = (
    "urn:cen.eu:en16931:2017#compliant#"
    "urn:mfin.gov.hr:cius-2025:1.0#conformant#urn:mfin.gov.hr:ext-2025:1.0"
)
_CREDIT_NOTE = "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"


class MessageType:
    """FINA message type codes (``HeaderSupplier/MessageType``)."""

    SEND_INVOICE = 9001
    STATUS_QUERY = 9011
    ECHO = 9999


def _header(parent: etree._Element, *, message_id: str, oib: str, message_type: int) -> None:
    header = etree.SubElement(parent, f"{{{IWSC}}}HeaderSupplier")
    etree.SubElement(header, f"{{{IWSC}}}MessageID").text = message_id
    etree.SubElement(header, f"{{{IWSC}}}SupplierID").text = f"{OIB_SCHEME}:{oib}"
    etree.SubElement(header, f"{{{IWSC}}}MessageType").text = str(message_type)


def build_echo(text: str, *, message_id: str, oib: str) -> etree._Element:
    """``EchoMsg`` — a connectivity and credential check."""
    root = etree.Element(f"{{{_ECHO}}}EchoMsg", nsmap={"v0": _ECHO, "v01": IWSC})
    _header(root, message_id=message_id, oib=oib, message_type=MessageType.ECHO)
    data = etree.SubElement(root, f"{{{_ECHO}}}Data")
    echo_data = etree.SubElement(data, f"{{{_ECHO}}}EchoData")
    etree.SubElement(echo_data, f"{{{_ECHO}}}Echo").text = text
    return root


def build_send_invoice(
    document: etree._Element,
    *,
    message_id: str,
    oib: str,
    primatelj_oib: str,
    broj_racuna: str,
) -> etree._Element:
    """``SendB2BOutgoingInvoiceMsg`` (9001) — deliver one eRačun.

    A UBL ``CreditNote`` goes into ``CreditNoteEnvelope`` and an
    ``Invoice`` into ``InvoiceEnvelope``; the two are a schema ``choice``,
    and sending a credit note in the wrong one is rejected.
    """
    root = etree.Element(f"{{{_SEND}}}SendB2BOutgoingInvoiceMsg", nsmap={"v0": _SEND, "v01": IWSC})
    _header(root, message_id=message_id, oib=oib, message_type=MessageType.SEND_INVOICE)
    data = etree.SubElement(root, f"{{{_SEND}}}Data")
    envelope = etree.SubElement(data, f"{{{_SEND}}}B2BOutgoingInvoiceEnvelope")
    etree.SubElement(envelope, f"{{{_SEND}}}XMLStandard").text = _UBL
    etree.SubElement(envelope, f"{{{_SEND}}}SpecificationIdentifier").text = _CUSTOMIZATION_ID
    etree.SubElement(envelope, f"{{{_SEND}}}SupplierInvoiceID").text = broj_racuna
    etree.SubElement(envelope, f"{{{_SEND}}}BuyerID").text = f"{OIB_SCHEME}:{primatelj_oib}"

    serialised = etree.tostring(document, xml_declaration=True, encoding="UTF-8")
    element = "CreditNoteEnvelope" if _is_credit_note(document) else "InvoiceEnvelope"
    etree.SubElement(envelope, f"{{{_SEND}}}{element}").text = base64.b64encode(serialised).decode(
        "ascii"
    )
    return root


def build_status_query(
    broj_racuna: str, *, godina: int, message_id: str, oib: str
) -> etree._Element:
    """``GetB2BOutgoingInvoiceStatusMsg`` (9011).

    The invoice is addressed by the sender's own number plus its year, not
    by FINA's identifier — so a caller that kept only ``InvoiceID`` cannot
    ask this question.
    """
    root = etree.Element(
        f"{{{_STATUS}}}GetB2BOutgoingInvoiceStatusMsg", nsmap={"v0": _STATUS, "v01": IWSC}
    )
    _header(root, message_id=message_id, oib=oib, message_type=MessageType.STATUS_QUERY)
    data = etree.SubElement(root, f"{{{_STATUS}}}Data")
    query = etree.SubElement(data, f"{{{_STATUS}}}B2BOutgoingInvoiceStatus")
    etree.SubElement(query, f"{{{_STATUS}}}SupplierInvoiceID").text = broj_racuna
    etree.SubElement(query, f"{{{_STATUS}}}InvoiceYear").text = str(godina)
    return root


def parse_echo(response: etree._Element) -> str:
    """The echoed text from an ``EchoAckMsg``."""
    _check_ack(response)
    echo = _find_local(response, "Echo")
    if echo is None or echo.text is None:
        raise PosrednikError("echo response carried no Echo element")
    return echo.text


def parse_send_ack(response: etree._Element) -> Isporuka:
    """``SendB2BOutgoingInvoiceAckMsg`` → `Isporuka`.

    Two levels of acceptance, and they fail differently: ``MessageAck``
    covers the SOAP message, then ``B2BOutgoingInvoiceProcessing`` chooses
    between ``CorrectB2BOutgoingInvoice`` and ``IncorrectB2BOutgoingInvoice``
    for the invoice itself. A well-formed message carrying a rejected
    invoice is a normal response, not an error.
    """
    _check_ack(response)

    incorrect = _find_local(response, "IncorrectB2BOutgoingInvoice")
    if incorrect is not None:
        codes = _text(incorrect, "ErrorCode") or ""
        messages = _text(incorrect, "ErrorMessage") or ""
        return Isporuka(
            prihvacen=False,
            broj_racuna=_text(incorrect, "SupplierInvoiceID"),
            greske=_pair_errors(codes, messages),
        )

    correct = _find_local(response, "CorrectB2BOutgoingInvoice")
    if correct is None:
        raise PosrednikError("send response contained neither a correct nor an incorrect invoice")
    return Isporuka(
        prihvacen=True,
        id_posrednika=_text(correct, "InvoiceID"),
        broj_racuna=_text(correct, "SupplierInvoiceID"),
    )


def parse_status_ack(response: etree._Element) -> StatusOdgovor:
    """``GetB2BOutgoingInvoiceStatusAckMsg`` → `StatusOdgovor`."""
    _check_ack(response)
    status_element = _find_local(response, "DocumentStatus")
    if status_element is None:
        raise PosrednikError("status response carried no DocumentStatus")

    code = _text(status_element, "StatusCode") or ""
    try:
        status: StatusIsporuke | None = StatusIsporuke(code)
    except ValueError:
        # An unknown code is reported, not swallowed: FINA can add one
        # without this library having to know it first.
        status = None

    return StatusOdgovor(
        status=status,
        status_kod=code,
        id_posrednika=_text(response, "InvoiceID"),
        vrijeme=_timestamp(_text(status_element, "StatusTimestamp")),
        napomena=_text(status_element, "Note"),
        djelomicni_iznos=_text(status_element, "PartialAmount"),
    )


def _check_ack(response: etree._Element) -> None:
    """Raise unless ``MessageAck/AckStatus`` is ``ACCEPTED``."""
    ack = _find_local(response, "MessageAck")
    if ack is None:
        raise PosrednikError("response carried no MessageAck")
    status = _text(ack, "AckStatus")
    if status == "ACCEPTED":
        return
    code = _text(ack, "AckStatusCode") or ""
    text = _text(ack, "AckStatusText") or ""
    raise PosrednikError(
        f"FINA rejected the message: {status} {code} {text}".rstrip(),
        code=code or None,
        message_hr=text or None,
    )


def _is_credit_note(document: etree._Element) -> bool:
    return etree.QName(document).namespace == _CREDIT_NOTE


def _pair_errors(codes: str, messages: str) -> tuple[tuple[str, str], ...]:
    """FINA packs several errors into one delimited string.

    The XSDs say only "šifre grešaka odvojene delimiterom" without naming
    the delimiter; the samples use ``;``. Codes and messages are zipped
    positionally, and a mismatch in counts leaves the message empty rather
    than pairing the wrong text with a code.
    """
    code_list = [code.strip() for code in codes.split(";") if code.strip()]
    message_list = [message.strip() for message in messages.split(";") if message.strip()]
    if len(code_list) != len(message_list):
        return tuple((code, "") for code in code_list)
    return tuple(zip(code_list, message_list, strict=True))


def _timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _find_local(parent: etree._Element, name: str) -> etree._Element | None:
    """Find a descendant by local name, ignoring its namespace.

    FINA's responses put shared components in the ``iwsc`` namespace and
    per-message elements in the message's own, and the ack namespaces are
    not all documented. Matching on local names keeps parsing robust
    without pinning namespaces this library cannot verify against a schema.
    """
    for element in parent.iter():
        if isinstance(element.tag, str) and etree.QName(element).localname == name:
            return element
    return None


def _text(parent: etree._Element, name: str) -> str | None:
    element = _find_local(parent, name)
    if element is None or element.text is None:
        return None
    return element.text.strip() or None
