"""OIB validation tests.

The real-OIB vectors are publicly registered identifiers of large Croatian
institutions (OIBs are public data in Croatia) and serve as independent
golden vectors for the ISO 7064 MOD 11,10 checksum.
"""

from __future__ import annotations

import pytest

from fiskhr.core.errors import InvalidOibError
from fiskhr.core.types import is_valid_oib, oib_check_digit, validate_oib

KNOWN_VALID_OIBS = [
    "81793146560",  # Hrvatski Telekom d.d.
    "27759560625",  # INA d.d.
    "61817894937",  # Grad Zagreb
    "85821130368",  # FINA
    "12345678903",  # synthetic, checksum-valid
    "00000000001",  # synthetic, checksum-valid
]


@pytest.mark.parametrize("oib", KNOWN_VALID_OIBS)
def test_known_valid_oibs(oib: str) -> None:
    assert is_valid_oib(oib)
    assert validate_oib(oib) == oib


@pytest.mark.parametrize(
    "value",
    [
        "12345678901",  # wrong checksum
        "81793146561",  # real OIB with last digit flipped
        "1234567890",  # too short
        "123456789012",  # too long
        "1234567890a",  # non-digit
        "١٢٣٤٥٦٧٨٩٠٣",  # non-ASCII digits must be rejected
        "",
    ],
)
def test_invalid_oibs(value: str) -> None:
    assert not is_valid_oib(value)
    with pytest.raises(InvalidOibError):
        validate_oib(value)


def test_check_digit_requires_exactly_ten_digits() -> None:
    with pytest.raises(InvalidOibError):
        oib_check_digit("123")
    with pytest.raises(InvalidOibError):
        oib_check_digit("12345678901")


@pytest.mark.parametrize(("digits", "expected"), [("1234567890", 3), ("0000000000", 1)])
def test_check_digit_vectors(digits: str, expected: int) -> None:
    assert oib_check_digit(digits) == expected
