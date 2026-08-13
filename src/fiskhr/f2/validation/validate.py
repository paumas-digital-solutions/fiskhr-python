"""The public validation entry point."""

from __future__ import annotations

from lxml import etree

from fiskhr.f2.validation.report import ValidationReport
from fiskhr.f2.validation.schematron import validate_schematron
from fiskhr.f2.validation.xsd import parse_document, validate_xsd

__all__ = ["validate"]


def validate(xml: bytes | etree._Element, *, schematron: bool = True) -> ValidationReport:
    """Validate an eRačun (UBL Invoice or CreditNote) document.

    Runs XSD validation first; when the document is structurally valid and
    ``schematron`` is True (default), the HR CIUS 2025 Schematron rules run
    as well. Schematron is skipped when the structure is already broken —
    rule XPaths against a malformed tree produce noise, not insight.

    Args:
        xml: The document as bytes or an lxml element.
        schematron: Run the business rules (requires the
            ``fiskhr[validation]`` extra). Set False for XSD-only checks.

    Returns:
        A `ValidationReport`; inspect ``.ok``, ``.errors``, ``.warnings``.

    Raises:
        FiskalizacijaError: On malformed XML, an unexpected root element, or
            a Schematron request without ``saxonche`` installed.
    """
    root = parse_document(xml)
    findings = validate_xsd(root)
    if findings or not schematron:
        return ValidationReport(findings=findings, schematron_ran=False)
    return ValidationReport(findings=validate_schematron(root), schematron_ran=True)
