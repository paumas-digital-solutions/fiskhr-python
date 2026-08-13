from __future__ import annotations

from pathlib import Path

import pytest

from fiskalhr import __version__
from fiskalhr.cli import PASSWORD_ENV_VAR, main
from tests.conftest import TEST_OIB, TEST_P12_PASSWORD


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_cert_info(
    p12_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(PASSWORD_ENV_VAR, TEST_P12_PASSWORD)

    assert main(["cert", "info", str(p12_path)]) == 0

    out = capsys.readouterr().out
    assert "TEST TVRTKA" in out
    assert TEST_OIB in out
    assert "expired:          no" in out


def test_ovlastenja_lists_oibi(
    p12_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fiskalhr.f2.izvjestavanje import EIzvjestavanjeClient
    from fiskalhr.testing import MockEIzvjestavanje

    monkeypatch.setenv(PASSWORD_ENV_VAR, TEST_P12_PASSWORD)
    mock = MockEIzvjestavanje(ovlasteni_oibi=(TEST_OIB, "00000000001"))

    original_init = EIzvjestavanjeClient.__init__

    def init_with_mock(self: EIzvjestavanjeClient, *args: object, **kwargs: object) -> None:
        kwargs["transport"] = mock.transport()
        original_init(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(EIzvjestavanjeClient, "__init__", init_with_mock)

    # No explicit OIB: falls back to the certificate subject's OIB.
    assert main(["ovlastenja", str(p12_path)]) == 0

    out = capsys.readouterr().out.splitlines()
    assert out == [TEST_OIB, "00000000001"]


def test_cert_info_wrong_password_fails_cleanly(
    p12_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "definitely-not-the-password"
    monkeypatch.setenv(PASSWORD_ENV_VAR, secret)

    assert main(["cert", "info", str(p12_path)]) == 1

    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert secret not in err  # the password itself must never be echoed
