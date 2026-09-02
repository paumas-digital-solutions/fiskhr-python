"""Read a received eRačun into a reportable digest.

An invoice you *receive* has to be reported to the Tax Administration as an
incoming one (``EvidentirajERacun`` with ``vrsta`` ``U``), and it arrives as
UBL XML someone else produced. `evidencija_iz_xml` turns that document into
the `EvidencijaERacun` digest the reporting messages carry.

**Why the digest and not `fiskalhr.f2.ubl.ERacun`.** The builder model is
deliberately narrow: it computes totals from lines, and rejects anything it
cannot construct. A received invoice is the opposite situation — it exists,
it is valid, and it may use constructs the builder does not offer (advance
payments with a ``PrepaidAmount``, an issuer outside the VAT system, a
business-unit identifier). Parsing into the digest reports what the document
*says* rather than what this library could have built, so an invoice never
becomes unreportable because of a gap in the builder.

That also means amounts are read, not recomputed. If a sender's totals
disagree with their own lines, the report mirrors the invoice — which is
what the recipient is required to report, and what makes a discrepancy
visible to the Tax Administration rather than silently corrected here.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from lxml import etree
from pydantic import ValidationError

from fiskalhr.core.errors import FiskalizacijaError
from fiskalhr.f2.fiskalizacija.models import (
    DokumentPopust,
    DokumentTrosak,
    DokumentUkupanIznos,
    EvidencijaERacun,
    Izdavatelj,
    PrethodniERacun,
    PrijenosSredstava,
    Primatelj,
    RaspodjelaPdv,
    StavkaEvidencije,
)
from fiskalhr.f2.ubl.models import KategorijaPdv, hr_oznaka
from fiskalhr.f2.ubl.xml import CAC, CBC, CREDITNOTE_NS

__all__ = ["evidencija_iz_xml"]


class ERacunParseError(FiskalizacijaError):
    """The document is not a UBL eRačun this library can report."""


def evidencija_iz_xml(document: etree._Element | bytes) -> EvidencijaERacun:
    """Parse a UBL Invoice or CreditNote into a reportable digest.

    Args:
        document: The received eRačun, as bytes or an lxml element.

    Returns:
        The `EvidencijaERacun` digest, ready for
        `fiskalhr.f2.fiskalizacija.EFiskalizacijaClient.evidentiraj_ulazni`.

    Raises:
        ERacunParseError: If the document is not a UBL Invoice/CreditNote,
            is missing something every eRačun must carry, or carries a value
            the reporting schema rejects — an OIB that fails its checksum,
            most often. The digest models validate as strictly for a
            received invoice as for one this library built, because the Tax
            Administration will apply the same rules to the report.
    """
    root = _root(document)
    odobrenje = etree.QName(root).namespace == CREDITNOTE_NS
    type_code = "CreditNoteTypeCode" if odobrenje else "InvoiceTypeCode"

    valuta = _text(root, "DocumentCurrencyCode") or "EUR"
    total = _child(root, "LegalMonetaryTotal")
    if total is None:
        raise ERacunParseError("document carries no LegalMonetaryTotal")

    try:
        return _evidencija(root, total, odobrenje=odobrenje, valuta=valuta, type_code=type_code)
    except ValidationError as exc:
        # Pydantic's multi-error dump is unreadable next to the document it
        # came from; name the fields and keep the original as the cause.
        errors = exc.errors()
        fields = ", ".join(".".join(str(part) for part in error["loc"]) for error in errors)
        raise ERacunParseError(
            f"the received eRačun cannot be reported as it stands ({fields}): {errors[0]['msg']}"
        ) from exc


def _evidencija(
    root: etree._Element,
    total: etree._Element,
    *,
    odobrenje: bool,
    valuta: str,
    type_code: str,
) -> EvidencijaERacun:
    return EvidencijaERacun(
        broj=_required(root, "ID"),
        datum_izdavanja=_required_date(root, "IssueDate"),
        vrsta_dokumenta=_text(root, type_code) or ("381" if odobrenje else "380"),
        valuta=valuta,
        datum_dospijeca=_due_date(root, odobrenje=odobrenje),
        vrsta_poslovnog_procesa=_text(root, "ProfileID") or "P1",
        referenca_na_ugovor=_deep_text(root, "ContractDocumentReference", "ID"),
        datum_isporuke=_optional_date(_child(root, "Delivery"), "ActualDeliveryDate"),
        prethodni_eracuni=_prethodni(root),
        izdavatelj=_izdavatelj(root),
        primatelj=_primatelj(root),
        prijenosi_sredstava=_prijenosi(root),
        ukupan_iznos=_ukupan_iznos(root, total),
        raspodjele_pdv=_raspodjele(root),
        popusti=tuple(_popusti(root)),
        troskovi=tuple(_troskovi(root)),
        stavke=_stavke(root, odobrenje=odobrenje),
    )


def _root(document: etree._Element | bytes) -> etree._Element:
    if isinstance(document, bytes):
        try:
            return etree.fromstring(document)
        except etree.XMLSyntaxError as exc:
            raise ERacunParseError(f"document is not well-formed XML: {exc}") from exc
    return document


def _izdavatelj(root: etree._Element) -> Izdavatelj:
    party = _child(root, "AccountingSupplierParty")
    if party is None:
        raise ERacunParseError("document carries no AccountingSupplierParty")
    # The operator (HR-BT-4/5) rides in SellerContact, beside the party.
    contact = _child(party, "SellerContact")
    operater = _text(contact, "ID") if contact is not None else None
    oib = _party_oib(party)
    return Izdavatelj(
        ime=_party_name(party),
        oib=oib,
        # HR-BR-9 makes the operator OIB mandatory, but a received document
        # is not ours to fix; falling back to the issuer keeps a reportable
        # digest rather than refusing the whole invoice.
        oib_operatera=operater or oib,
    )


def _primatelj(root: etree._Element) -> Primatelj:
    party = _child(root, "AccountingCustomerParty")
    if party is None:
        raise ERacunParseError("document carries no AccountingCustomerParty")
    return Primatelj(ime=_party_name(party), oib=_party_oib(party))


def _party_name(party: etree._Element) -> str:
    legal = _descendant(party, "PartyLegalEntity")
    name = _text(legal, "RegistrationName") if legal is not None else None
    if name:
        return name
    fallback = _deep_text(party, "PartyName", "Name")
    if fallback:
        return fallback
    raise ERacunParseError("party carries neither a RegistrationName nor a PartyName")


def _party_oib(party: etree._Element) -> str:
    """The OIB, from PartyTaxScheme/CompanyID or the endpoint identifier.

    A party outside the VAT system carries a bare OIB under TaxScheme
    ``FRE`` rather than the ``HR``-prefixed VAT identifier, so the prefix is
    stripped rather than required.
    """
    scheme = _descendant(party, "PartyTaxScheme")
    company = _text(scheme, "CompanyID") if scheme is not None else None
    if company:
        return company.removeprefix("HR").strip()
    endpoint = _descendant(party, "EndpointID")
    if endpoint is not None and endpoint.text:
        return endpoint.text.strip()
    raise ERacunParseError("party carries no OIB (PartyTaxScheme/CompanyID or EndpointID)")


def _prethodni(root: etree._Element) -> tuple[PrethodniERacun, ...]:
    references = []
    for billing in root.findall(f"{{{CAC}}}BillingReference"):
        document = _child(billing, "InvoiceDocumentReference")
        if document is None:
            continue
        broj = _text(document, "ID")
        datum = _optional_date(document, "IssueDate")
        if broj and datum is not None:
            references.append(PrethodniERacun(broj=broj, datum_izdavanja=datum))
    return tuple(references)


def _prijenosi(root: etree._Element) -> tuple[PrijenosSredstava, ...]:
    transfers = []
    for means in root.findall(f"{{{CAC}}}PaymentMeans"):
        account = _child(means, "PayeeFinancialAccount")
        if account is None:
            continue
        iban = _text(account, "ID")
        if not iban:
            continue
        transfers.append(
            PrijenosSredstava(
                iban=iban,
                naziv_racuna=_text(account, "Name"),
                pruzatelj_platnih_usluga=_deep_text(account, "FinancialInstitutionBranch", "ID"),
            )
        )
    return tuple(transfers)


def _ukupan_iznos(root: etree._Element, total: etree._Element) -> DokumentUkupanIznos:
    tax_total = _child(root, "TaxTotal")
    pdv = _decimal(_text(tax_total, "TaxAmount")) if tax_total is not None else None
    return DokumentUkupanIznos(
        neto=_required_decimal(total, "LineExtensionAmount"),
        popust=_decimal(_text(total, "AllowanceTotalAmount")),
        trosak=_decimal(_text(total, "ChargeTotalAmount")),
        iznos_bez_pdv=_required_decimal(total, "TaxExclusiveAmount"),
        pdv=pdv if pdv is not None else Decimal("0.00"),
        iznos_s_pdv=_required_decimal(total, "TaxInclusiveAmount"),
        placeni_iznos=_decimal(_text(total, "PrepaidAmount")),
        iznos_koji_dospijeva=_required_decimal(total, "PayableAmount"),
    )


def _raspodjele(root: etree._Element) -> tuple[RaspodjelaPdv, ...]:
    tax_total = _child(root, "TaxTotal")
    if tax_total is None:
        raise ERacunParseError("document carries no TaxTotal")
    subtotals = []
    for subtotal in tax_total.findall(f"{{{CAC}}}TaxSubtotal"):
        category = _child(subtotal, "TaxCategory")
        if category is None:
            continue
        kategorija = _kategorija(_text(category, "ID"))
        stopa = _decimal(_text(category, "Percent"))
        subtotals.append(
            RaspodjelaPdv(
                kategorija=kategorija,
                osnovica=_required_decimal(subtotal, "TaxableAmount"),
                iznos=_required_decimal(subtotal, "TaxAmount"),
                stopa=stopa,
                razlog_oslobodjenja=_text(category, "TaxExemptionReason"),
                razlog_oslobodjenja_kod=_text(category, "TaxExemptionReasonCode"),
                # UBL carries the HR mark (HR-BT-22) on lines and on the HR
                # extension, but not on a document-level TaxSubtotal, so it
                # is derived from category and rate exactly as the builder
                # derives it. Reporting it only for invoices that happen to
                # spell it out would make the digest depend on the sender's
                # serialiser rather than on the invoice.
                hr_oznaka=_text(category, "Name")
                or hr_oznaka(kategorija, stopa if stopa is not None else Decimal("0")),
            )
        )
    if not subtotals:
        raise ERacunParseError("document carries no TaxSubtotal")
    return tuple(subtotals)


def _popusti(root: etree._Element) -> list[DokumentPopust]:
    return [
        DokumentPopust(
            iznos=_required_decimal(allowance, "Amount"),
            kategorija=_kategorija(_deep_text(allowance, "TaxCategory", "ID")),
            stopa=_decimal(_deep_text(allowance, "TaxCategory", "Percent")),
            razlog=_text(allowance, "AllowanceChargeReason"),
            razlog_kod=_text(allowance, "AllowanceChargeReasonCode"),
        )
        for allowance in _allowance_charges(root, charge=False)
    ]


def _troskovi(root: etree._Element) -> list[DokumentTrosak]:
    return [
        DokumentTrosak(
            iznos=_required_decimal(charge, "Amount"),
            kategorija=_kategorija(_deep_text(charge, "TaxCategory", "ID")),
            hr_oznaka=_deep_text(charge, "TaxCategory", "Name"),
            stopa=_decimal(_deep_text(charge, "TaxCategory", "Percent")),
            # E/AE/O charges carry the reason as a TaxExemptionReason
            # (HR-BR-13); a standard-rated one states it once, as the
            # allowance/charge reason. Both land in the same digest field.
            razlog_oslobodjenja=_deep_text(charge, "TaxCategory", "TaxExemptionReason")
            or _text(charge, "AllowanceChargeReason"),
            razlog_oslobodjenja_kod=_deep_text(charge, "TaxCategory", "TaxExemptionReasonCode"),
        )
        for charge in _allowance_charges(root, charge=True)
    ]


def _allowance_charges(root: etree._Element, *, charge: bool) -> list[etree._Element]:
    wanted = "true" if charge else "false"
    return [
        element
        for element in root.findall(f"{{{CAC}}}AllowanceCharge")
        if (_text(element, "ChargeIndicator") or "").lower() == wanted
    ]


def _stavke(root: etree._Element, *, odobrenje: bool) -> tuple[StavkaEvidencije, ...]:
    line_name = "CreditNoteLine" if odobrenje else "InvoiceLine"
    quantity_name = "CreditedQuantity" if odobrenje else "InvoicedQuantity"
    lines = []
    for line in root.findall(f"{{{CAC}}}{line_name}"):
        item = _child(line, "Item")
        if item is None:
            raise ERacunParseError(f"{line_name} carries no Item")
        category = _child(item, "ClassifiedTaxCategory")
        quantity = _child(line, quantity_name)
        price = _child(line, "Price")
        base_quantity = _child(price, "BaseQuantity") if price is not None else None
        lines.append(
            StavkaEvidencije(
                kolicina=_decimal(quantity.text if quantity is not None else None) or Decimal("0"),
                jedinica=(quantity.get("unitCode") if quantity is not None else None) or "H87",
                neto=_required_decimal(line, "LineExtensionAmount"),
                cijena=_decimal(_text(price, "PriceAmount") if price is not None else None)
                or Decimal("0"),
                osnovna_kolicina=_decimal(
                    base_quantity.text if base_quantity is not None else None
                ),
                jedinica_osnovne_kolicine=(
                    base_quantity.get("unitCode") if base_quantity is not None else None
                ),
                kategorija=_kategorija(_text(category, "ID") if category is not None else None),
                stopa=_decimal(_text(category, "Percent") if category is not None else None),
                naziv=_text(item, "Name") or "",
                opis=_text(item, "Description"),
                hr_oznaka=_text(category, "Name") if category is not None else None,
                kpd=_deep_text(item, "CommodityClassification", "ItemClassificationCode"),
            )
        )
    if not lines:
        raise ERacunParseError(f"document carries no {line_name}")
    return tuple(lines)


def _due_date(root: etree._Element, *, odobrenje: bool) -> date | None:
    """``DueDate`` on an Invoice; a CreditNote keeps it in PaymentMeans."""
    if not odobrenje:
        return _optional_date(root, "DueDate")
    for means in root.findall(f"{{{CAC}}}PaymentMeans"):
        due = _optional_date(means, "PaymentDueDate")
        if due is not None:
            return due
    return None


def _kategorija(value: str | None) -> KategorijaPdv:
    if value is None:
        raise ERacunParseError("a tax category carries no ID")
    try:
        return KategorijaPdv(value)
    except ValueError as exc:
        raise ERacunParseError(f"unknown VAT category {value!r}") from exc


def _child(parent: etree._Element | None, name: str) -> etree._Element | None:
    """A direct child by name, trying the cac then cbc namespace."""
    if parent is None:
        return None
    for namespace in (CAC, CBC):
        element = parent.find(f"{{{namespace}}}{name}")
        if element is not None:
            return element
    return None


def _descendant(parent: etree._Element, name: str) -> etree._Element | None:
    for namespace in (CAC, CBC):
        element = parent.find(f".//{{{namespace}}}{name}")
        if element is not None:
            return element
    return None


def _text(parent: etree._Element | None, name: str) -> str | None:
    if parent is None:
        return None
    element = _child(parent, name)
    if element is None:
        element = _descendant(parent, name)
    if element is None or element.text is None:
        return None
    return element.text.strip() or None


def _deep_text(parent: etree._Element, container: str, name: str) -> str | None:
    element = _descendant(parent, container)
    return _text(element, name) if element is not None else None


def _required(parent: etree._Element, name: str) -> str:
    value = _text(parent, name)
    if value is None:
        raise ERacunParseError(f"document carries no {name}")
    return value


def _decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ERacunParseError(f"{value!r} is not a number") from exc


def _required_decimal(parent: etree._Element, name: str) -> Decimal:
    value = _decimal(_text(parent, name))
    if value is None:
        raise ERacunParseError(f"document carries no {name}")
    return value


def _optional_date(parent: etree._Element | None, name: str) -> date | None:
    value = _text(parent, name)
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ERacunParseError(f"{name} {value!r} is not an ISO date") from exc


def _required_date(parent: etree._Element, name: str) -> date:
    value = _optional_date(parent, name)
    if value is None:
        raise ERacunParseError(f"document carries no {name}")
    return value
