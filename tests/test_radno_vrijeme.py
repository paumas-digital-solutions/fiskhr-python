from __future__ import annotations

from datetime import date, datetime

import pytest
from lxml import etree

from fiskhr.core.certs import Certificate
from fiskhr.core.xmldsig import sign_enveloped
from fiskhr.f1.radno_vrijeme import (
    BrisanjeRadnogVremena,
    DanUTjednu,
    DioDvokratnog,
    Dvokratno,
    DvokratnoIznimka,
    Iznimka,
    Jednokratno,
    JednokratnoIznimka,
    ParNepar,
    ParniNeparni,
    PoDogovoru,
    Poslovnica,
    RadnoVrijeme,
    Redovno,
    VrstaRadnogVremena,
    build_dohvati_radno_vrijeme_zahtjev,
    build_obrisi_radno_vrijeme_zahtjev,
    build_prijavi_radno_vrijeme_za_poslovnice_zahtjev,
    build_prijavi_radno_vrijeme_zahtjev,
    parse_dohvati_radno_vrijeme_odgovor,
)
from fiskhr.f1.service import schema_dir
from tests.conftest import TEST_OIB, make_rsa_key, make_self_signed_cert

MESSAGE_TIME = datetime(2026, 8, 12, 9, 0, 0)


@pytest.fixture(scope="module")
def xsd() -> etree.XMLSchema:
    return etree.XMLSchema(etree.parse(schema_dir() / "FiskalizacijaSchema.xsd"))


@pytest.fixture(scope="module")
def signer_cert() -> Certificate:
    key = make_rsa_key()
    return Certificate(private_key=key, certificate=make_self_signed_cert(key))


def _full_radno_vrijeme() -> RadnoVrijeme:
    return RadnoVrijeme(
        redovno=(
            Redovno(
                datum_od=date(2026, 9, 1),
                napomena="Standardno radno vrijeme",
                raspored=(
                    Jednokratno(
                        dan_u_tjednu=DanUTjednu.PONEDJELJAK, vrijeme_od="08:00", vrijeme_do="16:00"
                    ),
                    Jednokratno(
                        dan_u_tjednu=DanUTjednu.SUBOTA, vrijeme_od="08:00", vrijeme_do="12:00"
                    ),
                ),
            ),
            Redovno(
                datum_od=date(2026, 10, 1),
                raspored=(
                    Dvokratno(
                        dan_u_tjednu=DanUTjednu.UTORAK,
                        dio=DioDvokratnog.PRVI,
                        vrijeme_od="08:00",
                        vrijeme_do="12:00",
                    ),
                    Dvokratno(
                        dan_u_tjednu=DanUTjednu.UTORAK,
                        dio=DioDvokratnog.DRUGI,
                        vrijeme_od="16:00",
                        vrijeme_do="20:00",
                    ),
                ),
            ),
            Redovno(datum_od=date(2026, 11, 1), raspored=PoDogovoru()),
        ),
        iznimke=(
            Iznimka(
                datum=date(2026, 12, 25),
                raspored=JednokratnoIznimka(vrijeme_od="09:00", vrijeme_do="12:00"),
            ),
            Iznimka(
                datum=date(2026, 12, 31),
                raspored=(
                    DvokratnoIznimka(
                        dio=DioDvokratnog.PRVI, vrijeme_od="08:00", vrijeme_do="11:00"
                    ),
                    DvokratnoIznimka(
                        dio=DioDvokratnog.DRUGI, vrijeme_od="17:00", vrijeme_do="22:00"
                    ),
                ),
            ),
        ),
    )


def test_prijavi_validates_against_official_xsd(
    xsd: etree.XMLSchema, signer_cert: Certificate
) -> None:
    zahtjev = build_prijavi_radno_vrijeme_zahtjev(
        TEST_OIB, "POSL1", _full_radno_vrijeme(), TEST_OIB, datum_vrijeme=MESSAGE_TIME
    )
    xsd.assertValid(zahtjev)
    xsd.assertValid(etree.fromstring(sign_enveloped(zahtjev, signer_cert)))


def _poslovnice() -> tuple[Poslovnica, ...]:
    return (
        Poslovnica(
            ozn_pos_pr="POSL1",
            raspored=Redovno(
                datum_od=date(2026, 9, 1),
                raspored=(
                    Jednokratno(
                        dan_u_tjednu=DanUTjednu.PONEDJELJAK,
                        vrijeme_od="08:00",
                        vrijeme_do="16:00",
                    ),
                ),
            ),
        ),
        Poslovnica(
            ozn_pos_pr="POSL2",
            raspored=Iznimka(
                datum=date(2026, 12, 25),
                raspored=JednokratnoIznimka(vrijeme_od="09:00", vrijeme_do="12:00"),
            ),
        ),
    )


def test_prijavi_za_poslovnice_validates_against_official_xsd(
    xsd: etree.XMLSchema, signer_cert: Certificate
) -> None:
    zahtjev = build_prijavi_radno_vrijeme_za_poslovnice_zahtjev(
        TEST_OIB, _poslovnice(), TEST_OIB, datum_vrijeme=MESSAGE_TIME
    )
    xsd.assertValid(zahtjev)
    xsd.assertValid(etree.fromstring(sign_enveloped(zahtjev, signer_cert)))


def test_prijavi_za_poslovnice_end_to_end(signer_cert: Certificate) -> None:
    from fiskhr.f1.client import FiskalizacijaClient
    from fiskhr.testing import MockCis

    mock = MockCis()
    client = FiskalizacijaClient(signer_cert, transport=mock.transport())

    odgovor = client.prijavi_radno_vrijeme_za_poslovnice(
        TEST_OIB, _poslovnice(), TEST_OIB, datum_vrijeme=MESSAGE_TIME
    )

    assert odgovor.ok
    assert [p.ozn_pos_pr for p in odgovor.poslovnice] == ["POSL1", "POSL2"]
    assert all(p.poruka is not None and p.poruka.sifra == "p001" for p in odgovor.poslovnice)


def test_prijavi_za_poslovnice_caps_at_100() -> None:
    with pytest.raises(ValueError, match="1-100"):
        build_prijavi_radno_vrijeme_za_poslovnice_zahtjev(
            TEST_OIB, (), TEST_OIB, datum_vrijeme=MESSAGE_TIME
        )


def test_parni_neparni_schedule_validates(xsd: etree.XMLSchema) -> None:
    radno_vrijeme = RadnoVrijeme(
        redovno=(
            Redovno(
                datum_od=date(2026, 9, 1),
                raspored=(
                    ParniNeparni(
                        dan_u_tjednu=DanUTjednu.PRAZNIK,
                        par_nepar=ParNepar.PARNI,
                        vrijeme_od="10:00",
                        vrijeme_do="14:00",
                    ),
                ),
            ),
        )
    )
    zahtjev = build_prijavi_radno_vrijeme_zahtjev(
        TEST_OIB, "POSL1", radno_vrijeme, TEST_OIB, datum_vrijeme=MESSAGE_TIME
    )
    xsd.assertValid(zahtjev)


def test_obrisi_validates_against_official_xsd(xsd: etree.XMLSchema) -> None:
    brisanje = BrisanjeRadnogVremena(redovno_od=(date(2026, 9, 1),), iznimke=(date(2026, 12, 25),))
    zahtjev = build_obrisi_radno_vrijeme_zahtjev(
        TEST_OIB, "POSL1", brisanje, TEST_OIB, datum_vrijeme=MESSAGE_TIME
    )
    xsd.assertValid(zahtjev)


def test_dohvati_validates_against_official_xsd(xsd: etree.XMLSchema) -> None:
    zahtjev = build_dohvati_radno_vrijeme_zahtjev(
        TEST_OIB, "POSL1", VrstaRadnogVremena.SVE, TEST_OIB, datum_vrijeme=MESSAGE_TIME
    )
    xsd.assertValid(zahtjev)


def test_schedule_roundtrip_through_serialisation(xsd: etree.XMLSchema) -> None:
    # Serialise a full schedule, re-parse it from a synthetic DohvatiOdgovor,
    # and compare models — proves serialisation and parsing are inverses.
    original = _full_radno_vrijeme()
    zahtjev = build_prijavi_radno_vrijeme_zahtjev(
        TEST_OIB, "POSL1", original, TEST_OIB, datum_vrijeme=MESSAGE_TIME
    )
    ns = "{http://www.apis-it.hr/fin/2012/types/f73}"
    prostor = zahtjev.find(f"{ns}PoslovniProstor")
    assert prostor is not None

    odgovor_root = etree.fromstring(
        b'<tns:DohvatiRadnoVrijemeOdgovor Id="DohvatiRadnoVrijemeOdgovor"'
        b' xmlns:tns="http://www.apis-it.hr/fin/2012/types/f73">'
        b"<tns:Zaglavlje><tns:IdPoruke></tns:IdPoruke>"
        b"<tns:DatumVrijeme>12.08.2026T09:00:01</tns:DatumVrijeme></tns:Zaglavlje>"
        b"</tns:DohvatiRadnoVrijemeOdgovor>"
    )
    odgovor_root.append(prostor)
    xsd.assertValid(odgovor_root)

    parsed = parse_dohvati_radno_vrijeme_odgovor(odgovor_root)
    assert parsed.ok
    assert parsed.oib == TEST_OIB
    assert parsed.ozn_pos_pr == "POSL1"
    assert parsed.radno_vrijeme == original


def test_redovno_rejects_oversized_schedules() -> None:
    with pytest.raises(ValueError, match="at most 8"):
        Redovno(
            datum_od=date(2026, 9, 1),
            raspored=tuple(
                Jednokratno(
                    dan_u_tjednu=DanUTjednu.PONEDJELJAK, vrijeme_od="08:00", vrijeme_do="16:00"
                )
                for _ in range(9)
            ),
        )


def test_vrijeme_pattern_is_enforced() -> None:
    with pytest.raises(ValueError, match="pattern"):
        Jednokratno(dan_u_tjednu=DanUTjednu.PETAK, vrijeme_od="8:00", vrijeme_do="26:00")
