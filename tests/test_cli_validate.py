from __future__ import annotations

from pathlib import Path

import pytest

from fiskalhr.cli import main
from fiskalhr.f2.validation.schematron import schematron_available

CORPUS = Path("tests/conformance/f2/eracuni")

needs_saxon = pytest.mark.skipif(
    not schematron_available(), reason="saxonche (fiskalhr[validation]) not installed"
)


def test_validate_xsd_only_passes_official_example(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = main(["validate", str(CORPUS / "eRacun-PDV25.xml"), "--no-schematron"])
    assert rc == 0
    assert "OK (XSD" in capsys.readouterr().out


@needs_saxon
def test_validate_full_reports_findings(capsys: pytest.CaptureFixture[str]) -> None:
    # Official examples carry known data quirks, so full validation fails —
    # and the CLI must show the rule ids.
    rc = main(["validate", str(CORPUS / "eRacun-PDV25.xml")])
    captured = capsys.readouterr()
    assert rc == 1
    assert "[HR-BR-9]" in captured.out
    assert "INVALID (XSD + Schematron" in captured.err


def test_validate_broken_structure(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    broken = tmp_path / "broken.xml"
    broken.write_text(
        (CORPUS / "eRacun-PDV25.xml").read_text().replace("<cbc:ID>", "<cbc:Nema/><cbc:ID>", 1)
    )
    rc = main(["validate", str(broken)])
    captured = capsys.readouterr()
    assert rc == 1
    assert "error" in captured.out
    assert "INVALID (XSD;" in captured.err
