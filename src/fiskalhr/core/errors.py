"""Exception hierarchy for `fiskalhr`.

Design rule: errors are structured, not strings. Anything reported by the Tax
Administration carries the server error code (``s001``, ``s002``, ...) and the
original Croatian message, so callers can react programmatically instead of
parsing text.
"""

from __future__ import annotations

__all__ = [
    "CertificateError",
    "CisError",
    "FiskalizacijaError",
    "InvalidOibError",
    "SignatureVerificationError",
]


class FiskalizacijaError(Exception):
    """Base class for every error raised by this library.

    Attributes:
        code: Server-side error code (e.g. ``"s001"``) when the error was
            reported by the Tax Administration, otherwise ``None``.
        message_hr: The original Croatian error message from the server,
            when one exists. The exception message itself is English.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        message_hr: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message_hr = message_hr


class CertificateError(FiskalizacijaError):
    """A certificate could not be loaded, is malformed, or is unusable."""


class InvalidOibError(FiskalizacijaError, ValueError):
    """A value is not a structurally valid OIB (length, digits, or checksum)."""


class CisError(FiskalizacijaError):
    """The CIS service returned an error response (``s001``-style codes).

    The mapping of known codes to explanations is populated in Phase 1
    alongside the F1 transport layer.
    """


class SignatureVerificationError(FiskalizacijaError):
    """An XML signature on a server response failed verification.

    This is deliberately its own type: a fiscalization response whose
    signature does not verify must never be treated as a transport hiccup.
    """
