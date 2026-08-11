"""Shared fixtures: throwaway certificate material generated at runtime.

No certificate, key, or P12 file is ever stored in this repository — not even
a test one. Everything below is generated fresh per test session.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

# A synthetic OIB with a valid ISO 7064 MOD 11,10 checksum. Not assigned to
# any real entity (checksum-valid does not mean issued).
TEST_OIB = "12345678903"
TEST_P12_PASSWORD = "test-password"


@pytest.fixture(scope="session")
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="session")
def self_signed_cert(rsa_key: rsa.RSAPrivateKey) -> x509.Certificate:
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "FISKAL 1"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, f"TEST TVRTKA D.O.O. HR{TEST_OIB}"),
            x509.NameAttribute(NameOID.COUNTRY_NAME, "HR"),
        ]
    )
    now = datetime.now(UTC)
    return (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(rsa_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .sign(rsa_key, hashes.SHA256())
    )


@pytest.fixture
def p12_path(
    tmp_path: Path, rsa_key: rsa.RSAPrivateKey, self_signed_cert: x509.Certificate
) -> Path:
    """A throwaway P12 file on disk, encrypted with TEST_P12_PASSWORD."""
    data = pkcs12.serialize_key_and_certificates(
        name=b"test",
        key=rsa_key,
        cert=self_signed_cert,
        cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(
            TEST_P12_PASSWORD.encode("utf-8")
        ),
    )
    path = tmp_path / "test-cert.p12"
    path.write_bytes(data)
    return path
