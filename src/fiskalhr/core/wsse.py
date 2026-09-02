"""WS-Security signatures for SOAP envelopes (OASIS WSS 1.0).

FINA's e-Račun services authenticate a caller by a signature over the SOAP
envelope's ``Body``, carried in a ``wsse:Security`` header — a different
mechanism from the Tax Administration's services, where the signature sits
inside the message document itself (`fiskalhr.core.xmldsig` for F1,
`fiskalhr.core.xades` for F2 reporting). A FINA request needs *both*: this
signature on the envelope, and a XAdES signature inside the invoice
(`fiskalhr.f2.ubl.sign`).

The profile below is taken from FINA's own sample requests, which are the
authoritative record of what their service accepts:

- one ``ds:Reference`` covering the ``soapenv:Body``, addressed by a
  ``wsu:Id`` attribute this module adds;
- exclusive c14n throughout, with an ``InclusiveNamespaces`` PrefixList on
  both the reference transform and ``SignedInfo``;
- RSA-SHA256 signatures over SHA-256 digests. FINA's older samples (echo,
  status) still use RSA-SHA1, so their service accepts both; this library
  emits SHA-256 everywhere, matching their newer samples and this project's
  secure-by-default posture;
- ``KeyInfo`` carrying the signer certificate as a
  ``wsse:SecurityTokenReference``/``wsse:KeyIdentifier`` of ValueType
  ``X509v3`` — not a ``ds:X509Data``;
- a ``wsu:Timestamp`` in the header which, matching the samples, is **not**
  itself referenced by the signature.

Written directly against lxml and `cryptography` rather than through
`signxml`: signxml models enveloped/enveloping/detached XML-DSig, and the
WSS token-reference shapes are outside what it constructs. The wire format
is pinned by `tests/test_wsse.py` so an upgrade cannot silently change it.
"""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime, timedelta

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import Encoding
from lxml import etree

from fiskalhr.core.certs import Certificate

__all__ = ["WSSE_NS", "WSU_NS", "sign_envelope_wsse"]

WSSE_NS = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
WSU_NS = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"
_DS_NS = "http://www.w3.org/2000/09/xmldsig#"
_EC_NS = "http://www.w3.org/2001/10/xml-exc-c14n#"
_SOAP_ENV_NS = "http://schemas.xmlsoap.org/soap/envelope/"

_EXC_C14N = "http://www.w3.org/2001/10/xml-exc-c14n#"
_RSA_SHA256 = "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
_SHA256 = "http://www.w3.org/2001/04/xmlenc#sha256"
_BASE64_ENCODING = (
    "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary"
)
_X509V3_VALUE_TYPE = (
    "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-x509-token-profile-1.0#X509v3"
)

_DEFAULT_TTL = timedelta(minutes=5)
"""Timestamp validity window. FINA's own samples use 50 minutes; five is the
WS-Security convention and keeps the replay window small. Widen it only if a
service rejects requests over clock skew."""


def sign_envelope_wsse(
    envelope: etree._Element,
    certificate: Certificate,
    *,
    ttl: timedelta = _DEFAULT_TTL,
    now: datetime | None = None,
) -> etree._Element:
    """Sign a SOAP envelope's ``Body`` with a WS-Security header.

    Args:
        envelope: The SOAP 1.1 envelope. A ``Header`` is inserted before the
            ``Body`` if the envelope has none; the ``Body`` gains a
            ``wsu:Id`` attribute, which is what the signature references.
        certificate: The certificate FINA issued for this service. Its OIB
            must match the one in the invoice, or the message is rejected
            before it enters their system.
        ttl: How long the ``wsu:Timestamp`` stays valid.
        now: Signing moment, for reproducible tests. Defaults to now (UTC).

    Returns:
        The same envelope element, signed in place.

    Raises:
        ValueError: If the element is not a SOAP 1.1 envelope with a body.
    """
    if envelope.tag != f"{{{_SOAP_ENV_NS}}}Envelope":
        raise ValueError(f"expected a SOAP 1.1 Envelope, got {envelope.tag!r}")
    body = envelope.find(f"{{{_SOAP_ENV_NS}}}Body")
    if body is None:
        raise ValueError("SOAP envelope has no Body to sign")

    moment = (now if now is not None else datetime.now(UTC)).astimezone(UTC)
    token = uuid.uuid4().hex.upper()

    # Read the message's own prefixes before any signature machinery is
    # added, so the PrefixList names what the payload uses and nothing else —
    # `soapenv v0 v01` in FINA's samples, never the wsse/wsu/ds prefixes.
    prefixes = _prefix_list(envelope, body)

    body_id = f"id-{token}"
    body.set(f"{{{WSU_NS}}}Id", body_id)

    header = envelope.find(f"{{{_SOAP_ENV_NS}}}Header")
    if header is None:
        header = etree.Element(f"{{{_SOAP_ENV_NS}}}Header")
        envelope.insert(0, header)

    security = etree.SubElement(header, f"{{{WSSE_NS}}}Security")
    security.set(f"{{{_SOAP_ENV_NS}}}mustUnderstand", "1")
    _timestamp(security, token=token, moment=moment, ttl=ttl)

    # Without an explicit declaration lxml invents a prefix (`ns0`) for the
    # namespace of the `wsu:Id` attribute added above. Declaring wsse and wsu
    # at the root keeps the wire format readable and matches the samples.
    declared = {prefix: uri for prefix, uri in envelope.nsmap.items() if prefix is not None}
    etree.cleanup_namespaces(envelope, top_nsmap={**declared, "wsse": WSSE_NS, "wsu": WSU_NS})

    digest = _digest(body, prefixes=_without_soap_prefix(envelope, prefixes))

    # The prefixes are declared here, before signing: exclusive c14n emits
    # them literally, so renaming them afterwards would invalidate the
    # signature. `ds` and `ec` match FINA's samples.
    signature = etree.SubElement(security, f"{{{_DS_NS}}}Signature", nsmap={"ds": _DS_NS})
    signature.set("Id", f"SIG-{token}")
    signed_info = _signed_info(
        signature,
        reference_uri=f"#{body_id}",
        digest=digest,
        signed_info_prefixes=prefixes,
        reference_prefixes=_without_soap_prefix(envelope, prefixes),
    )

    signed = certificate.private_key.sign(
        _c14n(signed_info, prefixes=prefixes), padding.PKCS1v15(), hashes.SHA256()
    )
    value = etree.SubElement(signature, f"{{{_DS_NS}}}SignatureValue")
    value.text = base64.b64encode(signed).decode("ascii")
    _key_info(signature, certificate=certificate, token=token)
    return envelope


def _timestamp(
    security: etree._Element, *, token: str, moment: datetime, ttl: timedelta
) -> etree._Element:
    timestamp = etree.SubElement(security, f"{{{WSU_NS}}}Timestamp")
    timestamp.set(f"{{{WSU_NS}}}Id", f"TS-{token}")
    created = etree.SubElement(timestamp, f"{{{WSU_NS}}}Created")
    created.text = _instant(moment)
    expires = etree.SubElement(timestamp, f"{{{WSU_NS}}}Expires")
    expires.text = _instant(moment + ttl)
    return timestamp


def _signed_info(
    signature: etree._Element,
    *,
    reference_uri: str,
    digest: str,
    signed_info_prefixes: tuple[str, ...],
    reference_prefixes: tuple[str, ...],
) -> etree._Element:
    signed_info = etree.SubElement(signature, f"{{{_DS_NS}}}SignedInfo")
    c14n = etree.SubElement(signed_info, f"{{{_DS_NS}}}CanonicalizationMethod")
    c14n.set("Algorithm", _EXC_C14N)
    _inclusive_namespaces(c14n, signed_info_prefixes)
    method = etree.SubElement(signed_info, f"{{{_DS_NS}}}SignatureMethod")
    method.set("Algorithm", _RSA_SHA256)

    reference = etree.SubElement(signed_info, f"{{{_DS_NS}}}Reference")
    reference.set("URI", reference_uri)
    transforms = etree.SubElement(reference, f"{{{_DS_NS}}}Transforms")
    transform = etree.SubElement(transforms, f"{{{_DS_NS}}}Transform")
    transform.set("Algorithm", _EXC_C14N)
    _inclusive_namespaces(transform, reference_prefixes)
    digest_method = etree.SubElement(reference, f"{{{_DS_NS}}}DigestMethod")
    digest_method.set("Algorithm", _SHA256)
    digest_value = etree.SubElement(reference, f"{{{_DS_NS}}}DigestValue")
    digest_value.text = digest
    return signed_info


def _key_info(signature: etree._Element, *, certificate: Certificate, token: str) -> None:
    key_info = etree.SubElement(signature, f"{{{_DS_NS}}}KeyInfo")
    key_info.set("Id", f"KI-{token}")
    reference = etree.SubElement(key_info, f"{{{WSSE_NS}}}SecurityTokenReference")
    reference.set(f"{{{WSU_NS}}}Id", f"STR-{token}")
    identifier = etree.SubElement(reference, f"{{{WSSE_NS}}}KeyIdentifier")
    identifier.set("EncodingType", _BASE64_ENCODING)
    identifier.set("ValueType", _X509V3_VALUE_TYPE)
    der = certificate.certificate.public_bytes(Encoding.DER)
    identifier.text = base64.b64encode(der).decode("ascii")


def _inclusive_namespaces(parent: etree._Element, prefixes: tuple[str, ...]) -> None:
    if not prefixes:
        return
    element = etree.SubElement(parent, f"{{{_EC_NS}}}InclusiveNamespaces", nsmap={"ec": _EC_NS})
    element.set("PrefixList", " ".join(prefixes))


def _prefix_list(envelope: etree._Element, body: etree._Element) -> tuple[str, ...]:
    """Every namespace prefix the message uses, in document order.

    These go into ``InclusiveNamespaces`` so that exclusive c14n keeps the
    declarations the receiver needs to resolve the message's own QNames,
    exactly as FINA's samples do (``PrefixList="soapenv v0 v01"``). The
    payload usually declares its own prefixes on its root rather than on the
    envelope, so the whole body subtree is walked, not just the envelope.
    """
    prefixes: list[str] = []
    for element in (envelope, *body.iter()):
        for prefix in element.nsmap:
            if prefix is not None and prefix not in prefixes:
                prefixes.append(prefix)
    return tuple(prefixes)


def _without_soap_prefix(envelope: etree._Element, prefixes: tuple[str, ...]) -> tuple[str, ...]:
    """The prefix list for the Body reference: the payload's prefixes only.

    The SOAP envelope prefix is dropped — the Body's own subtree does not use
    it, and FINA's samples leave it out of the reference transform while
    keeping it on ``SignedInfo``.
    """
    soap_prefixes = {
        prefix for prefix, uri in envelope.nsmap.items() if uri == _SOAP_ENV_NS and prefix
    }
    return tuple(prefix for prefix in prefixes if prefix not in soap_prefixes)


def _c14n(element: etree._Element, *, prefixes: tuple[str, ...]) -> bytes:
    data: bytes = etree.tostring(
        element,
        method="c14n",
        exclusive=True,
        with_comments=False,
        inclusive_ns_prefixes=list(prefixes) or None,
    )
    return data


def _digest(element: etree._Element, *, prefixes: tuple[str, ...]) -> str:
    sha = hashes.Hash(hashes.SHA256())
    sha.update(_c14n(element, prefixes=prefixes))
    return base64.b64encode(sha.finalize()).decode("ascii")


def _instant(moment: datetime) -> str:
    """WS-Security timestamps are UTC, second precision, with a ``Z`` suffix."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
