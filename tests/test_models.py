from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from fiskalhr.f1.models import (
    BrojRacuna,
    NacinPlacanja,
    OznakaSlijednosti,
    Racun,
)
from tests.conftest import TEST_OIB


def _racun(**overrides: object) -> Racun:
    fields: dict[str, object] = {
        "oib": TEST_OIB,
        "u_sust_pdv": True,
        "dat_vrijeme": datetime(2026, 8, 3, 11, 54, 25),
        "ozn_slijed": OznakaSlijednosti.POSLOVNI_PROSTOR,
        "br_rac": BrojRacuna(br_ozn_rac="1", ozn_pos_pr="POSL1", ozn_nap_ur="12"),
        "iznos_ukupno": Decimal("125.00"),
        "nacin_plac": NacinPlacanja.KARTICA,
        "oib_oper": TEST_OIB,
    }
    fields.update(overrides)
    return Racun(**fields)  # type: ignore[arg-type]


def test_valid_racun_constructs() -> None:
    racun = _racun()
    assert racun.oib == TEST_OIB
    assert racun.nak_dost is False  # not a late submission by default


@pytest.mark.parametrize("field", ["oib", "oib_oper", "oib_primatelja_racuna"])
def test_oib_fields_are_checksum_validated(field: str) -> None:
    with pytest.raises(ValidationError, match="checksum"):
        _racun(**{field: "12345678901"})


def test_broj_racuna_patterns() -> None:
    with pytest.raises(ValidationError):
        BrojRacuna(br_ozn_rac="0x1", ozn_pos_pr="POSL1", ozn_nap_ur="12")
    with pytest.raises(ValidationError):
        BrojRacuna(br_ozn_rac="1", ozn_pos_pr="POSL 1", ozn_nap_ur="12")
    with pytest.raises(ValidationError):
        BrojRacuna(br_ozn_rac="1", ozn_pos_pr="POSL1", ozn_nap_ur="ABC")


def test_racun_is_frozen() -> None:
    racun = _racun()
    with pytest.raises(ValidationError):
        racun.iznos_ukupno = Decimal("1.00")


def test_unknown_fields_are_rejected() -> None:
    # extra="forbid": a typo like "iznos_ukupno_" must not pass silently.
    with pytest.raises(ValidationError):
        _racun(iznos_ukupnoo=Decimal("1.00"))
