"""UBL 2.1 eRačun construction (HR CIUS 2025).

`ERacunBuilder` produces `ERacun` models; ``to_xml()`` serialises them to
UBL Invoice documents that pass `fiskalhr.f2.validation.validate` — the
official XSD plus the full HR CIUS 2025 Schematron — which the test suite
enforces on every build.

``sign_eracun`` fills the document's own signature slot with a XAdES
signature. It is optional under the HR rules (HR-BR-33 exempts that element
from the no-empty-elements rule) but required for delivery through FINA.
"""

from fiskalhr.f2.ubl.builder import ERacunBuilder
from fiskalhr.f2.ubl.models import (
    CUSTOMIZATION_ID,
    Adresa,
    ERacun,
    KategorijaPdv,
    Operater,
    Popust,
    PrethodniRacun,
    Stavka,
    Stranka,
    Trosak,
)
from fiskalhr.f2.ubl.sign import sign_eracun
from fiskalhr.f2.ubl.xml import to_xml

__all__ = [
    "CUSTOMIZATION_ID",
    "Adresa",
    "ERacun",
    "ERacunBuilder",
    "KategorijaPdv",
    "Operater",
    "Popust",
    "PrethodniRacun",
    "Stavka",
    "Stranka",
    "Trosak",
    "sign_eracun",
    "to_xml",
]
