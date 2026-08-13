"""The Phase 2 acid test: built invoices must pass the official validation —
XSD plus the complete HR CIUS 2025 Schematron — with zero findings."""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal

import pytest
from lxml import etree
from pydantic import ValidationError

from fiskalhr.f2.ubl import ERacunBuilder, KategorijaPdv, to_xml
from fiskalhr.f2.validation import validate
from fiskalhr.f2.validation.schematron import schematron_available

# Checksum-valid synthetic OIBs (see tests/conftest.py for the primary one).
OIB_IZDAVATELJ = "12345678903"
OIB_PRIMATELJ = "00000000001"
OIB_OPERATER = "12345678903"

needs_saxon = pytest.mark.skipif(
    not schematron_available(), reason="saxonche (fiskalhr[validation]) not installed"
)


def _builder() -> ERacunBuilder:
    return (
        ERacunBuilder()
        .izdavatelj(
            oib=OIB_IZDAVATELJ,
            naziv="Paumas j.d.o.o.",
            ulica="Ulica 1",
            grad="Zagreb",
            postanski_broj="10000",
            pravni_oblik="Trgovacki sud u Zagrebu, temeljni kapital 10 EUR",
        )
        .primatelj(
            oib=OIB_PRIMATELJ,
            naziv="Kupac d.o.o.",
            ulica="Ulica 2",
            grad="Rijeka",
            postanski_broj="51000",
        )
        .operater(oib=OIB_OPERATER, oznaka="Operater1")
        .broj("2026-42-P1-1")
        .datum_izdavanja(date(2026, 8, 13), time(12, 0, 0))
        .datum_isporuke(date(2026, 7, 31))
        .dospijece(date(2026, 9, 12))
        .placanje(iban="HR1210010051863000160", poziv_na_broj="HR00 42")
        .stavka(
            naziv="Licenca za softver",
            kpd="62.20.20",
            kolicina=1,
            cijena="100.00",
            pdv_stopa=25,
        )
    )


@needs_saxon
def test_built_invoice_passes_full_official_validation() -> None:
    xml = etree.tostring(_builder().to_xml())

    report = validate(xml)

    assert report.schematron_ran
    assert report.findings == (), [f"{f.rule}: {f.message}" for f in report.findings]


@needs_saxon
def test_multi_rate_invoice_passes_full_validation() -> None:
    builder = (
        _builder()
        .stavka(naziv="Knjiga", kpd="58.11.11", kolicina=2, cijena="10.00", pdv_stopa=5)
        .stavka(
            naziv="Novine",
            kpd="58.11.50",
            kolicina=3,
            cijena="2.00",
            pdv_stopa=13,
        )
        .stavka(
            naziv="Oslobodjena usluga",
            kpd="86.10.01",
            kolicina=1,
            cijena="50.00",
            kategorija=KategorijaPdv.OSLOBODJENO,
            razlog_oslobodjenja="Oslobodjeno PDV-a prema cl. 39. Zakona o PDV-u",
        )
    )
    racun = builder.build()
    report = validate(etree.tostring(to_xml(racun)))

    assert report.findings == (), [f"{f.rule}: {f.message}" for f in report.findings]
    # 100*0.25 + 20*0.05 + 6*0.13 = 25 + 1 + 0.78
    assert racun.ukupno_pdv == Decimal("26.78")
    assert racun.ukupno_s_pdv == Decimal("202.78")


@needs_saxon
def test_odobrenje_passes_full_validation() -> None:
    """A credit note (381) serialises as a UBL CreditNote: no KPD or due
    date required, preceding-invoice reference carried (HR-BR-6/25/4)."""
    builder = (
        ERacunBuilder()
        .izdavatelj(
            oib=OIB_IZDAVATELJ,
            naziv="Paumas j.d.o.o.",
            ulica="Ulica 1",
            grad="Zagreb",
            postanski_broj="10000",
        )
        .primatelj(
            oib=OIB_PRIMATELJ,
            naziv="Kupac d.o.o.",
            ulica="Ulica 2",
            grad="Rijeka",
            postanski_broj="51000",
        )
        .operater(oib=OIB_OPERATER, oznaka="Operater1")
        .broj("2026-43-P1-1")
        .datum_izdavanja(date(2026, 8, 20), time(9, 0, 0))
        .odobrenje("2026-42-P1-1", date(2026, 8, 13))
        .placanje(iban="HR1210010051863000160")
        .stavka(naziv="Storno licence", kolicina=1, cijena="100.00", pdv_stopa=25)
    )
    racun = builder.build()
    xml = to_xml(racun)

    assert etree.QName(xml).localname == "CreditNote"
    report = validate(etree.tostring(xml))
    assert report.schematron_ran
    assert report.findings == (), [f"{f.rule}: {f.message}" for f in report.findings]


@needs_saxon
def test_predujam_passes_full_validation() -> None:
    """An advance invoice (386) stays a UBL Invoice; KPD optional (HR-BR-25)."""
    racun = _builder().broj("2026-44-P1-1").vrsta("386").build()
    report = validate(etree.tostring(to_xml(racun)))
    assert report.schematron_ran
    assert report.findings == (), [f"{f.rule}: {f.message}" for f in report.findings]


def test_kpd_required_for_regular_invoice_only() -> None:
    with pytest.raises(ValidationError, match="HR-BR-25"):
        _builder().stavka(naziv="Bez KPD", kolicina=1, cijena="1.00", pdv_stopa=25).build()


def test_totals_group_by_category_and_rate() -> None:
    racun = (
        _builder()
        .stavka(naziv="Jos jedna", kpd="62.20.20", kolicina=1, cijena="60.00", pdv_stopa=25)
        .build()
    )
    grupe = racun.grupe_pdv
    assert grupe[(KategorijaPdv.STANDARDNA, Decimal("25"))] == Decimal("160.00")
    assert racun.ukupno_pdv == Decimal("40.00")


def test_xsd_valid_without_saxon() -> None:
    report = validate(etree.tostring(_builder().to_xml()), schematron=False)
    assert report.ok


def test_broj_rejects_whitespace() -> None:
    with pytest.raises(ValidationError):
        _builder().broj("2026 42").build()  # HR-BR-1


def test_standard_category_requires_positive_rate() -> None:
    with pytest.raises(ValidationError, match="HR-BR-S-10"):
        _builder().stavka(naziv="X", kpd="62.20.20", kolicina=1, cijena="1.00", pdv_stopa=0)


def test_exempt_category_requires_reason() -> None:
    with pytest.raises(ValidationError, match="razlog_oslobodjenja"):
        _builder().stavka(
            naziv="X",
            kpd="62.20.20",
            kolicina=1,
            cijena="1.00",
            kategorija=KategorijaPdv.OSLOBODJENO,
        )


def test_positive_payable_requires_due_date() -> None:
    builder = _builder()
    builder._data.pop("datum_dospijeca")
    with pytest.raises(ValidationError, match="HR-BR-4"):
        builder.build()


def test_invalid_oib_rejected() -> None:
    with pytest.raises(ValidationError, match="checksum"):
        ERacunBuilder().izdavatelj(
            oib="12345678901",
            naziv="X",
            ulica="U",
            grad="G",
            postanski_broj="10000",
        )
