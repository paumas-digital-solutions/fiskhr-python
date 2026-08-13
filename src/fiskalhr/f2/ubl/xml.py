"""Serialisation of `ERacun` models to UBL 2.1 Invoice documents.

Element order follows the UBL schema sequences exactly, mirroring the
official Tax Administration examples. Optional elements are emitted only
when set — HR-BR-33 forbids empty elements (except the signature slot,
which is deliberately included as in the official examples, reserving the
place for a XAdES signature).
"""

from __future__ import annotations

from decimal import Decimal
from typing import cast

from lxml import etree

from fiskalhr.f2.ubl.models import (
    CUSTOMIZATION_ID,
    OIB_ENDPOINT_SCHEME,
    ERacun,
    KategorijaPdv,
    Stranka,
    hr_oznaka,
)

__all__ = ["to_xml"]

INVOICE_NS = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
EXT = "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2"
SIG = "urn:oasis:names:specification:ubl:schema:xsd:CommonSignatureComponents-2"
SAC = "urn:oasis:names:specification:ubl:schema:xsd:SignatureAggregateComponents-2"
HREXTAC = "urn:mfin.gov.hr:schema:xsd:HRExtensionAggregateComponents-1"

# lxml accepts a None key for the default namespace; the stubs don't.
_NSMAP = cast(
    "dict[str, str]",
    {
        None: INVOICE_NS,
        "cac": CAC,
        "cbc": CBC,
        "ext": EXT,
        "sig": SIG,
        "sac": SAC,
        "hrextac": HREXTAC,
    },
)

_HR_EXTENSION_CATEGORIES = (KategorijaPdv.OSLOBODJENO, KategorijaPdv.NE_PODLIJEZE)
"""Categories whose presence requires the HRFISK20Data extension (HR-BR-26,
HR-BR-29/32); mirrors which official examples carry the extension."""


def _iznos(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):.2f}"


def _broj(value: Decimal) -> str:
    """Plain decimal without exponent (quantities, rates, unit prices)."""
    return format(value.normalize(), "f")


def _cbc(parent: etree._Element, name: str, text: str, **attrib: str) -> etree._Element:
    element = etree.SubElement(parent, f"{{{CBC}}}{name}", attrib=attrib)
    element.text = text
    return element


def _cac(parent: etree._Element, name: str) -> etree._Element:
    return etree.SubElement(parent, f"{{{CAC}}}{name}")


def _signature_slot(extensions: etree._Element) -> None:
    extension = etree.SubElement(extensions, f"{{{EXT}}}UBLExtension")
    content = etree.SubElement(extension, f"{{{EXT}}}ExtensionContent")
    signatures = etree.SubElement(content, f"{{{SIG}}}UBLDocumentSignatures")
    etree.SubElement(signatures, f"{{{SAC}}}SignatureInformation")


def _hrfisk20_extension(extensions: etree._Element, racun: ERacun) -> None:
    """HRFISK20Data — the HR VAT breakdown (HR-BG-2), shaped like the
    official examples: HRTaxTotal with per-group HRTaxSubtotals, plus
    HRLegalMonetaryTotal with the out-of-scope amount (HR-BR-32)."""
    extension = etree.SubElement(extensions, f"{{{EXT}}}UBLExtension")
    content = etree.SubElement(extension, f"{{{EXT}}}ExtensionContent")
    data = etree.SubElement(content, f"{{{HREXTAC}}}HRFISK20Data")

    tax_total = etree.SubElement(data, f"{{{HREXTAC}}}HRTaxTotal")
    _cbc(tax_total, "TaxAmount", _iznos(racun.ukupno_pdv), currencyID=racun.valuta)
    for (kategorija, stopa), osnovica in racun.grupe_pdv.items():
        subtotal = etree.SubElement(tax_total, f"{{{HREXTAC}}}HRTaxSubtotal")
        _cbc(subtotal, "TaxableAmount", _iznos(osnovica), currencyID=racun.valuta)
        iznos_pdv = (osnovica * stopa / 100).quantize(Decimal("0.01"))
        _cbc(subtotal, "TaxAmount", _iznos(iznos_pdv), currencyID=racun.valuta)
        category = etree.SubElement(subtotal, f"{{{HREXTAC}}}HRTaxCategory")
        _cbc(category, "ID", kategorija.value)
        oznaka = hr_oznaka(kategorija, stopa)
        if oznaka is not None:
            _cbc(category, "Name", oznaka)
        _cbc(category, "Percent", _broj(stopa))
        for reason in sorted(
            {
                s.razlog_oslobodjenja
                for s in racun.stavke
                if (s.kategorija, s.pdv_stopa) == (kategorija, stopa) and s.razlog_oslobodjenja
            }
        ):
            _cbc(category, "TaxExemptionReason", reason)
        scheme = etree.SubElement(category, f"{{{HREXTAC}}}HRTaxScheme")
        _cbc(scheme, "ID", "VAT")

    monetary = etree.SubElement(data, f"{{{HREXTAC}}}HRLegalMonetaryTotal")
    _cbc(monetary, "TaxExclusiveAmount", _iznos(racun.ukupno_neto), currencyID=racun.valuta)
    out_of_scope = sum(
        (s.neto for s in racun.stavke if s.kategorija is KategorijaPdv.NE_PODLIJEZE),
        Decimal("0.00"),
    )
    amount = etree.SubElement(monetary, f"{{{HREXTAC}}}OutOfScopeOfVATAmount")
    amount.set("currencyID", racun.valuta)
    amount.text = _iznos(out_of_scope)


def _party(parent: etree._Element, name: str, stranka: Stranka) -> etree._Element:
    wrapper = _cac(parent, name)
    party = _cac(wrapper, "Party")
    _cbc(party, "EndpointID", stranka.endpoint, schemeID=OIB_ENDPOINT_SCHEME)

    address = _cac(party, "PostalAddress")
    _cbc(address, "StreetName", stranka.adresa.ulica)
    _cbc(address, "CityName", stranka.adresa.grad)
    _cbc(address, "PostalZone", stranka.adresa.postanski_broj)
    country = _cac(address, "Country")
    _cbc(country, "IdentificationCode", stranka.adresa.drzava)

    tax_scheme = _cac(party, "PartyTaxScheme")
    _cbc(tax_scheme, "CompanyID", f"HR{stranka.oib}")
    _cbc(_cac(tax_scheme, "TaxScheme"), "ID", "VAT")

    legal = _cac(party, "PartyLegalEntity")
    _cbc(legal, "RegistrationName", stranka.naziv)
    if stranka.pravni_oblik is not None:
        _cbc(legal, "CompanyLegalForm", stranka.pravni_oblik)
    return wrapper


def to_xml(racun: ERacun) -> etree._Element:
    """Serialise to a UBL Invoice element (unsigned, signature slot ready)."""
    root = etree.Element(f"{{{INVOICE_NS}}}Invoice", nsmap=_NSMAP)
    extensions = etree.SubElement(root, f"{{{EXT}}}UBLExtensions")
    _signature_slot(extensions)
    if any(s.kategorija in _HR_EXTENSION_CATEGORIES for s in racun.stavke):
        _hrfisk20_extension(extensions, racun)

    _cbc(root, "CustomizationID", CUSTOMIZATION_ID)
    _cbc(root, "ProfileID", racun.profil)
    _cbc(root, "ID", racun.broj)
    _cbc(root, "IssueDate", racun.datum_izdavanja.isoformat())
    _cbc(root, "IssueTime", racun.vrijeme_izdavanja.strftime("%H:%M:%S"))
    if racun.datum_dospijeca is not None:
        _cbc(root, "DueDate", racun.datum_dospijeca.isoformat())
    _cbc(root, "InvoiceTypeCode", racun.vrsta)
    if racun.napomena is not None:
        _cbc(root, "Note", racun.napomena)
    _cbc(root, "DocumentCurrencyCode", racun.valuta)

    supplier = _party(root, "AccountingSupplierParty", racun.izdavatelj)
    contact = _cac(supplier, "SellerContact")
    _cbc(contact, "ID", racun.operater.oib)
    _cbc(contact, "Name", racun.operater.oznaka)

    _party(root, "AccountingCustomerParty", racun.primatelj)

    if racun.datum_isporuke is not None:
        delivery = _cac(root, "Delivery")
        _cbc(delivery, "ActualDeliveryDate", racun.datum_isporuke.isoformat())

    payment = _cac(root, "PaymentMeans")
    _cbc(payment, "PaymentMeansCode", racun.nacin_placanja)
    if racun.opis_placanja is not None:
        _cbc(payment, "InstructionNote", racun.opis_placanja)
    if racun.poziv_na_broj is not None:
        _cbc(payment, "PaymentID", racun.poziv_na_broj)
    if racun.iban is not None:
        account = _cac(payment, "PayeeFinancialAccount")
        _cbc(account, "ID", racun.iban)

    tax_total = _cac(root, "TaxTotal")
    _cbc(tax_total, "TaxAmount", _iznos(racun.ukupno_pdv), currencyID=racun.valuta)
    for (kategorija, stopa), osnovica in racun.grupe_pdv.items():
        subtotal = _cac(tax_total, "TaxSubtotal")
        _cbc(subtotal, "TaxableAmount", _iznos(osnovica), currencyID=racun.valuta)
        iznos_pdv = (osnovica * stopa / 100).quantize(Decimal("0.01"))
        _cbc(subtotal, "TaxAmount", _iznos(iznos_pdv), currencyID=racun.valuta)
        category = _cac(subtotal, "TaxCategory")
        _cbc(category, "ID", kategorija.value)
        _cbc(category, "Percent", _broj(stopa))
        reasons = {
            s.razlog_oslobodjenja
            for s in racun.stavke
            if (s.kategorija, s.pdv_stopa) == (kategorija, stopa) and s.razlog_oslobodjenja
        }
        for reason in sorted(reasons):
            _cbc(category, "TaxExemptionReason", reason)
        _cbc(_cac(category, "TaxScheme"), "ID", "VAT")

    total = _cac(root, "LegalMonetaryTotal")
    _cbc(total, "LineExtensionAmount", _iznos(racun.ukupno_neto), currencyID=racun.valuta)
    _cbc(total, "TaxExclusiveAmount", _iznos(racun.ukupno_neto), currencyID=racun.valuta)
    _cbc(total, "TaxInclusiveAmount", _iznos(racun.ukupno_s_pdv), currencyID=racun.valuta)
    _cbc(total, "PayableAmount", _iznos(racun.ukupno_s_pdv), currencyID=racun.valuta)

    for index, stavka in enumerate(racun.stavke, start=1):
        line = _cac(root, "InvoiceLine")
        _cbc(line, "ID", str(index))
        _cbc(line, "InvoicedQuantity", _broj(stavka.kolicina), unitCode=stavka.jedinica)
        _cbc(line, "LineExtensionAmount", _iznos(stavka.neto), currencyID=racun.valuta)

        item = _cac(line, "Item")
        if stavka.opis is not None:
            _cbc(item, "Description", stavka.opis)
        _cbc(item, "Name", stavka.naziv)
        classification = _cac(item, "CommodityClassification")
        _cbc(classification, "ItemClassificationCode", stavka.kpd, listID="CG")
        category = _cac(item, "ClassifiedTaxCategory")
        _cbc(category, "ID", stavka.kategorija.value)
        oznaka = hr_oznaka(stavka.kategorija, stavka.pdv_stopa)
        if oznaka is not None:
            _cbc(category, "Name", oznaka)
        _cbc(category, "Percent", _broj(stavka.pdv_stopa))
        if stavka.razlog_oslobodjenja is not None:
            _cbc(category, "TaxExemptionReason", stavka.razlog_oslobodjenja)
        _cbc(_cac(category, "TaxScheme"), "ID", "VAT")

        price = _cac(line, "Price")
        _cbc(price, "PriceAmount", _broj(stavka.cijena), currencyID=racun.valuta)

    return root
