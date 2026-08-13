"""XAdES-B enveloped signing and verification (F2 tech spec, ch. 11).

Fiskalizacija 2.0 request/response messages are signed with the XAdES
Baseline B profile (ETSI EN 319 132-1), realised as an XML enveloped
signature over the message root. The spec fixes the profile:

- ``SignedInfo`` canonicalization is exclusive c14n; signature method is
  RSA-SHA256; digests are SHA-256;
- one ``Reference`` covers the message root (transforms
  ``enveloped-signature`` + ``exc-c14n``), a second covers the XAdES
  ``SignedProperties`` (``exc-c14n``);
- ``KeyInfo`` carries the signer certificate as ``X509Certificate``;
- ``ds:Object/xades:QualifyingProperties/xades:SignedProperties`` holds
  ``SigningTime`` and ``SigningCertificateV2``.

Unlike F1 (`fiskhr.core.xmldsig`), the message root's ``id`` attribute is
a plain ``xsd:string``, not an ``xsd:ID`` — so the data reference uses
``URI=""`` (the whole document) with the enveloped-signature transform,
exactly as the spec's own examples do.

Implementation is delegated to `signxml`'s XAdES support; the tests pin the
produced XML to the spec profile (two references, no ``KeyValue``) so a
library upgrade cannot silently change the wire format.
"""

from __future__ import annotations

from typing import Any

from cryptography import x509
from lxml import etree
from signxml.algorithms import CanonicalizationMethod as _SxC14N
from signxml.algorithms import DigestAlgorithm as _SxDigest
from signxml.algorithms import SignatureConstructionMethod
from signxml.algorithms import SignatureMethod as _SxMethod
from signxml.exceptions import InvalidInput, InvalidSignature
from signxml.xades.xades import XAdESSignatureConfiguration, XAdESSigner, XAdESVerifier

from fiskhr.core.certs import Certificate
from fiskhr.core.errors import SignatureVerificationError
from fiskhr.core.xmldsig import XmlInput, _as_element, _embedded_certificate

__all__ = ["sign_xades_enveloped", "verify_xades_enveloped"]

_DS_NS = "http://www.w3.org/2000/09/xmldsig#"

# The server may legitimately sign its KeyInfo as a third reference (some
# XAdES stacks do); ours emits exactly the two the spec describes.
_VERIFY_CONFIG = XAdESSignatureConfiguration(
    signature_methods=frozenset({_SxMethod.RSA_SHA256}),
    digest_algorithms=frozenset({_SxDigest.SHA256, _SxDigest.SHA512}),
    expect_references=True,
    default_reference_c14n_method=_SxC14N.EXCLUSIVE_XML_CANONICALIZATION_1_0,
)


class _SpecProfileSigner(XAdESSigner):
    """XAdESSigner trimmed to the spec profile.

    The spec expects exactly two references — the message root and the
    XAdES ``SignedProperties`` — while signxml also references ``KeyInfo``
    by default. Skipping that reference keeps the wire format identical to
    the spec's examples.
    """

    def _add_reference_to_signed_info(
        self, sig_root: etree._Element, node_to_reference: etree._Element, **attrs: Any
    ) -> None:
        if node_to_reference.tag == f"{{{_DS_NS}}}KeyInfo":
            return
        super()._add_reference_to_signed_info(  # type: ignore[no-untyped-call]
            sig_root, node_to_reference, **attrs
        )


def sign_xades_enveloped(xml: XmlInput, certificate: Certificate) -> etree._Element:
    """Sign an F2 message with a XAdES-B enveloped signature.

    Args:
        xml: The message document (bytes or lxml element); the ``Signature``
            element is appended inside the root, where the schema puts it.
        certificate: The taxpayer's application certificate (the DN must
            contain the OIB for the real service to accept it).

    Returns:
        The root element with the signature appended.
    """
    root = _as_element(xml)
    signer = _SpecProfileSigner(
        method=SignatureConstructionMethod.enveloped,
        signature_algorithm=_SxMethod.RSA_SHA256,
        digest_algorithm=_SxDigest.SHA256,
        c14n_algorithm=_SxC14N.EXCLUSIVE_XML_CANONICALIZATION_1_0,
    )
    signed: etree._Element = signer.sign(
        root,
        key=certificate.private_key,
        cert=[certificate.certificate],
        always_add_key_value=False,
    )
    return signed


def verify_xades_enveloped(
    xml: XmlInput,
    *,
    expected_certificate: x509.Certificate | None = None,
    trust_embedded_certificate: bool = False,
) -> x509.Certificate:
    """Verify a XAdES enveloped signature; return the signing certificate.

    Mirrors `fiskhr.core.xmldsig.verify_enveloped`: a caller must either
    pin the expected certificate or opt in, loudly, to trusting the one the
    document embeds (which proves internal consistency only).

    Raises:
        SignatureVerificationError: If the signature does not verify, the
            signed content is not the message root, the document is
            malformed, or no trust source was provided.
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
        results = XAdESVerifier().verify(
            root,
            x509_cert=certificate,
            expect_config=_VERIFY_CONFIG,
        )
    except (InvalidSignature, InvalidInput, ValueError) as exc:
        raise SignatureVerificationError(f"XAdES signature verification failed: {exc}") from exc

    # The whole-document reference (URI="") must actually cover the message
    # root — a signature over only its own SignedProperties proves nothing.
    if not any(
        result.signed_xml is not None
        and isinstance(result.signed_xml, etree._Element)
        and result.signed_xml.tag == root.tag
        for result in results
    ):
        raise SignatureVerificationError("XAdES signature does not cover the message root element")
    return certificate
