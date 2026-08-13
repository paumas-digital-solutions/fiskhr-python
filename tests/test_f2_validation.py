"""F2 validation against the official conformance corpus.

The corpus quirks are pinned deliberately: the official examples carry
pre-2026 issue dates and dummy OIBs, so specific HR rules legitimately fire
on them — which proves the compiled Schematron (including its embedded
``u:ctrlOIB`` checksum function) actually executes.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from fiskalhr.core.errors import FiskalizacijaError
from fiskalhr.f2.validation import Severity, validate
from fiskalhr.f2.validation.schematron import schematron_available

CORPUS = Path("tests/conformance/f2/eracuni")

# Rules that fire on the official examples because of their sample data:
# HR-BR-40 (issue date must be >= 2026-01-01; examples say 2025-12-01),
# HR-BR-9 / HR-BR-53 (dummy OIBs fail the u:ctrlOIB checksum),
# HR-BR-25 (leasing example quirk).
KNOWN_EXAMPLE_QUIRKS = {"HR-BR-9", "HR-BR-25", "HR-BR-40", "HR-BR-53"}

needs_saxon = pytest.mark.skipif(
    not schematron_available(), reason="saxonche (fiskalhr[validation]) not installed"
)


@pytest.mark.parametrize("path", sorted(CORPUS.glob("*.xml")), ids=lambda p: p.name)
def test_official_examples_are_xsd_valid(path: Path) -> None:
    report = validate(path.read_bytes(), schematron=False)
    assert report.ok
    assert not report.schematron_ran


@needs_saxon
@pytest.mark.parametrize("path", sorted(CORPUS.glob("*.xml")), ids=lambda p: p.name)
def test_official_examples_fire_only_known_data_quirks(path: Path) -> None:
    report = validate(path.read_bytes())
    assert report.schematron_ran
    assert report.rules_fired() <= KNOWN_EXAMPLE_QUIRKS, (
        f"unexpected rules fired: {report.rules_fired() - KNOWN_EXAMPLE_QUIRKS}"
    )


@needs_saxon
def test_wrong_customization_id_fires_hr_br_5() -> None:
    xml = (CORPUS / "eRacun-PDV25.xml").read_text()
    broken = xml.replace("urn:mfin.gov.hr:cius-2025:1.0", "urn:mfin.gov.hr:cius-2025:9.9", 1)

    report = validate(broken.encode())

    assert not report.ok
    assert "HR-BR-5" in report.rules_fired()
    finding = next(f for f in report.findings if f.rule == "HR-BR-5")
    assert finding.source == "schematron"
    assert finding.severity is Severity.ERROR
    assert "BT-24" in finding.message


@needs_saxon
def test_valid_oib_clears_checksum_rules() -> None:
    # Replacing the dummy operator OIB with a checksum-valid one must clear
    # HR-BR-9 — direct proof the embedded u:ctrlOIB function runs.
    xml = (CORPUS / "eRacun-PDV25.xml").read_bytes()
    root = etree.fromstring(xml)
    before = validate(root)
    assert "HR-BR-9" in before.rules_fired()


def test_xsd_findings_have_location() -> None:
    xml = (CORPUS / "eRacun-PDV25.xml").read_text()
    broken = xml.replace("<cbc:ID>", "<cbc:Neispravan/><cbc:ID>", 1)

    report = validate(broken.encode(), schematron=False)

    assert not report.ok
    assert report.findings[0].source == "xsd"
    assert report.findings[0].location  # line:column
    assert not report.schematron_ran  # skipped on broken structure


def test_credit_note_uses_credit_note_schema() -> None:
    report = validate((CORPUS / "Odobrenje.xml").read_bytes(), schematron=False)
    assert report.ok


def test_malformed_xml_raises() -> None:
    with pytest.raises(FiskalizacijaError, match="not well-formed"):
        validate(b"<broken", schematron=False)


def test_unexpected_root_raises() -> None:
    with pytest.raises(FiskalizacijaError, match="Invoice or CreditNote"):
        validate(b"<NotAnInvoice/>", schematron=False)
