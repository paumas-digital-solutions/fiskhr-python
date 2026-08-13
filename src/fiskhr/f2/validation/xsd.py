"""XSD (structural) validation against the vendored UBL 2.1 schemas."""

from __future__ import annotations

from collections.abc import Iterable
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import cast

from lxml import etree

from fiskhr.core.errors import FiskalizacijaError
from fiskhr.f2.validation.report import Severity, ValidationFinding

__all__ = ["parse_document", "validate_xsd"]

INVOICE_TAG = "{urn:oasis:names:specification:ubl:schema:xsd:Invoice-2}Invoice"
CREDIT_NOTE_TAG = "{urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2}CreditNote"

_MAINDOC = {
    INVOICE_TAG: "UBL-Invoice-2.1.xsd",
    CREDIT_NOTE_TAG: "UBL-CreditNote-2.1.xsd",
}


def _schema_path(name: str) -> Path:
    return Path(str(files("fiskhr.f2") / "schemas" / "ubl" / "maindoc" / name))


@cache
def _schema(name: str) -> etree.XMLSchema:
    return etree.XMLSchema(etree.parse(_schema_path(name)))


def parse_document(xml: bytes | etree._Element) -> etree._Element:
    """Parse input into a root element, raising `FiskalizacijaError` on
    malformed XML or a root that is neither ``Invoice`` nor ``CreditNote``."""
    if isinstance(xml, bytes):
        try:
            root = etree.fromstring(xml)
        except etree.XMLSyntaxError as exc:
            raise FiskalizacijaError(f"document is not well-formed XML: {exc}") from exc
    else:
        root = xml
    if root.tag not in _MAINDOC:
        raise FiskalizacijaError(f"expected a UBL Invoice or CreditNote root, got {root.tag!r}")
    return root


def validate_xsd(root: etree._Element) -> tuple[ValidationFinding, ...]:
    """Validate against the matching vendored maindoc schema.

    Returns one finding per libxml2 error; an empty tuple means the
    document is structurally valid.
    """
    schema = _schema(_MAINDOC[root.tag])
    if schema.validate(root):
        return ()
    # lxml-stubs does not type _ErrorLog as iterable, but it is.
    error_log = cast("Iterable[etree._LogEntry]", schema.error_log)
    return tuple(
        ValidationFinding(
            source="xsd",
            severity=Severity.ERROR,
            message=error.message or "schema violation",
            location=f"{error.line}:{error.column}",
        )
        for error in error_log
    )
