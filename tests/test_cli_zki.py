from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from fiskhr.cli import PASSWORD_ENV_VAR, main
from fiskhr.core.certs import Certificate
from fiskhr.f1.zki import izracunaj_zki
from tests.conftest import TEST_OIB, TEST_P12_PASSWORD


def test_zki_command_matches_library(
    p12_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(PASSWORD_ENV_VAR, TEST_P12_PASSWORD)

    rc = main(
        [
            "zki",
            str(p12_path),
            "--oib",
            TEST_OIB,
            "--datum-vrijeme",
            "03.08.2026 11:54:25",
            "--br-ozn-rac",
            "1",
            "--ozn-pos-pr",
            "POSL1",
            "--ozn-nap-ur",
            "12",
            "--iznos",
            "125.00",
        ]
    )
    assert rc == 0

    cert = Certificate.from_p12(p12_path, TEST_P12_PASSWORD)
    expected = izracunaj_zki(
        cert.private_key,
        oib=TEST_OIB,
        datum_vrijeme=datetime(2026, 8, 3, 11, 54, 25),
        br_ozn_rac="1",
        ozn_pos_pr="POSL1",
        ozn_nap_ur="12",
        ukupan_iznos=Decimal("125.00"),
    )
    assert capsys.readouterr().out.strip() == expected


def test_zki_command_rejects_bad_datetime(
    p12_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(PASSWORD_ENV_VAR, TEST_P12_PASSWORD)

    rc = main(
        [
            "zki",
            str(p12_path),
            "--oib",
            TEST_OIB,
            "--datum-vrijeme",
            "2026-08-03T11:54:25",
            "--br-ozn-rac",
            "1",
            "--ozn-pos-pr",
            "POSL1",
            "--ozn-nap-ur",
            "12",
            "--iznos",
            "125.00",
        ]
    )
    assert rc == 2
    assert "dd.MM.yyyy" in capsys.readouterr().err


def test_zki_command_rejects_bad_amount(
    p12_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(PASSWORD_ENV_VAR, TEST_P12_PASSWORD)

    rc = main(
        [
            "zki",
            str(p12_path),
            "--oib",
            TEST_OIB,
            "--datum-vrijeme",
            "03.08.2026 11:54:25",
            "--br-ozn-rac",
            "1",
            "--ozn-pos-pr",
            "POSL1",
            "--ozn-nap-ur",
            "12",
            "--iznos",
            "abc",
        ]
    )
    assert rc == 2
    assert "not a valid amount" in capsys.readouterr().err
