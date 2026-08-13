"""Shared building blocks used by both fiscalization regimes.

Everything in `core` is regime-agnostic: certificate handling, the exception
hierarchy, environment selection, and shared value types. Nothing in here may
import from `fiskhr.f1` or `fiskhr.f2`.
"""

from fiskhr.core.certs import Certificate
from fiskhr.core.environment import Environment
from fiskhr.core.errors import (
    CertificateError,
    CisError,
    FiskalizacijaError,
    InvalidOibError,
    SignatureVerificationError,
)
from fiskhr.core.signing import SignatureMethod
from fiskhr.core.types import is_valid_oib, validate_oib
from fiskhr.core.xmldsig import sign_enveloped, verify_enveloped

__all__ = [
    "Certificate",
    "CertificateError",
    "CisError",
    "Environment",
    "FiskalizacijaError",
    "InvalidOibError",
    "SignatureMethod",
    "SignatureVerificationError",
    "is_valid_oib",
    "sign_enveloped",
    "validate_oib",
    "verify_enveloped",
]
