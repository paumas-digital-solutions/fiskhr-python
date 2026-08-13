"""eFiskalizacija (F2 reporting): messages, XAdES-B signing, client, mock.

The built ``EvidentirajERacunZahtjev`` must validate against the official
eFiskalizacijaSchema.xsd once signed, and the XAdES signature must match
the spec profile (tech spec ch. 11): two references, enveloped-signature +
exc-c14n transforms, RSA-SHA256, SignedProperties with SigningCertificateV2.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from lxml import etree

from fiskalhr.core.certs import Certificate
from fiskalhr.core.errors import CisError, SignatureVerificationError, TransportError
from fiskalhr.core.transport import unwrap_soap, wrap_soap
from fiskalhr.core.xades import sign_xades_enveloped, verify_xades_enveloped
from fiskalhr.f2.fiskalizacija import (
    EFiskalizacijaClient,
    EvidencijaERacun,
    VrstaERacuna,
    build_evidentiraj_eracun_zahtjev,
)
from fiskalhr.f2.service import efiskalizacija_schema_path
from fiskalhr.f2.ubl import ERacunBuilder, KategorijaPdv
from fiskalhr.testing import MockEFiskalizacija
from tests.conftest import make_self_signed_cert

DS_NS = "http://www.w3.org/2000/09/xmldsig#"
XADES_NS = "http://uri.etsi.org/01903/v1.3.2#"

SLANJE = datetime(2026, 8, 13, 12, 0, 36, 142400)


@pytest.fixture(scope="module")
def xsd() -> etree.XMLSchema:
    return etree.XMLSchema(etree.parse(efiskalizacija_schema_path()))


@pytest.fixture(scope="module")
def certificate() -> Certificate:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return Certificate(private_key=key, certificate=make_self_signed_cert(key))


def _eracun_builder() -> ERacunBuilder:
    return (
        ERacunBuilder()
        .izdavatelj(
            oib="12345678903",
            naziv="Paumas j.d.o.o.",
            ulica="Ulica 1",
            grad="Zagreb",
            postanski_broj="10000",
        )
        .primatelj(
            oib="00000000001",
            naziv="Kupac d.o.o.",
            ulica="Ulica 2",
            grad="Rijeka",
            postanski_broj="51000",
        )
        .operater(oib="12345678903", oznaka="Operater1")
        .broj("2026-42-P1-1")
        .datum_izdavanja(date(2026, 8, 13), time(12, 0, 0))
        .datum_isporuke(date(2026, 7, 31))
        .dospijece(date(2026, 9, 12))
        .placanje(iban="HR1210010051863000160", poziv_na_broj="HR00 42")
        .stavka(
            naziv="Licenca za softver", kpd="62.20.20", kolicina=1, cijena="100.00", pdv_stopa=25
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


def test_from_eracuna_maps_totals_and_breakdown() -> None:
    racun = _eracun_builder().build()
    evidencija = EvidencijaERacun.from_eracuna(racun)

    assert evidencija.broj == "2026-42-P1-1"
    assert evidencija.izdavatelj.oib == "12345678903"
    assert evidencija.izdavatelj.oib_operatera == "12345678903"
    assert evidencija.ukupan_iznos.neto == Decimal("150.00")
    assert evidencija.ukupan_iznos.pdv == Decimal("25.00")
    assert evidencija.ukupan_iznos.iznos_koji_dospijeva == Decimal("175.00")
    assert evidencija.prijenosi_sredstava[0].iban == "HR1210010051863000160"

    po_kategoriji = {r.kategorija: r for r in evidencija.raspodjele_pdv}
    standard = po_kategoriji[KategorijaPdv.STANDARDNA]
    assert (standard.osnovica, standard.iznos) == (Decimal("100.00"), Decimal("25.00"))
    assert standard.hr_oznaka == "HR:PDV25"
    exempt = po_kategoriji[KategorijaPdv.OSLOBODJENO]
    assert exempt.hr_oznaka == "HR:E"
    assert exempt.razlog_oslobodjenja is not None
    assert [s.kpd for s in evidencija.stavke] == ["62.20.20", "86.10.01"]


def test_signed_zahtjev_validates_against_official_xsd(
    xsd: etree.XMLSchema, certificate: Certificate
) -> None:
    racun = _eracun_builder().build()
    zahtjev = build_evidentiraj_eracun_zahtjev(
        (EvidencijaERacun.from_eracuna(racun),),
        vrsta=VrstaERacuna.IZLAZNI,
        id_zahtjeva="test-request-1",
        datum_vrijeme_slanja=SLANJE,
    )
    signed = sign_xades_enveloped(zahtjev, certificate)

    assert xsd.validate(signed), xsd.error_log


def test_signature_matches_spec_profile(certificate: Certificate) -> None:
    zahtjev = build_evidentiraj_eracun_zahtjev(
        (EvidencijaERacun.from_eracuna(_eracun_builder().build()),),
        vrsta=VrstaERacuna.IZLAZNI,
        id_zahtjeva="test-request-2",
        datum_vrijeme_slanja=SLANJE,
    )
    signed = sign_xades_enveloped(zahtjev, certificate)

    references = signed.findall(f".//{{{DS_NS}}}SignedInfo/{{{DS_NS}}}Reference")
    assert len(references) == 2  # root + SignedProperties, per spec ch. 11
    transforms = [
        t.get("Algorithm")
        for t in references[0].findall(f"{{{DS_NS}}}Transforms/{{{DS_NS}}}Transform")
    ]
    assert transforms == [
        "http://www.w3.org/2000/09/xmldsig#enveloped-signature",
        "http://www.w3.org/2001/10/xml-exc-c14n#",
    ]
    assert references[1].get("Type") == "http://uri.etsi.org/01903#SignedProperties"

    signature_method = signed.find(f".//{{{DS_NS}}}SignatureMethod")
    assert signature_method is not None
    assert signature_method.get("Algorithm") == (
        "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
    )
    assert signed.find(f".//{{{DS_NS}}}KeyValue") is None
    assert signed.find(f".//{{{XADES_NS}}}SigningCertificateV2") is not None
    assert signed.find(f".//{{{XADES_NS}}}SigningTime") is not None


def test_verify_round_trip_and_tamper_detection(certificate: Certificate) -> None:
    zahtjev = build_evidentiraj_eracun_zahtjev(
        (EvidencijaERacun.from_eracuna(_eracun_builder().build()),),
        vrsta=VrstaERacuna.ULAZNI,
        id_zahtjeva="test-request-3",
        datum_vrijeme_slanja=SLANJE,
    )
    signed_bytes = etree.tostring(sign_xades_enveloped(zahtjev, certificate))

    verified = verify_xades_enveloped(signed_bytes, trust_embedded_certificate=True)
    assert verified == certificate.certificate

    tampered = signed_bytes.replace(b"2026-42-P1-1", b"2026-42-P1-2")
    with pytest.raises(SignatureVerificationError):
        verify_xades_enveloped(tampered, trust_embedded_certificate=True)


def test_verify_requires_a_trust_source(certificate: Certificate) -> None:
    zahtjev = build_evidentiraj_eracun_zahtjev(
        (EvidencijaERacun.from_eracuna(_eracun_builder().build()),),
        vrsta=VrstaERacuna.IZLAZNI,
        id_zahtjeva="test-request-4",
        datum_vrijeme_slanja=SLANJE,
    )
    signed = sign_xades_enveloped(zahtjev, certificate)
    with pytest.raises(SignatureVerificationError, match="no trusted certificate"):
        verify_xades_enveloped(signed)


def test_client_reports_eracun_end_to_end(certificate: Certificate) -> None:
    mock = MockEFiskalizacija()
    client = EFiskalizacijaClient(certificate, transport=mock.transport())

    odgovor = client.evidentiraj_izlazni(_eracun_builder().build())

    assert odgovor.prihvacen
    assert odgovor.greska is None
    [request] = mock.requests
    zaglavlje = request.find(
        "e:Zaglavlje/e:vrstaERacuna",
        namespaces={"e": "http://www.porezna-uprava.gov.hr/fin/2024/types/eFiskalizacija"},
    )
    assert zaglavlje is not None
    assert zaglavlje.text == "I"


def test_client_raises_cis_error_on_rejection(certificate: Certificate) -> None:
    mock = MockEFiskalizacija(force_greska="S008")
    client = EFiskalizacijaClient(certificate, transport=mock.transport())

    with pytest.raises(CisError) as excinfo:
        client.evidentiraj_ulazni(_eracun_builder().build())
    assert excinfo.value.code == "S008"
    assert "identifikatorom" in (excinfo.value.message_hr or "")


def test_client_rejects_unsigned_response(certificate: Certificate) -> None:
    mock = MockEFiskalizacija(sign_responses=False)
    client = EFiskalizacijaClient(certificate, transport=mock.transport())

    with pytest.raises(SignatureVerificationError):
        client.evidentiraj_izlazni(_eracun_builder().build())


def test_digest_with_popust_i_trosak_validates(
    xsd: etree.XMLSchema, certificate: Certificate
) -> None:
    racun = (
        _eracun_builder()
        .popust(iznos="10.00", razlog="Rabat", pdv_stopa=25)
        .trosak(iznos="5.00", razlog="Dostava", pdv_stopa=25)
        .build()
    )
    evidencija = EvidencijaERacun.from_eracuna(racun)
    assert evidencija.ukupan_iznos.popust == Decimal("10.00")
    assert evidencija.ukupan_iznos.trosak == Decimal("5.00")
    # lines 150; S25 base 100-10+5=95 -> 23.75 PDV; E base 50
    assert evidencija.ukupan_iznos.iznos_bez_pdv == Decimal("145.00")
    assert evidencija.ukupan_iznos.iznos_s_pdv == Decimal("168.75")

    zahtjev = build_evidentiraj_eracun_zahtjev(
        (evidencija,),
        vrsta=VrstaERacuna.IZLAZNI,
        id_zahtjeva="test-request-6",
        datum_vrijeme_slanja=SLANJE,
    )
    assert xsd.validate(sign_xades_enveloped(zahtjev, certificate)), xsd.error_log


def test_client_soap_fault_raises_transport_error(certificate: Certificate) -> None:
    mock = MockEFiskalizacija(soap_fault="planned outage")
    client = EFiskalizacijaClient(certificate, transport=mock.transport())

    with pytest.raises(TransportError, match="planned outage"):
        client.evidentiraj_izlazni(_eracun_builder().build())


def test_mock_responses_validate_against_official_xsd(
    xsd: etree.XMLSchema, certificate: Certificate
) -> None:
    mock = MockEFiskalizacija()
    zahtjev = build_evidentiraj_eracun_zahtjev(
        (EvidencijaERacun.from_eracuna(_eracun_builder().build()),),
        vrsta=VrstaERacuna.IZLAZNI,
        id_zahtjeva="test-request-5",
        datum_vrijeme_slanja=SLANJE,
    )
    signed = sign_xades_enveloped(zahtjev, certificate)
    request = httpx.Request("POST", "https://mock.invalid/", content=wrap_soap(signed))

    response = unwrap_soap(mock.handler(request).content)

    assert xsd.validate(response), xsd.error_log


def test_zahtjev_caps_at_100_records() -> None:
    with pytest.raises(ValueError, match="1-100"):
        build_evidentiraj_eracun_zahtjev(
            (),
            vrsta=VrstaERacuna.IZLAZNI,
            id_zahtjeva="x",
            datum_vrijeme_slanja=SLANJE,
        )
