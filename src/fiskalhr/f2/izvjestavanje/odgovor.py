"""ApplicationResponse — telling the supplier their invoice was rejected.

Rejecting an eRačun is two messages, not one, and they go to different
places. This module builds the one that goes to the *supplier*: a UBL
``ApplicationResponse`` delivered to their access point. The other goes to
the Tax Administration as ``EvidentirajOdbijanje``
(`fiskalhr.f2.izvjestavanje.EIzvjestavanjeClient.evidentiraj_odbijanje`).
The specification is explicit that the second follows the first — "nakon
uspješnog slanja poruke Dobavljaču o odbijanju računa, Kupac šalje poreznoj
upravi na eIzvještavanje fiskalizacijsku poruku odbijanja računa sukladno
čl. 52. Zakona o fiskalizaciji" — so they live side by side here.

Both carry the same ``N``/``U``/``O`` reason code (`RazlogOdbijanja`), which
is what makes them one act rather than two. An intermediary may do this for
you: FINA's ``odbij`` sets the status and takes care of telling the
supplier, in which case this document is not needed for that route.

Built from the field model in "PU — Aplikacijski odgovor v1.1 (27.07.2026)"
(`docs/specs/f2/PU-AplikacijskiOdgovor-2026-07-27-v1.1.pdf`) and the
rejection model in `TS_odbijanje_eRacuna_HUP.pdf`. Note that the Tax
Administration's UBL bundle ships only the Invoice and CreditNote schemas,
so — unlike every other document this library produces — an
``ApplicationResponse`` cannot be XSD-validated against a vendored schema;
`tests/test_aplikacijski_odgovor.py` pins its shape instead.
"""

from __future__ import annotations

from datetime import date, time
from typing import cast

from lxml import etree

from fiskalhr.f2.izvjestavanje.models import RazlogOdbijanja
from fiskalhr.f2.ubl.models import OIB_ENDPOINT_SCHEME
from fiskalhr.f2.ubl.xml import CAC, CBC

__all__ = [
    "APPLICATION_RESPONSE_NS",
    "CUSTOMIZATION_ID",
    "KOD_ODBIJANJA",
    "LISTA_RAZLOGA",
    "odbijanje",
]

APPLICATION_RESPONSE_NS = "urn:oasis:names:specification:ubl:schema:xsd:ApplicationResponse-2"

CUSTOMIZATION_ID = "urn:mfin.gov.hr:AplikacijskiOdgovor-2025:1.0"
"""AR-BT-1 and AR-BT-2 — the same URN identifies the specification and the
business process (the latter matters for the access point's PMode)."""

KOD_ODBIJANJA = "RE"
"""AR-BT-10, UNCL 4343. ``RE`` (rejected) is the only code an
implementation must support; acceptance codes are optional and by prior
agreement between the parties."""

LISTA_RAZLOGA = "MFINVrstaRazlogaOdbijanja"
"""AR-BT-12 ``@listID`` — fixed for a rejection."""


def odbijanje(
    *,
    broj: str,
    datum_izdavanja: date,
    vrijeme_izdavanja: time | None = None,
    posiljatelj_oib: str,
    primatelj_oib: str,
    broj_racuna: str,
    datum_racuna: date,
    razlog: RazlogOdbijanja,
    opis: str,
    posiljatelj_oznaka: str | None = None,
    primatelj_oznaka: str | None = None,
) -> etree._Element:
    """Build the ``ApplicationResponse`` that rejects one eRačun.

    Args:
        broj: This response's own number (AR-BT-3), unique in the sender's
            records — it is not the invoice's number.
        datum_izdavanja: When the response is issued (AR-BT-4).
        vrijeme_izdavanja: Optional issue time (AR-BT-5), ``HH:MM:SS``
            without a timezone.
        posiljatelj_oib: OIB of the party rejecting the invoice — the buyer.
        primatelj_oib: OIB of the party being told — the supplier.
        broj_racuna: The rejected invoice's number (AR-BT-13).
        datum_racuna: The rejected invoice's issue date (AR-BT-14),
            mandatory.
        razlog: Why it is rejected (AR-BT-12) — the same ``N``/``U``/``O``
            code that goes to the Tax Administration, so that the supplier
            and the tax record agree.
        opis: The reason in words (AR-BT-11), mandatory for a rejection.
        posiljatelj_oznaka: Business-unit identifier of the sender, when the
            rejection comes from a sub-unit (AR-BT-7).
        primatelj_oznaka: The same for the receiver (AR-BT-9).

    Returns:
        The ``ApplicationResponse`` element, ready to be handed to an
        access point.

    Raises:
        ValueError: If ``opis`` is empty — the specification makes the
            reason mandatory for a rejection, and an empty one tells the
            supplier nothing.
    """
    if not opis.strip():
        raise ValueError("a rejection must state its reason (AR-BT-11 is mandatory for RE)")

    # lxml accepts a None key for the default namespace; the stubs don't
    # (same cast as `fiskalhr.f2.ubl.xml._nsmap`).
    nsmap = cast(
        "dict[str, str]",
        {None: APPLICATION_RESPONSE_NS, "cac": CAC, "cbc": CBC},
    )
    root = etree.Element(f"{{{APPLICATION_RESPONSE_NS}}}ApplicationResponse", nsmap=nsmap)
    _cbc(root, "CustomizationID", CUSTOMIZATION_ID)
    _cbc(root, "ProfileID", CUSTOMIZATION_ID)
    _cbc(root, "ID", broj)
    _cbc(root, "IssueDate", datum_izdavanja.isoformat())
    if vrijeme_izdavanja is not None:
        _cbc(root, "IssueTime", vrijeme_izdavanja.strftime("%H:%M:%S"))

    _party(root, "SenderParty", oib=posiljatelj_oib, oznaka=posiljatelj_oznaka)
    _party(root, "ReceiverParty", oib=primatelj_oib, oznaka=primatelj_oznaka)

    document_response = _cac(root, "DocumentResponse")
    response = _cac(document_response, "Response")
    _cbc(response, "ResponseCode", KOD_ODBIJANJA)
    _cbc(response, "Description", opis)
    status = _cac(response, "Status")
    _cbc(status, "StatusReasonCode", razlog.value, listID=LISTA_RAZLOGA)

    reference = _cac(document_response, "DocumentReference")
    _cbc(reference, "ID", broj_racuna)
    _cbc(reference, "IssueDate", datum_racuna.isoformat())
    return root


def _party(root: etree._Element, name: str, *, oib: str, oznaka: str | None) -> etree._Element:
    """A sender or receiver party: the electronic address, plus a business
    unit identifier when the rejection concerns one (AR-BT-7/9)."""
    party = _cac(root, name)
    _cbc(party, "EndpointID", oib, schemeID=OIB_ENDPOINT_SCHEME)
    if oznaka is not None:
        identification = _cac(party, "PartyIdentification")
        _cbc(identification, "ID", oznaka)
    return party


def _cac(parent: etree._Element, name: str) -> etree._Element:
    return etree.SubElement(parent, f"{{{CAC}}}{name}")


def _cbc(parent: etree._Element, name: str, text: str, **attrib: str) -> etree._Element:
    element = etree.SubElement(parent, f"{{{CBC}}}{name}", attrib=attrib)
    element.text = text
    return element
