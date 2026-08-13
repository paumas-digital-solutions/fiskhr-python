from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from fiskhr.core.certs import Certificate
from fiskhr.core.errors import CertificateError
from tests.conftest import TEST_OIB, TEST_P12_PASSWORD


def test_from_p12_loads_key_and_certificate(p12_path: Path) -> None:
    cert = Certificate.from_p12(p12_path, TEST_P12_PASSWORD)

    assert "TEST TVRTKA" in cert.subject
    assert cert.subject == cert.issuer  # self-signed fixture
    assert cert.chain == ()
    assert cert.serial_number > 0
    assert not cert.is_expired()


def test_from_p12_accepts_bytes_password(p12_path: Path) -> None:
    cert = Certificate.from_p12(p12_path, TEST_P12_PASSWORD.encode("utf-8"))
    assert cert.oib == TEST_OIB


def test_oib_extracted_from_subject(p12_path: Path) -> None:
    cert = Certificate.from_p12(p12_path, TEST_P12_PASSWORD)
    assert cert.oib == TEST_OIB


def test_wrong_password_raises_certificate_error(p12_path: Path) -> None:
    with pytest.raises(CertificateError, match="wrong password or corrupt file"):
        Certificate.from_p12(p12_path, "not-the-password")


def test_wrong_password_error_does_not_leak_password(p12_path: Path) -> None:
    secret = "super-secret-value"
    with pytest.raises(CertificateError) as exc_info:
        Certificate.from_p12(p12_path, secret)
    assert secret not in str(exc_info.value)


def test_missing_file_raises_certificate_error(tmp_path: Path) -> None:
    with pytest.raises(CertificateError, match="cannot read"):
        Certificate.from_p12(tmp_path / "does-not-exist.p12", "irrelevant")


def test_repr_hides_private_key(p12_path: Path) -> None:
    cert = Certificate.from_p12(p12_path, TEST_P12_PASSWORD)
    assert "private_key" not in repr(cert)


def test_is_expired_respects_validity_window(p12_path: Path) -> None:
    cert = Certificate.from_p12(p12_path, TEST_P12_PASSWORD)
    assert cert.is_expired(at=datetime(2000, 1, 1, tzinfo=UTC))
    assert cert.is_expired(at=datetime(2100, 1, 1, tzinfo=UTC))
    assert not cert.is_expired(at=datetime.now(UTC))
