"""eRačun validation — XSD structure plus HR CIUS 2025 Schematron rules.

`validate` returns a `ValidationReport` instead of raising, because callers
almost always want to show every problem at once. The report carries
structured findings: the rule id (``HR-BR-5``-style for Schematron, the
libxml2 message for XSD), severity, human-readable message, and location.

Schematron validation needs an XSLT 2.0 engine and is an optional extra::

    pip install fiskhr[validation]

Without it, `validate(..., schematron=False)` still performs full XSD
validation; requesting Schematron without the extra raises a helpful error.
"""

from fiskhr.f2.validation.report import Severity, ValidationFinding, ValidationReport
from fiskhr.f2.validation.validate import validate

__all__ = ["Severity", "ValidationFinding", "ValidationReport", "validate"]
