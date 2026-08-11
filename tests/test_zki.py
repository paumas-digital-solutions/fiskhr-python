from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import Decimal
from typing import TypedDict

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from fiskalhr.core.errors import InvalidOibError
from fiskalhr.f1.zki import format_iznos, izracunaj_zki, zki_payload
from tests.conftest import TEST_OIB


class RacunFields(TypedDict):
    oib: str
    datum_vrijeme: datetime
    br_ozn_rac: str
    ozn_pos_pr: str
    ozn_nap_ur: str
    ukupan_iznos: Decimal


RACUN_FIELDS = RacunFields(
    oib=TEST_OIB,
    datum_vrijeme=datetime(2026, 8, 3, 11, 54, 25),
    br_ozn_rac="1",
    ozn_pos_pr="POSL1",
    ozn_nap_ur="12",
    ukupan_iznos=Decimal("125.00"),
)


def test_payload_is_exact_concatenation() -> None:
    # The payload format is fixed by the spec: any deviation breaks the ZKI.
    assert zki_payload(**RACUN_FIELDS) == f"{TEST_OIB}03.08.2026 11:54:251POSL112125.00"


def test_payload_rejects_invalid_oib() -> None:
    fields = RACUN_FIELDS.copy()
    fields["oib"] = "12345678901"  # bad checksum
    with pytest.raises(InvalidOibError):
        zki_payload(**fields)


@pytest.mark.parametrize(
    ("iznos", "expected"),
    [
        (Decimal("125.00"), "125.00"),
        (Decimal("0.1"), "0.10"),
        (Decimal("1E+2"), "100.00"),
        (Decimal("2.005"), "2.01"),  # half-up, not banker's rounding
        (Decimal("-13.5"), "-13.50"),  # storno amounts are negative
        (7, "7.00"),
        ("42.1", "42.10"),
    ],
)
def test_format_iznos(iznos: Decimal | int | str, expected: str) -> None:
    assert format_iznos(iznos) == expected


def test_zki_shape_and_determinism(rsa_key: rsa.RSAPrivateKey) -> None:
    zki = izracunaj_zki(rsa_key, **RACUN_FIELDS)

    assert len(zki) == 32
    assert zki == zki.lower()
    assert int(zki, 16) >= 0  # valid hex
    # PKCS#1 v1.5 signing is deterministic: same key + input -> same ZKI.
    assert izracunaj_zki(rsa_key, **RACUN_FIELDS) == zki


def test_zki_changes_with_input(rsa_key: rsa.RSAPrivateKey) -> None:
    fields = RACUN_FIELDS.copy()
    fields["ukupan_iznos"] = Decimal("125.01")

    assert izracunaj_zki(rsa_key, **fields) != izracunaj_zki(rsa_key, **RACUN_FIELDS)


def test_zki_matches_independent_computation(rsa_key: rsa.RSAPrivateKey) -> None:
    # Recompute the spec pipeline (RSA-SHA1 signature, then MD5 hex) directly
    # against the primitives, independent of the implementation under test.
    payload = f"{TEST_OIB}03.08.2026 11:54:251POSL112125.00"
    signature = rsa_key.sign(payload.encode("utf-8"), padding.PKCS1v15(), hashes.SHA1())
    expected = hashlib.md5(signature, usedforsecurity=False).hexdigest()

    assert izracunaj_zki(rsa_key, **RACUN_FIELDS) == expected
