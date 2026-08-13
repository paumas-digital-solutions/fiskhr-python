"""Structured validation findings and the report container."""

from __future__ import annotations

import enum

from pydantic import BaseModel, ConfigDict

__all__ = ["Severity", "ValidationFinding", "ValidationReport"]


class Severity(enum.StrEnum):
    ERROR = "error"
    WARNING = "warning"


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ValidationFinding(_Model):
    """One validation problem.

    Attributes:
        source: Which layer produced it — ``"xsd"`` or ``"schematron"``.
        rule: Rule identifier when one exists (e.g. ``HR-BR-5``,
            ``BR-CL-01``); empty for XSD findings, which have no rule ids.
        severity: Schematron ``flag`` mapped to `Severity` (missing flag
            counts as an error); XSD findings are always errors.
        message: Human-readable text, verbatim from the validator (Croatian
            for the HR Schematron rules, per the language policy).
        location: XPath of the offending node (Schematron) or
            ``line:column`` (XSD); best-effort, may be empty.
    """

    source: str
    rule: str = ""
    severity: Severity = Severity.ERROR
    message: str
    location: str = ""


class ValidationReport(_Model):
    """The outcome of validating one document.

    ``ok`` means no error-severity findings; warnings alone do not fail a
    document. ``schematron_ran`` distinguishes "no Schematron findings"
    from "Schematron was skipped".
    """

    findings: tuple[ValidationFinding, ...] = ()
    schematron_ran: bool = False

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def errors(self) -> tuple[ValidationFinding, ...]:
        return tuple(f for f in self.findings if f.severity is Severity.ERROR)

    @property
    def warnings(self) -> tuple[ValidationFinding, ...]:
        return tuple(f for f in self.findings if f.severity is Severity.WARNING)

    def rules_fired(self) -> frozenset[str]:
        """The set of rule ids that produced findings (Schematron only)."""
        return frozenset(f.rule for f in self.findings if f.rule)
