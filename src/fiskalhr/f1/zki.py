"""ZKI (zastitni kod izdavatelja) computation.

The ZKI is defined by the Fiskalizacija 1.0 technical specification as:

1. Concatenate, in order, with no separators: OIB, date and time of issue
   (``dd.mm.yyyy HH:MM:SS``), receipt number (``brOznRac``), business premises
   code (``oznPosPr``), payment device code (``oznNapUr``), and the total
   amount with exactly two decimals and ``.`` as the separator.
2. Sign the UTF-8 bytes of that string with the issuer's private key using
   RSA-SHA1 (PKCS#1 v1.5).
3. The ZKI is the lowercase hex MD5 digest of the signature bytes.

SHA-1 and MD5 are mandated by the specification and are not used here for
collision resistance — the ZKI is a receipt fingerprint, not a security
primitive. They are not a choice this library gets to make.

ZKI computation is deliberately offline: a receipt must show its ZKI even when
CIS is unreachable, so nothing in this module touches the network.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

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
) -> str:
    """Compute the ZKI for a receipt. Works fully offline.

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
        hashes.SHA1(),
    )
    return hashlib.md5(signature, usedforsecurity=False).hexdigest()
