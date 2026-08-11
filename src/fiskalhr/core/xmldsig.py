"""Enveloped XML-DSig signing and verification (F1 tech spec v2.7, ch. 7).

The profile is fixed by the specification:

- the **root element of the request** is signed ("XML enveloped signature"),
  and carries an ``Id`` attribute referenced as ``<Reference URI="#...">``;
- ``CanonicalizationMethod`` for requests is Exclusive XML Canonicalization
  (``xml-exc-c14n``); transforms are ``enveloped-signature`` + ``exc-c14n``;
- signature method is RSA-SHA256 (RSA-SHA1 legacy — see
  `fiskalhr.core.signing` for the migration timeline), digest follows suit;
- ``KeyInfo`` carries the signer certificate as ``X509Certificate`` plus
  ``X509IssuerSerial``, as in the spec example;
- the CIS **response** is signed with *inclusive* c14n
  (``REC-xml-c14n-20010315``) and mirrors the request's signature method, so
  verification accepts both canonicalization and both signature methods.

Verification is secure by default: a caller must either provide the expected
certificate or opt in, loudly, to trusting the certificate embedded in the
document (`trust_embedded_certificate=True`). Trusting the embedded
certificate only proves the document is internally consistent — response
authenticity additionally requires checking *whose* certificate it is, which
the F1 client layer does.

Implementation is delegated to `signxml` (lxml-based); the tests in
``tests/test_xmldsig.py`` pin the produced XML to the spec profile so a
library upgrade cannot silently change the wire format.
"""

from __future__ import annotations

import base64

from cryptography import x509
from lxml import etree
from signxml.algorithms import CanonicalizationMethod as _SxC14N
from signxml.algorithms import DigestAlgorithm as _SxDigest
from signxml.algorithms import SignatureConstructionMethod
from signxml.algorithms import SignatureMethod as _SxMethod
from signxml.exceptions import InvalidInput, InvalidSignature
from signxml.signer import XMLSigner
from signxml.verifier import SignatureConfiguration, XMLVerifier

from fiskalhr.core.certs import Certificate
from fiskalhr.core.errors import SignatureVerificationError
from fiskalhr.core.signing import SignatureMethod

__all__ = ["sign_enveloped", "verify_enveloped"]

_DS_NS = "http://www.w3.org/2000/09/xmldsig#"

_SIGNXML_PARAMS: dict[SignatureMethod, tuple[_SxMethod, _SxDigest]] = {
    SignatureMethod.RSA_SHA256: (_SxMethod.RSA_SHA256, _SxDigest.SHA256),
    SignatureMethod.RSA_SHA1: (_SxMethod.RSA_SHA1, _SxDigest.SHA1),
}

# What the CIS may legitimately use during the SHA-1 -> SHA-256 transition.
_VERIFY_CONFIG = SignatureConfiguration(
    signature_methods=frozenset({_SxMethod.RSA_SHA256, _SxMethod.RSA_SHA1}),
    digest_algorithms=frozenset({_SxDigest.SHA256, _SxDigest.SHA1}),
)


class _LegacySha1Signer(XMLSigner):
    """XMLSigner that permits RSA-SHA1.

    signxml refuses SHA-1 by default (correctly). The F1 production
    environment still accepts RSA-SHA1 until the end of 2026, so this
    subclass exists solely for that transition period and is used only when
    the caller explicitly asks for ``SignatureMethod.RSA_SHA1``.
    """

    def check_deprecated_methods(self) -> None:
        pass


XmlInput = bytes | etree._Element


def _as_element(xml: XmlInput) -> etree._Element:
    if isinstance(xml, bytes):
        try:
            return etree.fromstring(xml)
        except etree.XMLSyntaxError as exc:
            raise SignatureVerificationError(f"document is not well-formed XML: {exc}") from exc
    return xml


def sign_enveloped(
    xml: XmlInput,
    certificate: Certificate,
    *,
    method: SignatureMethod = SignatureMethod.RSA_SHA256,
) -> bytes:
    """Sign a request document with an enveloped signature per the spec profile.

    Args:
        xml: The document (bytes or lxml element). Its root element must
            carry an ``Id`` attribute (the schema defines one per message,
            e.g. ``Id="RacunZahtjev"``); the signature references it.
        certificate: The signer's certificate (FISKAL / demo certificate).
        method: RSA-SHA256 by default; RSA-SHA1 only for the production
            transition period (rejected by the test environment).

    Returns:
        The serialised document with the ``<Signature>`` element appended
        inside the root element.
    """
    root = _as_element(xml)
    reference_id = root.get("Id")
    if reference_id is None:
        raise ValueError(
            "the root element must carry an Id attribute to sign (spec v2.7, ch. 7); "
            f"got <{root.tag}> without one"
        )

    signature_algorithm, digest_algorithm = _SIGNXML_PARAMS[method]
    signer_cls = XMLSigner if method is SignatureMethod.RSA_SHA256 else _LegacySha1Signer
    signer = signer_cls(
        method=SignatureConstructionMethod.enveloped,
        signature_algorithm=signature_algorithm,
        digest_algorithm=digest_algorithm,
        c14n_algorithm=_SxC14N.EXCLUSIVE_XML_CANONICALIZATION_1_0,
    )
    signed = signer.sign(
        root,
        key=certificate.private_key,
        cert=[certificate.certificate],
        reference_uri=f"#{reference_id}",
        id_attribute="Id",
    )
    _append_issuer_serial(signed, certificate.certificate)
    return etree.tostring(signed)


def verify_enveloped(
    xml: XmlInput,
    *,
    expected_certificate: x509.Certificate | None = None,
    trust_embedded_certificate: bool = False,
) -> x509.Certificate:
    """Verify an enveloped signature and return the certificate that signed it.

    Args:
        xml: The signed document (bytes or lxml element).
        expected_certificate: The certificate the signature must verify
            against (e.g. the CIS ``fiskalcis`` / ``fiskalcistest``
            certificate for responses).
        trust_embedded_certificate: Explicitly opt in to verifying against
            whatever certificate the document itself embeds. This proves
            internal consistency only — the caller must still decide whether
            that certificate is trustworthy.

    Raises:
        SignatureVerificationError: If the signature does not verify, the
            document is malformed, or no trust source was provided.
    """
    if expected_certificate is None and not trust_embedded_certificate:
        raise SignatureVerificationError(
            "no trusted certificate provided: pass expected_certificate, or set "
            "trust_embedded_certificate=True to explicitly trust the embedded one"
        )

    root = _as_element(xml)
    certificate = (
        expected_certificate if expected_certificate is not None else _embedded_certificate(root)
    )
    try:
        XMLVerifier().verify(
            root,
            x509_cert=certificate,
            id_attribute="Id",
            expect_config=_VERIFY_CONFIG,
        )
    except (InvalidSignature, InvalidInput, ValueError) as exc:
        raise SignatureVerificationError(f"XML signature verification failed: {exc}") from exc
    return certificate


def _embedded_certificate(root: etree._Element) -> x509.Certificate:
    """Extract the signer certificate from ``KeyInfo/X509Data/X509Certificate``."""
    element = root.find(f".//{{{_DS_NS}}}X509Certificate")
    if element is None or not element.text:
        raise SignatureVerificationError("document embeds no X509Certificate to verify against")
    try:
        der = base64.b64decode(element.text, validate=False)
        return x509.load_der_x509_certificate(der)
    except ValueError as exc:
        raise SignatureVerificationError(f"embedded X509Certificate is invalid: {exc}") from exc


def _append_issuer_serial(signed_root: etree._Element, certificate: x509.Certificate) -> None:
    """Add ``X509IssuerSerial`` next to the embedded certificate.

    The spec example carries issuer name and serial alongside the
    certificate. ``KeyInfo`` is outside the signed content (only
    ``SignedInfo`` is signed), so appending it after signing is legal and
    cannot invalidate the signature.
    """
    x509_data = signed_root.find(f".//{{{_DS_NS}}}X509Data")
    if x509_data is None:  # pragma: no cover — signxml always emits X509Data here
        return
    issuer_serial = etree.SubElement(x509_data, f"{{{_DS_NS}}}X509IssuerSerial")
    issuer_name = etree.SubElement(issuer_serial, f"{{{_DS_NS}}}X509IssuerName")
    issuer_name.text = certificate.issuer.rfc4514_string()
    serial_number = etree.SubElement(issuer_serial, f"{{{_DS_NS}}}X509SerialNumber")
    serial_number.text = str(certificate.serial_number)
