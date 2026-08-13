"""ZKI (zastitni kod izdavatelja) computation.

The ZKI is defined in chapter 12 of the Fiskalizacija tech spec (v2.7):

1. Concatenate, in order, with no separators: OIB, date and time of issue
   (``dd.MM.yyyy HH:mm:ss``), receipt number (``brOznRac``), business premises
   code (``oznPosPr``), payment device code (``oznNapUr``), and the total
   amount with exactly two decimals and ``.`` as the separator.
2. Sign the UTF-8 bytes of that string with the issuer's private key using
   RSA (PKCS#1 v1.5). The spec's pseudocode and reference implementations use
   **RSA-SHA256**; RSA-SHA1 is the legacy method still accepted in production
   until the end of 2026 (see `fiskalhr.core.signing` for the timeline).
3. The ZKI is the lowercase hex MD5 digest of the signature bytes.

MD5 here is mandated by the specification (RFC 1321 per the spec text) and is
a receipt fingerprint, not a security primitive.

ZKI computation is deliberately offline: a receipt must show its ZKI even when
CIS is unreachable, so nothing in this module touches the network.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from cryptography.hazmat.primitives.asymmetric import padding, rsa

from fiskalhr.core.signing import SignatureMethod
from fiskalhr.core.types import validate_oib

__all__ = ["ZKI_DATETIME_FORMAT", "format_iznos", "izracunaj_zki", "zki_payload"]

ZKI_DATETIME_FORMAT = "%d.%m.%Y %H:%M:%S"
"""Datetime format required in the ZKI input string (local Croatian time)."""


def format_iznos(iznos: Decimal | int | str) -> str:
    """Format an amount as required by the spec: two decimals, ``.`` separator.

    Uses ``Decimal`` and half-up rounding; never pass floats for money.
    """
    return f"{Decimal(iznos).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"


def zki_payload(
    *,
    oib: str,
    datum_vrijeme: datetime,
    br_ozn_rac: str,
    ozn_pos_pr: str,
    ozn_nap_ur: str,
    ukupan_iznos: Decimal | int | str,
) -> str:
    """Build the exact string that gets signed for the ZKI.

    Exposed separately so integrators can log or debug the signed input —
    formatting mistakes here are the most common cause of ZKI mismatches.

    Args:
        oib: Issuer's OIB (11 digits, validated).
        datum_vrijeme: Date and time of issue, local Croatian time (naive).
        br_ozn_rac: Receipt sequence number (``brOznRac``).
        ozn_pos_pr: Business premises code (``oznPosPr``).
        ozn_nap_ur: Payment device code (``oznNapUr``).
        ukupan_iznos: Total receipt amount.
    """
    return (
        validate_oib(oib)
        + datum_vrijeme.strftime(ZKI_DATETIME_FORMAT)
        + br_ozn_rac
        + ozn_pos_pr
        + ozn_nap_ur
        + format_iznos(ukupan_iznos)
    )


def izracunaj_zki(
    private_key: rsa.RSAPrivateKey,
    *,
    oib: str,
    datum_vrijeme: datetime,
    br_ozn_rac: str,
    ozn_pos_pr: str,
    ozn_nap_ur: str,
    ukupan_iznos: Decimal | int | str,
    method: SignatureMethod = SignatureMethod.RSA_SHA256,
) -> str:
    """Compute the ZKI for a receipt. Works fully offline.

    Args:
        method: Signature method for step 2. Defaults to RSA-SHA256 per the
            current spec; pass ``SignatureMethod.RSA_SHA1`` only to reproduce
            ZKIs computed with the legacy method (accepted in production
            until the end of 2026).

    Returns:
        The 32-character lowercase hex ZKI.
    """
    payload = zki_payload(
        oib=oib,
        datum_vrijeme=datum_vrijeme,
        br_ozn_rac=br_ozn_rac,
        ozn_pos_pr=ozn_pos_pr,
        ozn_nap_ur=ozn_nap_ur,
        ukupan_iznos=ukupan_iznos,
    )
    signature = private_key.sign(
        payload.encode("utf-8"),
        padding.PKCS1v15(),
        method.hash_algorithm,
    )
    return hashlib.md5(signature, usedforsecurity=False).hexdigest()
