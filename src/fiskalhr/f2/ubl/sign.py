"""XAdES signatures inside an eRačun's own ``UBLExtensions``.

`fiskalhr.f2.ubl.xml.to_xml` emits the document with an empty signature slot
— `ext:UBLExtensions/ext:UBLExtension/ext:ExtensionContent/`
`sig:UBLDocumentSignatures/sac:SignatureInformation`. HR-BR-33 explicitly
permits that element to stay empty (it is the one element the "no empty
elements" rule exempts), and the Tax Administration's own examples ship it
empty, so an unsigned eRačun is valid. Delivery is where it stops being
optional: FINA requires the invoice XML to be signed, and checks that the
OIB inside it matches the OIB of the signing certificate.

This is the third signature profile in the library and it is nobody else's:

- `fiskalhr.core.xmldsig` — F1 messages to CIS, enveloped, `URI=""` with the
  enveloped-signature transform;
- `fiskalhr.core.xades` — F2 reporting messages, XAdES-B with
  ``SigningCertificateV2``;
- this module — the invoice document, whose data reference uses an **XPath
  transform** (``not(ancestor-or-self::sig:UBLDocumentSignatures)``) instead
  of the enveloped-signature transform, and whose signed properties carry
  ``xades:SigningCertificate`` (ETSI v1.3.2) rather than the V2 element.

The XPath filter is what makes the signature self-consistent: it excludes
the whole ``UBLDocumentSignatures`` subtree, so the digest is the same
before and after the signature is inserted, and a second signature can be
added later without invalidating the first. Its ancestors
(``UBLExtensions``, ``UBLExtension``, ``ExtensionContent``) stay inside the
digest, empty.

Per XML-DSig §4.3.3.2 the node-set an XPath transform yields is serialised
with *inclusive* c14n unless a later transform says otherwise, which is why
the data reference below is canonicalised inclusively while ``SignedInfo``
and ``SignedProperties`` use exclusive c14n.

The profile is taken from FINA's sample requests and pinned by
`tests/test_ubl_sign.py`; their interface definitions are deliberately not
vendored (see `docs/specs/SOURCES.md`).
"""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import Encoding
from lxml import etree

from fiskalhr.core.certs import Certificate
from fiskalhr.f2.ubl.xml import EXT, SAC, SIG

__all__ = ["XADES_NS", "sign_eracun"]

_DS_NS = "http://www.w3.org/2000/09/xmldsig#"
XADES_NS = "http://uri.etsi.org/01903/v1.3.2#"

_EXC_C14N = "http://www.w3.org/2001/10/xml-exc-c14n#"
_XPATH_TRANSFORM = "http://www.w3.org/TR/1999/REC-xpath-19991116"
_RSA_SHA256 = "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
_SHA256 = "http://www.w3.org/2001/04/xmlenc#sha256"
_SIGNED_PROPERTIES_TYPE = "http://uri.etsi.org/01903#SignedProperties"

_EXCLUDE_SIGNATURES = "not(ancestor-or-self::sig:UBLDocumentSignatures)"


def sign_eracun(
    document: etree._Element,
    certificate: Certificate,
    *,
    now: datetime | None = None,
) -> etree._Element:
    """Sign an eRačun in place, into its ``UBLDocumentSignatures`` slot.

    Args:
        document: A UBL ``Invoice`` or ``CreditNote`` element, as produced by
            `fiskalhr.f2.ubl.xml.to_xml`. The signature slot is created if
            the document does not already carry one.
        certificate: The signing certificate. For delivery through FINA its
            OIB must match the issuer OIB in the document, or the message is
            rejected before it enters their system — the ``Posrednik``
            adapter checks that before sending.
        now: Signing moment, for reproducible tests. Defaults to now (UTC).

    Returns:
        The same document element, signed in place.
    """
    moment = (now if now is not None else datetime.now(UTC)).astimezone(UTC)
    slot = _signature_slot(document)
    token = uuid.uuid4()
    signature_id = f"Signature-{token}"
    properties_id = f"SignedProperties-{token}"

    # Computed before the signature exists; the XPath transform makes this
    # identical to what a verifier computes once it does.
    document_digest = _digest(_without_signatures(document), exclusive=False)

    # FINA's samples put the signature in a default namespace; a `ds:`
    # prefix is equivalent (c14n resolves prefixes) and keeps the tree
    # readable next to the surrounding UBL default namespace.
    signature = etree.SubElement(slot, f"{{{_DS_NS}}}Signature", nsmap={"ds": _DS_NS})
    signature.set("Id", signature_id)

    signed_properties = _qualifying_properties(
        signature,
        certificate=certificate,
        moment=moment,
        signature_id=signature_id,
        properties_id=properties_id,
    )
    properties_digest = _digest(signed_properties, exclusive=True)

    signed_info = _signed_info(
        document_digest=document_digest,
        properties_digest=properties_digest,
        properties_id=properties_id,
    )
    signature.insert(0, signed_info)

    signed = certificate.private_key.sign(
        _c14n(signed_info, exclusive=True), padding.PKCS1v15(), hashes.SHA256()
    )
    value = etree.Element(f"{{{_DS_NS}}}SignatureValue")
    value.text = base64.b64encode(signed).decode("ascii")
    signature.insert(1, value)
    signature.insert(2, _key_info(certificate))
    return document


def _signature_slot(document: etree._Element) -> etree._Element:
    """The ``sac:SignatureInformation`` element, created if absent."""
    slot = document.find(
        f"{{{EXT}}}UBLExtensions/{{{EXT}}}UBLExtension/{{{EXT}}}ExtensionContent/"
        f"{{{SIG}}}UBLDocumentSignatures/{{{SAC}}}SignatureInformation"
    )
    if slot is not None:
        return slot

    extensions = document.find(f"{{{EXT}}}UBLExtensions")
    if extensions is None:
        extensions = etree.Element(f"{{{EXT}}}UBLExtensions")
        document.insert(0, extensions)
    extension = etree.SubElement(extensions, f"{{{EXT}}}UBLExtension")
    content = etree.SubElement(extension, f"{{{EXT}}}ExtensionContent")
    signatures = etree.SubElement(content, f"{{{SIG}}}UBLDocumentSignatures")
    return etree.SubElement(signatures, f"{{{SAC}}}SignatureInformation")


def _without_signatures(document: etree._Element) -> etree._Element:
    """A copy of the document with every ``UBLDocumentSignatures`` removed.

    This is what the XPath transform selects. The subtree's ancestors are
    kept — the filter drops only nodes that have a ``UBLDocumentSignatures``
    ancestor-or-self — so they remain in the digest as empty elements.
    """
    copy = etree.fromstring(etree.tostring(document))
    for signatures in copy.iter(f"{{{SIG}}}UBLDocumentSignatures"):
        parent = signatures.getparent()
        if parent is not None:
            parent.remove(signatures)
    return copy


def _signed_info(
    *, document_digest: str, properties_digest: str, properties_id: str
) -> etree._Element:
    signed_info = etree.Element(f"{{{_DS_NS}}}SignedInfo")
    etree.SubElement(signed_info, f"{{{_DS_NS}}}CanonicalizationMethod").set("Algorithm", _EXC_C14N)
    etree.SubElement(signed_info, f"{{{_DS_NS}}}SignatureMethod").set("Algorithm", _RSA_SHA256)

    document_reference = etree.SubElement(signed_info, f"{{{_DS_NS}}}Reference")
    document_reference.set("URI", "")
    transforms = etree.SubElement(document_reference, f"{{{_DS_NS}}}Transforms")
    transform = etree.SubElement(transforms, f"{{{_DS_NS}}}Transform")
    transform.set("Algorithm", _XPATH_TRANSFORM)
    # The expression names the sig: prefix, so it has to be in scope here.
    xpath = etree.SubElement(transform, f"{{{_DS_NS}}}XPath", nsmap={"sig": SIG})
    xpath.text = _EXCLUDE_SIGNATURES
    _digest_elements(document_reference, document_digest)

    properties_reference = etree.SubElement(signed_info, f"{{{_DS_NS}}}Reference")
    properties_reference.set("URI", f"#{properties_id}")
    properties_reference.set("Type", _SIGNED_PROPERTIES_TYPE)
    properties_transforms = etree.SubElement(properties_reference, f"{{{_DS_NS}}}Transforms")
    etree.SubElement(properties_transforms, f"{{{_DS_NS}}}Transform").set("Algorithm", _EXC_C14N)
    _digest_elements(properties_reference, properties_digest)
    return signed_info


def _digest_elements(reference: etree._Element, digest: str) -> None:
    etree.SubElement(reference, f"{{{_DS_NS}}}DigestMethod").set("Algorithm", _SHA256)
    etree.SubElement(reference, f"{{{_DS_NS}}}DigestValue").text = digest


def _key_info(certificate: Certificate) -> etree._Element:
    key_info = etree.Element(f"{{{_DS_NS}}}KeyInfo")
    data = etree.SubElement(key_info, f"{{{_DS_NS}}}X509Data")
    element = etree.SubElement(data, f"{{{_DS_NS}}}X509Certificate")
    element.text = _base64(certificate.certificate)
    return key_info


def _qualifying_properties(
    signature: etree._Element,
    *,
    certificate: Certificate,
    moment: datetime,
    signature_id: str,
    properties_id: str,
) -> etree._Element:
    obj = etree.SubElement(signature, f"{{{_DS_NS}}}Object")
    qualifying = etree.SubElement(
        obj, f"{{{XADES_NS}}}QualifyingProperties", nsmap={"xades": XADES_NS}
    )
    qualifying.set("Target", f"#{signature_id}")
    signed_properties = etree.SubElement(qualifying, f"{{{XADES_NS}}}SignedProperties")
    signed_properties.set("Id", properties_id)
    signature_properties = etree.SubElement(
        signed_properties, f"{{{XADES_NS}}}SignedSignatureProperties"
    )
    signing_time = etree.SubElement(signature_properties, f"{{{XADES_NS}}}SigningTime")
    signing_time.text = moment.strftime("%Y-%m-%dT%H:%M:%SZ")

    signing_certificate = etree.SubElement(
        signature_properties, f"{{{XADES_NS}}}SigningCertificate"
    )
    for certificate_in_chain in (certificate.certificate, *certificate.chain):
        _cert(signing_certificate, certificate_in_chain)
    return signed_properties


def _cert(parent: etree._Element, certificate: x509.Certificate) -> None:
    cert = etree.SubElement(parent, f"{{{XADES_NS}}}Cert")
    cert_digest = etree.SubElement(cert, f"{{{XADES_NS}}}CertDigest")
    etree.SubElement(cert_digest, f"{{{_DS_NS}}}DigestMethod").set("Algorithm", _SHA256)
    sha = hashes.Hash(hashes.SHA256())
    sha.update(certificate.public_bytes(Encoding.DER))
    etree.SubElement(cert_digest, f"{{{_DS_NS}}}DigestValue").text = base64.b64encode(
        sha.finalize()
    ).decode("ascii")

    issuer_serial = etree.SubElement(cert, f"{{{XADES_NS}}}IssuerSerial")
    etree.SubElement(
        issuer_serial, f"{{{_DS_NS}}}X509IssuerName"
    ).text = certificate.issuer.rfc4514_string()
    etree.SubElement(issuer_serial, f"{{{_DS_NS}}}X509SerialNumber").text = str(
        certificate.serial_number
    )


def _base64(certificate: x509.Certificate) -> str:
    return base64.b64encode(certificate.public_bytes(Encoding.DER)).decode("ascii")


def _c14n(element: etree._Element, *, exclusive: bool) -> bytes:
    data: bytes = etree.tostring(element, method="c14n", exclusive=exclusive, with_comments=False)
    return data


def _digest(element: etree._Element, *, exclusive: bool) -> str:
    sha = hashes.Hash(hashes.SHA256())
    sha.update(_c14n(element, exclusive=exclusive))
    return base64.b64encode(sha.finalize()).decode("ascii")
