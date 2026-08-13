"""Certificate loading and inspection.

Security posture (non-negotiable):

- Passwords are used to decrypt the P12 and then dropped — never stored on the
  object, never logged, never part of ``repr()``.
- The private key is excluded from ``repr()`` so a stray log line cannot leak
  key material identifiers.
- No certificate material ships with, or is committed to, this repository.
  Tests generate throwaway self-signed certificates at runtime.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12

from fiskhr.core.errors import CertificateError
from fiskhr.core.types import is_valid_oib

__all__ = ["Certificate"]

_OIB_IN_SUBJECT = re.compile(r"(?:HR)?(\d{11})")


@dataclass(frozen=True)
class Certificate:
    """A loaded signing certificate: private key, leaf certificate, CA chain."""

    private_key: rsa.RSAPrivateKey = field(repr=False)
    certificate: x509.Certificate
    chain: tuple[x509.Certificate, ...] = ()

    @classmethod
    def from_p12(cls, path: str | Path, password: str | bytes) -> Certificate:
        """Load a certificate from a PKCS#12 (``.p12`` / ``.pfx``) file.

        Args:
            path: Path to the P12 file.
            password: The P12 password. Used for decryption only; not retained.

        Raises:
            CertificateError: If the file cannot be read or decrypted, or does
                not contain both a certificate and an RSA private key.
        """
        try:
            data = Path(path).read_bytes()
        except OSError as exc:
            raise CertificateError(f"cannot read P12 file {str(path)!r}: {exc}") from exc

        password_bytes = password.encode("utf-8") if isinstance(password, str) else password
        try:
            key, cert, extra = pkcs12.load_key_and_certificates(data, password_bytes)
        except ValueError as exc:
            # Deliberately does not echo the password back in any form.
            raise CertificateError(
                f"cannot decrypt P12 file {str(path)!r}: wrong password or corrupt file"
            ) from exc

        if cert is None:
            raise CertificateError(f"P12 file {str(path)!r} contains no certificate")
        if key is None:
            raise CertificateError(f"P12 file {str(path)!r} contains no private key")
        if not isinstance(key, rsa.RSAPrivateKey):
            raise CertificateError(
                "fiscalization requires an RSA private key, "
                f"got {type(key).__name__} in {str(path)!r}"
            )

        return cls(private_key=key, certificate=cert, chain=tuple(extra or ()))

    @property
    def subject(self) -> str:
        """Subject distinguished name in RFC 4514 form."""
        return self.certificate.subject.rfc4514_string()

    @property
    def issuer(self) -> str:
        """Issuer distinguished name in RFC 4514 form."""
        return self.certificate.issuer.rfc4514_string()

    @property
    def serial_number(self) -> int:
        return self.certificate.serial_number

    @property
    def not_valid_before(self) -> datetime:
        """Start of validity, timezone-aware UTC."""
        return self.certificate.not_valid_before_utc

    @property
    def not_valid_after(self) -> datetime:
        """End of validity, timezone-aware UTC."""
        return self.certificate.not_valid_after_utc

    @property
    def oib(self) -> str | None:
        """The OIB embedded in the certificate subject, if one can be found.

        FINA fiscalization certificates carry the holder's OIB inside subject
        attributes (typically suffixed as ``HR<oib>``). This scans every
        subject attribute for an 11-digit sequence with a valid OIB checksum.
        Best-effort: returns ``None`` when nothing plausible is found.
        """
        for attribute in self.certificate.subject:
            value = attribute.value
            if isinstance(value, bytes):
                continue
            for match in _OIB_IN_SUBJECT.finditer(value):
                if is_valid_oib(match.group(1)):
                    return match.group(1)
        return None

    def is_expired(self, at: datetime | None = None) -> bool:
        """Whether the certificate is outside its validity window.

        Args:
            at: The moment to check, timezone-aware. Defaults to now (UTC).
        """
        moment = at if at is not None else datetime.now(UTC)
        return not (self.not_valid_before <= moment <= self.not_valid_after)
