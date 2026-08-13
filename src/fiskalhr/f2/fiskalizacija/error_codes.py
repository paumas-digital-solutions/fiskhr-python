"""eFiskalizacija error codes (``greska`` simple type, eFiskalizacijaSchema.xsd).

Verbatim Croatian descriptions from the schema annotations. Codes S009 and
S010 are not defined in the schema. ``#``-prefixed placeholders are filled
in by the server with the offending value.
"""

from __future__ import annotations

__all__ = ["EFISKALIZACIJA_ERROR_MESSAGES"]

EFISKALIZACIJA_ERROR_MESSAGES: dict[str, str] = {
    "S001": "Sistemska greška prilikom obrade zahtjeva",
    "S002": "Lokacija potpisa nije ispravna",
    "S003": (
        "Certifikat nije izdan od davatelja usluga s Pouzdanog potpisa, "
        "ili je istekao ili je ukinut"
    ),
    "S004": "Neispravan potpis zahtjeva",
    "S005": (
        "Poruka nije u skladu s XML shemom : "
        "#element ili lista elemenata koji nisu ispravni po shemi"
    ),
    "S006": "Pristupna tocka nije ovlaštena za dostavu podataka",
    "S007": "OIB iz zahtjeva nije formalno ispravan: #vrijednost OIB-a iz upita",
    "S008": "Već postoji zabilježen eRačun s istim identifikatorom",
    "S011": "OIB iz zahtjeva nije jedinstven u listi",
    "S012": "Ne postoji evidentiran originalni eRačun za koji je dostavljen ispravljeni eRačun",
}
