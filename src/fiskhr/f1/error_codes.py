"""CIS error codes (šifrarnik grešaka).

Source: tech spec v2.7 (21.07.2026), per-method error tables. The texts are
the server's Croatian messages, kept verbatim per the language policy —
these are what the CIS actually returns, so translating them here would
only obscure matching. ``#...#`` marks a server-filled placeholder.

Not every code can occur on every method: s007/s008 belong to the
payment-method change message, s009/s010 to napojnica (tip) messages,
s011/s012 to the receipt-data change message. s013 wraps the separate
"restriktivne greške" code list (numeric codes such as 176-179), enforced
since 2026-01-01.
"""

from __future__ import annotations

__all__ = ["CIS_ERROR_MESSAGES"]

CIS_ERROR_MESSAGES: dict[str, str] = {
    "s001": (
        "Poruka nije u skladu s XML shemom: "
        "#element ili lista elemenata koji nisu ispravni po shemi#."
    ),
    "s002": (
        "Certifikat nije izdan od pružatelja usluga povjerenja s pouzdanog "
        "popisa u skladu s eIDAS uredbom ili je istekao ili je ukinut."
    ),
    "s003": "Certifikat ne sadrži obvezan podatak.",
    "s004": "Neispravan digitalni potpis.",
    "s005": "OIB iz poruke zahtjeva nije jednak OIB-u iz certifikata.",
    "s006": "Sistemska pogreška prilikom obrade zahtjeva.",
    "s007": (
        "Datum izdavanja računa u poruci promjene načina plaćanja nije jednak trenutnom datumu."
    ),
    "s008": (
        "Podaci za račun u poruci promjene načina plaćanja razlikuju se od "
        "podataka fiskaliziranog računa ili račun nije fiskaliziran."
    ),
    "s009": (
        "Datum izdavanja računa u poruci dostave podataka o napojnici je za "
        "više od dva dana manji od trenutnog datuma."
    ),
    "s010": (
        "Podaci za račun u poruci dostave podataka o napojnici razlikuju se "
        "od podataka fiskaliziranog računa ili račun nije fiskaliziran."
    ),
    "s011": (
        "Datum izdavanja računa u poruci promjene podataka računa nije jednak trenutnom datumu."
    ),
    "s012": (
        "Podaci za račun u poruci promjene podataka računa razlikuju se od "
        "podataka fiskaliziranog računa ili račun nije fiskaliziran."
    ),
    "s013": (
        "Račun sadrži restriktivne greške: "
        "#jedna ili više šifara restriktivnih grešaka koje sadrži račun#."
    ),
}
