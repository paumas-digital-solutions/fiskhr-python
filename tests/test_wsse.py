"""WS-Security envelope signing, pinned to the profile FINA's samples use."""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import Encoding
from lxml import etree

from fiskalhr.core.certs import Certificate
from fiskalhr.core.transport import SOAP_ENV_NS, build_envelope
from fiskalhr.core.wsse import WSSE_NS, WSU_NS, sign_envelope_wsse

DS_NS = "http://www.w3.org/2000/09/xmldsig#"
EC_NS = "http://www.w3.org/2001/10/xml-exc-c14n#"
FINA_NS = "http://fina.hr/eracun/b2b/pki/SendB2BOutgoingInvoice/v0.1"


@pytest.fixture
def certificate(rsa_key: rsa.RSAPrivateKey, self_signed_cert: x509.Certificate) -> Certificate:
    return Certificate(private_key=rsa_key, certificate=self_signed_cert)


def _payload() -> etree._Element:
    payload = etree.Element(f"{{{FINA_NS}}}SendB2BOutgoingInvoiceMsg", nsmap={"v0": FINA_NS})
    etree.SubElement(payload, f"{{{FINA_NS}}}Data").text = "x"
    return payload


def _signed(certificate: Certificate) -> etree._Element:
    return sign_envelope_wsse(build_envelope(_payload()), certificate)


def test_security_header_carries_timestamp_and_signature(certificate: Certificate) -> None:
    envelope = _signed(certificate)

    security = envelope.find(f"{{{SOAP_ENV_NS}}}Header/{{{WSSE_NS}}}Security")
    assert security is not None
    assert security.get(f"{{{SOAP_ENV_NS}}}mustUnderstand") == "1"
    assert security.find(f"{{{WSU_NS}}}Timestamp") is not None
    assert security.find(f"{{{DS_NS}}}Signature") is not None


def test_signature_references_the_body_by_wsu_id(certificate: Certificate) -> None:
    envelope = _signed(certificate)

    body = envelope.find(f"{{{SOAP_ENV_NS}}}Body")
    assert body is not None
    body_id = body.get(f"{{{WSU_NS}}}Id")
    assert body_id is not None

    references = envelope.findall(f".//{{{DS_NS}}}Reference")
    assert len(references) == 1  # the Body only; the Timestamp is not signed
    assert references[0].get("URI") == f"#{body_id}"


def test_algorithms_match_the_spec_profile(certificate: Certificate) -> None:
    envelope = _signed(certificate)

    c14n = envelope.find(f".//{{{DS_NS}}}CanonicalizationMethod")
    method = envelope.find(f".//{{{DS_NS}}}SignatureMethod")
    transform = envelope.find(f".//{{{DS_NS}}}Transform")
    digest = envelope.find(f".//{{{DS_NS}}}DigestMethod")

    assert c14n is not None
    assert c14n.get("Algorithm") == EC_NS
    assert method is not None
    assert method.get("Algorithm") == "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
    assert transform is not None
    assert transform.get("Algorithm") == EC_NS
    assert digest is not None
    assert digest.get("Algorithm") == "http://www.w3.org/2001/04/xmlenc#sha256"


def test_inclusive_namespace_prefix_lists_are_emitted(certificate: Certificate) -> None:
    envelope = _signed(certificate)

    lists = envelope.findall(f".//{{{EC_NS}}}InclusiveNamespaces")
    assert len(lists) == 2  # one on SignedInfo, one on the reference transform

    signed_info_prefixes = lists[0].get("PrefixList", "").split()
    reference_prefixes = lists[1].get("PrefixList", "").split()
    assert "soapenv" in signed_info_prefixes
    assert "v0" in signed_info_prefixes
    # The Body's own subtree does not use the envelope prefix.
    assert "soapenv" not in reference_prefixes
    assert "v0" in reference_prefixes


def test_key_info_uses_a_security_token_reference_not_x509data(
    certificate: Certificate,
) -> None:
    envelope = _signed(certificate)

    assert envelope.find(f".//{{{DS_NS}}}X509Data") is None
    identifier = envelope.find(
        f".//{{{DS_NS}}}KeyInfo/{{{WSSE_NS}}}SecurityTokenReference/{{{WSSE_NS}}}KeyIdentifier"
    )
    assert identifier is not None
    assert identifier.get("ValueType", "").endswith("#X509v3")
    assert identifier.text is not None
    embedded = base64.b64decode(identifier.text)
    assert embedded == certificate.certificate.public_bytes(Encoding.DER)


def test_signature_verifies_against_the_signed_body(certificate: Certificate) -> None:
    envelope = _signed(certificate)

    signed_info = envelope.find(f".//{{{DS_NS}}}SignedInfo")
    signature_value = envelope.find(f".//{{{DS_NS}}}SignatureValue")
    assert signed_info is not None
    assert signature_value is not None
    assert signature_value.text

    prefix_list = signed_info.find(f".//{{{EC_NS}}}InclusiveNamespaces")
    assert prefix_list is not None
    canonical = etree.tostring(
        signed_info,
        method="c14n",
        exclusive=True,
        with_comments=False,
        inclusive_ns_prefixes=prefix_list.get("PrefixList", "").split(),
    )

    public_key = certificate.certificate.public_key()
    assert isinstance(public_key, rsa.RSAPublicKey)
    # Raises InvalidSignature if the envelope was tampered with.
    public_key.verify(
        base64.b64decode(signature_value.text),
        canonical,
        padding.PKCS1v15(),
        hashes.SHA256(),
    )


def test_digest_covers_the_body_contents(certificate: Certificate) -> None:
    envelope = _signed(certificate)
    body = envelope.find(f"{{{SOAP_ENV_NS}}}Body")
    digest_value = envelope.find(f".//{{{DS_NS}}}DigestValue")
    transform_prefixes = envelope.findall(f".//{{{EC_NS}}}InclusiveNamespaces")[1]
    assert body is not None
    assert digest_value is not None

    def digest_of(element: etree._Element) -> str:
        sha = hashes.Hash(hashes.SHA256())
        sha.update(
            etree.tostring(
                element,
                method="c14n",
                exclusive=True,
                with_comments=False,
                inclusive_ns_prefixes=transform_prefixes.get("PrefixList", "").split(),
            )
        )
        return base64.b64encode(sha.finalize()).decode("ascii")

    assert digest_of(body) == digest_value.text

    data = body.find(f".//{{{FINA_NS}}}Data")
    assert data is not None
    data.text = "tampered"
    assert digest_of(body) != digest_value.text


def test_timestamp_window_follows_ttl(certificate: Certificate) -> None:
    moment = datetime(2026, 9, 2, 10, 0, 0, tzinfo=UTC)

    envelope = sign_envelope_wsse(
        build_envelope(_payload()), certificate, ttl=timedelta(minutes=10), now=moment
    )

    timestamp = envelope.find(f".//{{{WSU_NS}}}Timestamp")
    assert timestamp is not None
    assert timestamp.findtext(f"{{{WSU_NS}}}Created") == "2026-09-02T10:00:00Z"
    assert timestamp.findtext(f"{{{WSU_NS}}}Expires") == "2026-09-02T10:10:00Z"


def test_existing_header_is_reused(certificate: Certificate) -> None:
    envelope = build_envelope(_payload())
    header = etree.Element(f"{{{SOAP_ENV_NS}}}Header")
    etree.SubElement(header, "{urn:test}Custom")
    envelope.insert(0, header)

    sign_envelope_wsse(envelope, certificate)

    headers = envelope.findall(f"{{{SOAP_ENV_NS}}}Header")
    assert len(headers) == 1
    assert headers[0].find("{urn:test}Custom") is not None
    assert headers[0].find(f"{{{WSSE_NS}}}Security") is not None


def test_rejects_anything_that_is_not_a_soap_envelope(certificate: Certificate) -> None:
    with pytest.raises(ValueError, match=r"SOAP 1\.1 Envelope"):
        sign_envelope_wsse(_payload(), certificate)
