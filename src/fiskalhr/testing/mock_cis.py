"""An in-process mock of the CIS fiscalization service.

Behaves like the real thing where it matters for integration testing:

- validates incoming ``RacunZahtjev`` documents against the vendored
  official XSD;
- verifies the request's XML-DSig signature (embedded certificate);
- **signs its responses** with a throwaway self-signed certificate generated
  at construction time, so client-side response-signature verification is
  genuinely exercised;
- answers ``echo`` like the real service;
- can be told to fail: reject with specific ``s0xx`` codes or return a SOAP
  fault.

Plug it into a client via httpx's transport injection:

    mock = MockCis()
    client = FiskalizacijaClient(cert, transport=httpx.MockTransport(mock.handler))
    odgovor = client.fiskaliziraj(racun)   # never leaves the process

No network, no FINA certificate, no demo environment.
"""

from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from lxml import etree

from fiskalhr.core.certs import Certificate
from fiskalhr.core.errors import SignatureVerificationError
from fiskalhr.core.transport import SOAP_ENV_NS, unwrap_soap, wrap_soap
from fiskalhr.core.xmldsig import sign_enveloped, verify_enveloped
from fiskalhr.f1.error_codes import CIS_ERROR_MESSAGES
from fiskalhr.f1.messages import F73_NS
from fiskalhr.f1.service import schema_dir

__all__ = ["MockCis"]

_DATUM_VRIJEME_FORMAT = "%d.%m.%YT%H:%M:%S"

_RESPONSE_ROOTS = {
    "RacunZahtjev": "RacunOdgovor",
    "ProvjeraZahtjev": "ProvjeraOdgovor",
    "NapojnicaZahtjev": "NapojnicaOdgovor",
    "PromijeniNacPlacZahtjev": "PromijeniNacPlacOdgovor",
    "PromijeniPodatkeRacunaZahtjev": "PromijeniPodatkeRacunaOdgovor",
    "PrijaviRadnoVrijemeZahtjev": "PrijaviRadnoVrijemeOdgovor",
    "ObrisiRadnoVrijemeZahtjev": "ObrisiRadnoVrijemeOdgovor",
    "DohvatiRadnoVrijemeZahtjev": "DohvatiRadnoVrijemeOdgovor",
}


def _make_service_certificate() -> Certificate:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "fiskalcistest-mock"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "fiskalhr MockCis"),
            x509.NameAttribute(NameOID.COUNTRY_NAME, "HR"),
        ]
    )
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    return Certificate(private_key=key, certificate=certificate)


class MockCis:
    """In-process CIS double for testing F1 integrations.

    Args:
        force_greske: When set, every ``RacunZahtjev`` is rejected with
            these error codes (messages from the spec's error table).
        soap_fault: When set, every call answers HTTP 500 with a SOAP fault
            carrying this fault string.
        sign_responses: Sign responses with the mock's throwaway service
            certificate (default). Turn off to simulate a tampering
            man-in-the-middle and assert your client refuses the response.

    Attributes:
        service_certificate: The throwaway certificate responses are signed
            with (a stand-in for ``fiskalcistest``).
        requests: Every payload element received, in order — assert on it to
            check what your integration actually sent.
    """

    def __init__(
        self,
        *,
        force_greske: tuple[str, ...] = (),
        soap_fault: str | None = None,
        sign_responses: bool = True,
    ) -> None:
        self.force_greske = force_greske
        self.soap_fault = soap_fault
        self.sign_responses = sign_responses
        self._service_cert = _make_service_certificate()
        self._xsd = etree.XMLSchema(etree.parse(schema_dir() / "FiskalizacijaSchema.xsd"))
        self.requests: list[etree._Element] = []

    @property
    def service_certificate(self) -> x509.Certificate:
        return self._service_cert.certificate

    def transport(self) -> httpx.MockTransport:
        """An httpx transport routing all requests to this mock."""
        return httpx.MockTransport(self.handler)

    def handler(self, request: httpx.Request) -> httpx.Response:
        """httpx request handler — the mock's single entry point."""
        if self.soap_fault is not None:
            return self._fault(self.soap_fault)

        try:
            payload = unwrap_soap(request.content)
        except Exception as exc:
            return self._fault(f"invalid SOAP request: {exc}")
        self.requests.append(payload)

        tag = etree.QName(payload).localname
        if tag == "EchoRequest":
            return self._echo(payload)
        if tag in _RESPONSE_ROOTS:
            return self._zahtjev(tag, payload)
        return self._fault(f"unsupported request {tag!r}")

    def _echo(self, payload: etree._Element) -> httpx.Response:
        response = etree.Element(f"{{{F73_NS}}}EchoResponse", nsmap={"tns": F73_NS})
        response.text = payload.text or ""
        return httpx.Response(200, content=wrap_soap(response))

    def _zahtjev(self, tag: str, payload: etree._Element) -> httpx.Response:
        greske: list[tuple[str, str]] = []

        if not self._xsd.validate(payload):
            greske.append(("s001", f"Poruka nije u skladu s XML shemom: {self._xsd.error_log}"))
        else:
            try:
                verify_enveloped(payload, trust_embedded_certificate=True)
            except SignatureVerificationError:
                greske.append(("s004", CIS_ERROR_MESSAGES["s004"]))

        for sifra in self.force_greske:
            greske.append((sifra, CIS_ERROR_MESSAGES.get(sifra, "")))

        return httpx.Response(200, content=wrap_soap(self._odgovor(tag, payload, greske)))

    def _odgovor(
        self, tag: str, payload: etree._Element, greske: list[tuple[str, str]]
    ) -> etree._Element:
        response_name = _RESPONSE_ROOTS[tag]
        root = etree.Element(
            f"{{{F73_NS}}}{response_name}", attrib={"Id": response_name}, nsmap={"tns": F73_NS}
        )
        zaglavlje = etree.SubElement(root, f"{{{F73_NS}}}Zaglavlje")
        etree.SubElement(zaglavlje, f"{{{F73_NS}}}IdPoruke").text = (
            payload.findtext(f"{{{F73_NS}}}Zaglavlje/{{{F73_NS}}}IdPoruke") or ""
        )
        etree.SubElement(zaglavlje, f"{{{F73_NS}}}DatumVrijeme").text = datetime.now(
            tz=None
        ).strftime(_DATUM_VRIJEME_FORMAT)

        if tag == "ProvjeraZahtjev":
            # ProvjeraOdgovor must echo the received Racun (minOccurs=1).
            racun = payload.find(f"{{{F73_NS}}}Racun")
            if racun is not None:
                root.append(copy.deepcopy(racun))
            self._append_greske(root, greske)
        elif tag == "DohvatiRadnoVrijemeZahtjev":
            # PoslovniProstor is mandatory in the response even on errors.
            prostor = etree.SubElement(root, f"{{{F73_NS}}}PoslovniProstor")
            etree.SubElement(prostor, f"{{{F73_NS}}}Oib").text = (
                payload.findtext(f"{{{F73_NS}}}Oib") or ""
            )
            etree.SubElement(prostor, f"{{{F73_NS}}}OznPosPr").text = (
                payload.findtext(f"{{{F73_NS}}}OznPosPr") or ""
            )
            rv = etree.SubElement(prostor, f"{{{F73_NS}}}RadnoVrijeme")
            if not greske:
                redovno = etree.SubElement(rv, f"{{{F73_NS}}}Redovno")
                etree.SubElement(redovno, f"{{{F73_NS}}}DatumOd").text = "01.01.2026"
                po_dogovoru = etree.SubElement(redovno, f"{{{F73_NS}}}PoDogovoru")
                etree.SubElement(po_dogovoru, f"{{{F73_NS}}}RedovnoPoDogovoru").text = "DA"
            self._append_greske(root, greske)
        elif greske:
            self._append_greske(root, greske)
        elif tag == "RacunZahtjev":
            etree.SubElement(root, f"{{{F73_NS}}}Jir").text = str(uuid.uuid4())
        else:
            # Success message; p005 is the spec's code for receipt-data
            # change, the rest use a generic mock code.
            sifra = "p005" if tag == "PromijeniPodatkeRacunaZahtjev" else "p001"
            poruka_el = etree.SubElement(root, f"{{{F73_NS}}}PorukaOdgovora")
            etree.SubElement(poruka_el, f"{{{F73_NS}}}SifraPoruke").text = sifra
            etree.SubElement(poruka_el, f"{{{F73_NS}}}Poruka").text = "Uspješno zaprimljeno."

        if self.sign_responses:
            return etree.fromstring(sign_enveloped(root, self._service_cert))
        return root

    @staticmethod
    def _append_greske(root: etree._Element, greske: list[tuple[str, str]]) -> None:
        if not greske:
            return
        greske_el = etree.SubElement(root, f"{{{F73_NS}}}Greske")
        for sifra, poruka in greske:
            greska_el = etree.SubElement(greske_el, f"{{{F73_NS}}}Greska")
            etree.SubElement(greska_el, f"{{{F73_NS}}}SifraGreske").text = sifra
            etree.SubElement(greska_el, f"{{{F73_NS}}}PorukaGreske").text = poruka

    def _fault(self, fault_string: str) -> httpx.Response:
        envelope = etree.Element(f"{{{SOAP_ENV_NS}}}Envelope", nsmap={"soapenv": SOAP_ENV_NS})
        body = etree.SubElement(envelope, f"{{{SOAP_ENV_NS}}}Body")
        fault = etree.SubElement(body, f"{{{SOAP_ENV_NS}}}Fault")
        etree.SubElement(fault, "faultcode").text = "soapenv:Client"
        etree.SubElement(fault, "faultstring").text = fault_string
        return httpx.Response(500, content=etree.tostring(envelope))
