"""Shared building blocks used by both fiscalization regimes.

Everything in `core` is regime-agnostic: certificate handling, the exception
hierarchy, environment selection, and shared value types. Nothing in here may
import from `fiskalhr.f1` or `fiskalhr.f2`.
"""

from fiskalhr.core.certs import Certificate
from fiskalhr.core.environment import Environment
from fiskalhr.core.errors import (
    CertificateError,
    CisError,
    FiskalizacijaError,
    InvalidOibError,
    SignatureVerificationError,
)
from fiskalhr.core.types import is_valid_oib, validate_oib

__all__ = [
    "Certificate",
    "CertificateError",
    "CisError",
    "Environment",
    "FiskalizacijaError",
    "InvalidOibError",
    "SignatureVerificationError",
    "is_valid_oib",
    "validate_oib",
]
