"""The ApplicationResponse that rejects an eRačun, pinned to its field model.

The Tax Administration's UBL bundle ships no ApplicationResponse schema, so
there is nothing to validate against; these tests stand in for it, asserting
each business term lands at the path the specification names.
"""

from __future__ import annotations

from datetime import date, time

import pytest
from lxml import etree

from fiskalhr.f2.izvjestavanje import RazlogOdbijanja
from fiskalhr.f2.izvjestavanje.odgovor import (
    APPLICATION_RESPONSE_NS,
    CUSTOMIZATION_ID,
    odbijanje,
)
from fiskalhr.f2.ubl.xml import CAC, CBC

OIB_KUPAC = "11111111119"
OIB_DOBAVLJAC = "12345678903"


def _odgovor(**overrides: object) -> etree._Element:
    arguments: dict[str, object] = {
        "broj": "ODB-2026-1",
        "datum_izdavanja": date(2026, 9, 2),
        "posiljatelj_oib": OIB_KUPAC,
        "primatelj_oib": OIB_DOBAVLJAC,
        "broj_racuna": "2026-42-P1-1",
        "datum_racuna": date(2026, 8, 13),
        "razlog": RazlogOdbijanja.NEUSKLADJENOST_POREZ,
        "opis": "Pogrešna stopa PDV-a na stavci 2",
    }
    arguments.update(overrides)
    return odbijanje(**arguments)  # type: ignore[arg-type]


def _text(root: etree._Element, path: str) -> str | None:
    element = root.find(path)
    return element.text if element is not None else None


def test_document_is_an_application_response_with_the_hr_customization() -> None:
    root = _odgovor()

    assert root.tag == f"{{{APPLICATION_RESPONSE_NS}}}ApplicationResponse"
    assert _text(root, f"{{{CBC}}}CustomizationID") == CUSTOMIZATION_ID
    # AR-BT-2: the same URN is the business process, which the access
    # point's PMode keys on.
    assert _text(root, f"{{{CBC}}}ProfileID") == CUSTOMIZATION_ID


def test_carries_its_own_identity_not_the_invoices() -> None:
    root = _odgovor()

    assert _text(root, f"{{{CBC}}}ID") == "ODB-2026-1"
    assert _text(root, f"{{{CBC}}}IssueDate") == "2026-09-02"
    # AR-BT-13/14 — the invoice being rejected, kept separately.
    reference = f"{{{CAC}}}DocumentResponse/{{{CAC}}}DocumentReference"
    assert _text(root, f"{reference}/{{{CBC}}}ID") == "2026-42-P1-1"
    assert _text(root, f"{reference}/{{{CBC}}}IssueDate") == "2026-08-13"


def test_issue_time_is_optional_and_formatted_without_a_timezone() -> None:
    assert _odgovor().find(f"{{{CBC}}}IssueTime") is None

    with_time = _odgovor(vrijeme_izdavanja=time(14, 30, 5))

    assert _text(with_time, f"{{{CBC}}}IssueTime") == "14:30:05"


def test_parties_carry_endpoint_identifiers_under_the_oib_scheme() -> None:
    root = _odgovor()

    for name, oib in (
        (f"{{{CAC}}}SenderParty", OIB_KUPAC),
        (f"{{{CAC}}}ReceiverParty", OIB_DOBAVLJAC),
    ):
        endpoint = root.find(f"{name}/{{{CBC}}}EndpointID")
        assert endpoint is not None
        assert endpoint.text == oib
        assert endpoint.get("schemeID") == "9934"


def test_business_unit_identifiers_are_emitted_only_when_given() -> None:
    assert _odgovor().find(f"{{{CAC}}}SenderParty/{{{CAC}}}PartyIdentification") is None

    root = _odgovor(posiljatelj_oznaka="HR99:12345")

    assert (
        _text(root, f"{{{CAC}}}SenderParty/{{{CAC}}}PartyIdentification/{{{CBC}}}ID")
        == "HR99:12345"
    )


def test_response_is_a_rejection_with_its_reason() -> None:
    root = _odgovor()
    response = f"{{{CAC}}}DocumentResponse/{{{CAC}}}Response"

    # AR-BT-10: RE is the one code every implementation must support.
    assert _text(root, f"{response}/{{{CBC}}}ResponseCode") == "RE"
    assert _text(root, f"{response}/{{{CBC}}}Description") == "Pogrešna stopa PDV-a na stavci 2"


def test_reason_code_matches_the_tax_administration_codebook() -> None:
    """The same N/U/O code goes to the supplier here and to the Tax
    Administration in EvidentirajOdbijanje — that is what makes the two
    messages one rejection rather than two unrelated statements."""
    root = _odgovor(razlog=RazlogOdbijanja.OSTALO)

    code = root.find(
        f"{{{CAC}}}DocumentResponse/{{{CAC}}}Response/{{{CAC}}}Status/{{{CBC}}}StatusReasonCode"
    )
    assert code is not None
    assert code.text == "O"
    assert code.get("listID") == "MFINVrstaRazlogaOdbijanja"


def test_every_reason_code_round_trips() -> None:
    for razlog in RazlogOdbijanja:
        root = _odgovor(razlog=razlog)
        code = root.find(
            f"{{{CAC}}}DocumentResponse/{{{CAC}}}Response/{{{CAC}}}Status/{{{CBC}}}StatusReasonCode"
        )
        assert code is not None
        assert code.text == razlog.value


def test_a_rejection_without_a_reason_is_refused() -> None:
    """AR-BT-11 is mandatory for RE, and a blank reason tells the supplier
    nothing about what to correct."""
    with pytest.raises(ValueError, match="must state its reason"):
        _odgovor(opis="   ")


def test_element_order_follows_the_ubl_sequence() -> None:
    """UBL types are sequences, so order is part of validity — and there is
    no vendored schema to catch a mistake here."""
    root = _odgovor(vrijeme_izdavanja=time(9, 0, 0))

    assert [etree.QName(child).localname for child in root] == [
        "CustomizationID",
        "ProfileID",
        "ID",
        "IssueDate",
        "IssueTime",
        "SenderParty",
        "ReceiverParty",
        "DocumentResponse",
    ]

    response = root.find(f"{{{CAC}}}DocumentResponse")
    assert response is not None
    assert [etree.QName(child).localname for child in response] == [
        "Response",
        "DocumentReference",
    ]
