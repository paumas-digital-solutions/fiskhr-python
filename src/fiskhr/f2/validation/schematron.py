"""HR CIUS 2025 Schematron validation via the pre-compiled XSLT.

The official rules (``queryBinding="xslt2"`` with embedded XSLT functions,
e.g. the ``u:ctrlOIB`` OIB checksum) require a real XSLT 2.0 engine, so this
module depends on ``saxonche`` (SaxonC-HE), installable as::

    pip install fiskhr[validation]

The vendored, pre-compiled stylesheet (see ``schemas/schematron/compiled/``
and SOURCES.md) is applied to the document; the resulting SVRL report is
parsed into `ValidationFinding` objects.

The Saxon processor and compiled stylesheet are process-wide singletons —
compilation costs ~a second, execution is fast. SaxonC keeps its own
threading model; for multi-process servers this is per-process state.
"""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Any

from lxml import etree

from fiskhr.core.errors import FiskalizacijaError
from fiskhr.f2.validation.report import Severity, ValidationFinding

if TYPE_CHECKING:
    from saxonche import PySaxonProcessor, PyXsltExecutable

__all__ = ["schematron_available", "validate_schematron"]

_SVRL_NS = "http://purl.oclc.org/dsdl/svrl"

_processor: PySaxonProcessor | None = None
_executable: PyXsltExecutable | None = None


def schematron_available() -> bool:
    """Whether the optional XSLT 2.0 engine (``saxonche``) is installed."""
    try:
        import saxonche  # noqa: F401
    except ImportError:
        return False
    return True


def _compiled_stylesheet_path() -> Path:
    return Path(
        str(
            files("fiskhr.f2")
            / "schemas"
            / "schematron"
            / "compiled"
            / "HR-CIUS-EXT-EN16931-UBL.xsl"
        )
    )


def _get_executable() -> tuple[Any, Any]:
    global _processor, _executable
    if _executable is not None:
        return _processor, _executable
    try:
        from saxonche import PySaxonProcessor
    except ImportError as exc:
        raise FiskalizacijaError(
            "Schematron validation requires an XSLT 2.0 engine: "
            "install the optional extra with `pip install fiskhr[validation]`, "
            "or call validate(..., schematron=False) for XSD-only validation"
        ) from exc
    _processor = PySaxonProcessor(license=False)
    xslt = _processor.new_xslt30_processor()
    _executable = xslt.compile_stylesheet(stylesheet_file=str(_compiled_stylesheet_path()))
    return _processor, _executable


def validate_schematron(root: etree._Element) -> tuple[ValidationFinding, ...]:
    """Run the HR CIUS 2025 rules and return one finding per failed assert.

    Raises:
        FiskalizacijaError: If ``saxonche`` is not installed.
    """
    processor, executable = _get_executable()
    document = processor.parse_xml(xml_text=etree.tostring(root, encoding="unicode"))
    svrl_text = executable.transform_to_string(xdm_node=document)
    if svrl_text is None:
        raise FiskalizacijaError("Schematron transformation produced no SVRL output")

    svrl = etree.fromstring(svrl_text.encode("utf-8"))
    findings = []
    for element in svrl.iter(f"{{{_SVRL_NS}}}failed-assert", f"{{{_SVRL_NS}}}successful-report"):
        flag = (element.get("flag") or "").lower()
        findings.append(
            ValidationFinding(
                source="schematron",
                rule=element.get("id") or "",
                severity=Severity.WARNING if flag == "warning" else Severity.ERROR,
                message=" ".join((element.findtext(f"{{{_SVRL_NS}}}text") or "").split()),
                location=element.get("location") or "",
            )
        )
    return tuple(findings)
