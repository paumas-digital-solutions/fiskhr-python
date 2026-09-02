"""Invoice-level XAdES signing, pinned to the profile FINA's samples use."""

from __future__ import annotations

import base64
from datetime import UTC, date, datetime, time

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import Encoding
from lxml import etree

from fiskalhr.core.certs import Certificate
from fiskalhr.f2.ubl import ERacunBuilder, to_xml
from fiskalhr.f2.ubl.sign import XADES_NS, sign_eracun
from fiskalhr.f2.ubl.xml import EXT, SAC, SIG
from fiskalhr.f2.validation import validate
from fiskalhr.f2.validation.schematron import schematron_available

needs_saxon = pytest.mark.skipif(
    not schematron_available(), reason="saxonche (fiskalhr[validation]) not installed"
)

DS_NS = "http://www.w3.org/2000/09/xmldsig#"
SLOT = (
    f"{{{EXT}}}UBLExtensions/{{{EXT}}}UBLExtension/{{{EXT}}}ExtensionContent/"
    f"{{{SIG}}}UBLDocumentSignatures/{{{SAC}}}SignatureInformation"
)


@pytest.fixture
def certificate(rsa_key: rsa.RSAPrivateKey, self_signed_cert: x509.Certificate) -> Certificate:
    return Certificate(private_key=rsa_key, certificate=self_signed_cert)


@pytest.fixture
def eracun() -> etree._Element:
    return to_xml(
        ERacunBuilder()
        .izdavatelj(
            oib="12345678903",
            naziv="Tvrtka d.o.o.",
            ulica="Ulica 1",
            grad="Zagreb",
            postanski_broj="10000",
        )
        .primatelj(
            oib="00000000001",
            naziv="Kupac d.o.o.",
            ulica="Ulica 2",
            grad="Rijeka",
            postanski_broj="51000",
        )
        .operater(oib="12345678903", oznaka="Operater1")
        .broj("2026-42-P1-1")
        .datum_izdavanja(date(2026, 8, 13), time(12, 0))
        .dospijece(date(2026, 9, 12))
        .stavka(naziv="Licenca", kpd="62.20.20", kolicina=1, cijena="100.00", pdv_stopa=25)
        .build()
    )


def test_signature_lands_in_the_ubl_signature_slot(
    eracun: etree._Element, certificate: Certificate
) -> None:
    slot = eracun.find(SLOT)
    assert slot is not None
    assert len(slot) == 0  # the builder leaves it empty (HR-BR-33)

    sign_eracun(eracun, certificate)

    signed_slot = eracun.find(SLOT)
    assert signed_slot is not None
    assert signed_slot.find(f"{{{DS_NS}}}Signature") is not None


def test_data_reference_uses_the_xpath_transform_not_enveloped_signature(
    eracun: etree._Element, certificate: Certificate
) -> None:
    sign_eracun(eracun, certificate)

    references = eracun.findall(f".//{{{DS_NS}}}Reference")
    assert len(references) == 2

    document_reference = references[0]
    assert document_reference.get("URI") == ""
    transform = document_reference.find(f".//{{{DS_NS}}}Transform")
    assert transform is not None
    assert transform.get("Algorithm") == "http://www.w3.org/TR/1999/REC-xpath-19991116"
    xpath = transform.find(f"{{{DS_NS}}}XPath")
    assert xpath is not None
    assert xpath.text == "not(ancestor-or-self::sig:UBLDocumentSignatures)"
    assert xpath.nsmap["sig"] == SIG


def test_signed_properties_reference_is_typed_and_exclusive(
    eracun: etree._Element, certificate: Certificate
) -> None:
    sign_eracun(eracun, certificate)

    properties_reference = eracun.findall(f".//{{{DS_NS}}}Reference")[1]
    assert properties_reference.get("Type") == "http://uri.etsi.org/01903#SignedProperties"
    signed_properties = eracun.find(f".//{{{XADES_NS}}}SignedProperties")
    assert signed_properties is not None
    assert properties_reference.get("URI") == f"#{signed_properties.get('Id')}"


def test_uses_signing_certificate_v1_not_v2(
    eracun: etree._Element, certificate: Certificate
) -> None:
    # The Tax Administration's messages (core.xades) use SigningCertificateV2;
    # the invoice profile FINA accepts uses the v1.3.2 element.
    sign_eracun(eracun, certificate)

    assert eracun.find(f".//{{{XADES_NS}}}SigningCertificateV2") is None
    signing_certificate = eracun.find(f".//{{{XADES_NS}}}SigningCertificate")
    assert signing_certificate is not None
    certs = signing_certificate.findall(f"{{{XADES_NS}}}Cert")
    assert len(certs) == 1  # leaf only; a chain adds one Cert each
    issuer_name = certs[0].find(f".//{{{DS_NS}}}X509IssuerName")
    assert issuer_name is not None
    assert issuer_name.text == certificate.certificate.issuer.rfc4514_string()


def test_key_info_embeds_the_signing_certificate(
    eracun: etree._Element, certificate: Certificate
) -> None:
    sign_eracun(eracun, certificate)

    embedded = eracun.find(f".//{{{DS_NS}}}KeyInfo/{{{DS_NS}}}X509Data/{{{DS_NS}}}X509Certificate")
    assert embedded is not None
    assert embedded.text is not None
    assert base64.b64decode(embedded.text) == certificate.certificate.public_bytes(Encoding.DER)


def test_signature_verifies(eracun: etree._Element, certificate: Certificate) -> None:
    sign_eracun(eracun, certificate)

    signed_info = eracun.find(f".//{{{DS_NS}}}SignedInfo")
    signature_value = eracun.find(f".//{{{DS_NS}}}SignatureValue")
    assert signed_info is not None
    assert signature_value is not None
    assert signature_value.text

    public_key = certificate.certificate.public_key()
    assert isinstance(public_key, rsa.RSAPublicKey)
    public_key.verify(
        base64.b64decode(signature_value.text),
        etree.tostring(signed_info, method="c14n", exclusive=True, with_comments=False),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )


def test_document_digest_is_stable_across_signing(
    eracun: etree._Element, certificate: Certificate
) -> None:
    """The XPath filter excludes the signature, so what a verifier digests
    after signing equals what the signer digested before."""

    def digest_of(document: etree._Element) -> str:
        copy = etree.fromstring(etree.tostring(document))
        for signatures in copy.iter(f"{{{SIG}}}UBLDocumentSignatures"):
            parent = signatures.getparent()
            assert parent is not None
            parent.remove(signatures)
        sha = hashes.Hash(hashes.SHA256())
        sha.update(etree.tostring(copy, method="c14n", with_comments=False))
        return base64.b64encode(sha.finalize()).decode("ascii")

    before = digest_of(eracun)
    sign_eracun(eracun, certificate)
    after = digest_of(eracun)

    assert before == after
    digest_value = eracun.find(f".//{{{DS_NS}}}DigestValue")
    assert digest_value is not None
    assert digest_value.text == after


def test_digest_covers_the_invoice_contents(
    eracun: etree._Element, certificate: Certificate
) -> None:
    sign_eracun(eracun, certificate)
    digest_value = eracun.findall(f".//{{{DS_NS}}}DigestValue")[0].text

    total = eracun.find(f".//{{{SIG}}}UBLDocumentSignatures")
    assert total is not None  # sanity: the slot is populated

    copy = etree.fromstring(etree.tostring(eracun))
    identifier = copy.find(
        "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}ID"
    )
    assert identifier is not None
    identifier.text = "TAMPERED"
    for signatures in copy.iter(f"{{{SIG}}}UBLDocumentSignatures"):
        parent = signatures.getparent()
        assert parent is not None
        parent.remove(signatures)
    sha = hashes.Hash(hashes.SHA256())
    sha.update(etree.tostring(copy, method="c14n", with_comments=False))

    assert base64.b64encode(sha.finalize()).decode("ascii") != digest_value


def test_signing_time_is_utc_with_second_precision(
    eracun: etree._Element, certificate: Certificate
) -> None:
    moment = datetime(2026, 9, 2, 10, 30, 15, 123456, tzinfo=UTC)

    sign_eracun(eracun, certificate, now=moment)

    signing_time = eracun.find(f".//{{{XADES_NS}}}SigningTime")
    assert signing_time is not None
    assert signing_time.text == "2026-09-02T10:30:15Z"


@needs_saxon
def test_signed_invoice_still_passes_official_validation(
    eracun: etree._Element, certificate: Certificate
) -> None:
    sign_eracun(eracun, certificate)

    report = validate(etree.tostring(eracun, xml_declaration=True, encoding="UTF-8"))

    assert report.ok, [f"{finding.rule}: {finding.message}" for finding in report.findings]
