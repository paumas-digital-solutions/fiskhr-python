from __future__ import annotations

import pytest
from cryptography import x509
from lxml import etree

from fiskhr.core.certs import Certificate
from fiskhr.core.errors import SignatureVerificationError
from fiskhr.core.signing import SignatureMethod
from fiskhr.core.xmldsig import sign_enveloped, verify_enveloped
from tests.conftest import TEST_OIB, make_rsa_key, make_self_signed_cert

DS = "{http://www.w3.org/2000/09/xmldsig#}"

# Shaped like the spec's ch. 7 example (RacunZahtjev with Id attribute).
SAMPLE_ZAHTJEV = (
    b'<tns:RacunZahtjev Id="RacunZahtjev"'
    b' xmlns:tns="http://www.apis-it.hr/fin/2012/types/f73">'
    b"<tns:Zaglavlje>"
    b"<tns:IdPoruke>f81d4fae-7dec-11d0-a765-00a0c91e6bf6</tns:IdPoruke>"
    b"<tns:DatumVrijeme>03.08.2026T11:54:25</tns:DatumVrijeme>"
    b"</tns:Zaglavlje>"
    b"<tns:Racun><tns:Oib>" + TEST_OIB.encode() + b"</tns:Oib></tns:Racun>"
    b"</tns:RacunZahtjev>"
)


@pytest.fixture(scope="module")
def signer_cert() -> Certificate:
    key = make_rsa_key()
    return Certificate(private_key=key, certificate=make_self_signed_cert(key))


def test_signature_matches_spec_profile(signer_cert: Certificate) -> None:
    # Pin the wire format to spec v2.7 ch. 7 so a signxml upgrade cannot
    # silently change it.
    root = etree.fromstring(sign_enveloped(SAMPLE_ZAHTJEV, signer_cert))

    c14n = root.find(f".//{DS}SignedInfo/{DS}CanonicalizationMethod")
    assert c14n is not None
    assert c14n.get("Algorithm") == "http://www.w3.org/2001/10/xml-exc-c14n#"

    sig_method = root.find(f".//{DS}SignedInfo/{DS}SignatureMethod")
    assert sig_method is not None
    assert sig_method.get("Algorithm") == "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"

    reference = root.find(f".//{DS}Reference")
    assert reference is not None
    assert reference.get("URI") == "#RacunZahtjev"

    transforms = [el.get("Algorithm") for el in reference.findall(f"{DS}Transforms/{DS}Transform")]
    assert transforms == [
        "http://www.w3.org/2000/09/xmldsig#enveloped-signature",
        "http://www.w3.org/2001/10/xml-exc-c14n#",
    ]

    digest = reference.find(f"{DS}DigestMethod")
    assert digest is not None
    assert digest.get("Algorithm") == "http://www.w3.org/2001/04/xmlenc#sha256"

    assert root.find(f".//{DS}X509Data/{DS}X509Certificate") is not None
    issuer_serial = root.find(f".//{DS}X509Data/{DS}X509IssuerSerial")
    assert issuer_serial is not None
    serial = issuer_serial.find(f"{DS}X509SerialNumber")
    assert serial is not None
    assert serial.text == str(signer_cert.serial_number)


@pytest.mark.parametrize("method", list(SignatureMethod))
def test_sign_verify_roundtrip(signer_cert: Certificate, method: SignatureMethod) -> None:
    signed = sign_enveloped(SAMPLE_ZAHTJEV, signer_cert, method=method)

    used = verify_enveloped(signed, expected_certificate=signer_cert.certificate)
    assert used == signer_cert.certificate


def test_verify_with_embedded_certificate_needs_opt_in(signer_cert: Certificate) -> None:
    signed = sign_enveloped(SAMPLE_ZAHTJEV, signer_cert)

    with pytest.raises(SignatureVerificationError, match="no trusted certificate"):
        verify_enveloped(signed)

    used = verify_enveloped(signed, trust_embedded_certificate=True)
    assert used == signer_cert.certificate


def test_tampered_document_fails_verification(signer_cert: Certificate) -> None:
    signed = sign_enveloped(SAMPLE_ZAHTJEV, signer_cert)
    tampered = signed.replace(TEST_OIB.encode(), b"00000000001")
    assert tampered != signed

    with pytest.raises(SignatureVerificationError):
        verify_enveloped(tampered, expected_certificate=signer_cert.certificate)


def test_wrong_certificate_fails_verification(signer_cert: Certificate) -> None:
    signed = sign_enveloped(SAMPLE_ZAHTJEV, signer_cert)
    other_key = make_rsa_key()
    other_cert: x509.Certificate = make_self_signed_cert(other_key, organization="DRUGA TVRTKA")

    with pytest.raises(SignatureVerificationError):
        verify_enveloped(signed, expected_certificate=other_cert)


def test_sign_requires_id_attribute(signer_cert: Certificate) -> None:
    no_id = b'<tns:RacunZahtjev xmlns:tns="http://www.apis-it.hr/fin/2012/types/f73"/>'
    with pytest.raises(ValueError, match="Id attribute"):
        sign_enveloped(no_id, signer_cert)


def test_verify_rejects_malformed_xml() -> None:
    with pytest.raises(SignatureVerificationError, match="not well-formed"):
        verify_enveloped(b"<not-xml", trust_embedded_certificate=True)
