"""Signature methods shared by ZKI computation and XML-DSig.

The Tax Administration is migrating from RSA-SHA1 to RSA-SHA256
(tech spec v2.7, changelog and chapter on XML signing):

- since 2026-05-01, production accepts **both** RSA-SHA1 and RSA-SHA256;
- since 2026-07-01, the **test environment rejects RSA-SHA1** (and TLS 1.1);
- from 2027-01-01, **production rejects RSA-SHA1** (and TLS 1.1).

RSA-SHA256 is therefore the default everywhere in this library; RSA-SHA1
exists only for the production transition period and for verifying old
receipts. The CIS signs its response with the same method the request used.
"""

from __future__ import annotations

import enum

from cryptography.hazmat.primitives import hashes

__all__ = ["SignatureMethod"]


class SignatureMethod(enum.Enum):
    """An RSA signature method permitted by the F1 specification."""

    RSA_SHA256 = "RSA-SHA256"
    RSA_SHA1 = "RSA-SHA1"

    @property
    def hash_algorithm(self) -> hashes.HashAlgorithm:
        """The `cryptography` hash instance for this method."""
        if self is SignatureMethod.RSA_SHA256:
            return hashes.SHA256()
        return hashes.SHA1()

    @property
    def xmldsig_uri(self) -> str:
        """The XML-DSig ``SignatureMethod`` algorithm URI (spec v2.7, ch. 15)."""
        if self is SignatureMethod.RSA_SHA256:
            return "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
        return "http://www.w3.org/2000/09/xmldsig#rsa-sha1"
