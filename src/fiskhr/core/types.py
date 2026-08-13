"""Shared value types and validators.

Domain identifiers keep their Croatian names (``oib``, ``zki``, ``jir``) —
see the language policy in ARCHITECTURE.md.
"""

from __future__ import annotations

from fiskhr.core.errors import InvalidOibError

__all__ = ["is_valid_oib", "oib_check_digit", "validate_oib"]

OIB_LENGTH = 11


def oib_check_digit(digits: str) -> int:
    """Compute the OIB check digit for the first ten digits.

    The OIB checksum is ISO 7064 MOD 11,10 over the first ten digits; the
    result is the expected eleventh digit.

    Args:
        digits: Exactly ten ASCII digits.

    Raises:
        InvalidOibError: If ``digits`` is not exactly ten digits.
    """
    if len(digits) != OIB_LENGTH - 1 or not digits.isascii() or not digits.isdigit():
        raise InvalidOibError(f"expected exactly 10 digits, got {digits!r}")

    acc = 10
    for char in digits:
        acc = (acc + int(char)) % 10
        if acc == 0:
            acc = 10
        acc = (acc * 2) % 11
    return (11 - acc) % 10


def is_valid_oib(value: str) -> bool:
    """Return whether ``value`` is a structurally valid OIB.

    Checks length (11), digits-only, and the ISO 7064 MOD 11,10 checksum.
    A valid checksum does not mean the OIB is actually assigned to anyone.
    """
    if len(value) != OIB_LENGTH or not value.isascii() or not value.isdigit():
        return False
    return int(value[-1]) == oib_check_digit(value[:-1])


def validate_oib(value: str) -> str:
    """Validate ``value`` as an OIB and return it unchanged.

    Raises:
        InvalidOibError: If the value is not 11 digits or the checksum fails.
    """
    if len(value) != OIB_LENGTH or not value.isascii() or not value.isdigit():
        raise InvalidOibError(f"OIB must be exactly 11 digits, got {value!r}")
    if int(value[-1]) != oib_check_digit(value[:-1]):
        raise InvalidOibError(f"OIB checksum is invalid for {value!r}")
    return value
