"""`MockEFiskalizacija` — an in-process eFiskalizacija service double.

Behaves like the F2 reporting service for testing purposes: it validates
each ``EvidentirajERacunZahtjev`` against the vendored official XSD,
verifies its XAdES-B signature, and answers with a signed
``EvidentirajERacunOdgovor``, so an `EFiskalizacijaClient` exercises its
entire pipeline — build, sign, send, verify, parse — without the demo
environment or a real application certificate.

Usage::

    mock = MockEFiskalizacija()
    client = EFiskalizacijaClient(cert, transport=mock.transport())
    odgovor = client.evidentiraj_izlazni(eracun)   # never leaves the process
"""

from __future__ import annotations

import uuid
from datetime import datetime

import httpx
from cryptography import x509
from lxml import etree

from fiskhr.core.errors import SignatureVerificationError
from fiskhr.core.transport import SOAP_ENV_NS, unwrap_soap, wrap_soap
from fiskhr.core.xades import sign_xades_enveloped, verify_xades_enveloped
from fiskhr.f2.fiskalizacija.error_codes import EFISKALIZACIJA_ERROR_MESSAGES
from fiskhr.f2.fiskalizacija.messages import EFISK_NS, format_datum_vrijeme
from fiskhr.f2.service import efiskalizacija_schema_path
from fiskhr.testing.mock_cis import _make_service_certificate

__all__ = ["MockEFiskalizacija"]


class MockEFiskalizacija:
    """In-process eFiskalizacija double for testing F2 reporting.

    Args:
        force_greska: When set, every request is rejected with this error
            code (``S001``-``S012``; description from the spec's table),
            attributed to record 1.
        soap_fault: When set, every call answers HTTP 500 with a SOAP fault
            carrying this fault string.
        sign_responses: Sign responses with the mock's throwaway service
            certificate (default). Turn off to simulate a tampering
            man-in-the-middle and assert your client refuses the response.

    Attributes:
        service_certificate: The throwaway certificate responses are signed
            with (a stand-in for ``fiskalcistest``).
        requests: Every payload element received, in order.
    """

    def __init__(
        self,
        *,
        force_greska: str | None = None,
        soap_fault: str | None = None,
        sign_responses: bool = True,
    ) -> None:
        self.force_greska = force_greska
        self.soap_fault = soap_fault
        self.sign_responses = sign_responses
        self._service_cert = _make_service_certificate()
        self._xsd = etree.XMLSchema(etree.parse(efiskalizacija_schema_path()))
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

        if payload.tag != f"{{{EFISK_NS}}}EvidentirajERacunZahtjev":
            return self._fault(f"unsupported request {payload.tag!r}")

        greska: tuple[str, str] | None = None
        if not self._xsd.validate(payload):
            greska = ("S005", f"Poruka nije u skladu s XML shemom: {self._xsd.error_log}")
        else:
            try:
                verify_xades_enveloped(payload, trust_embedded_certificate=True)
            except SignatureVerificationError:
                greska = ("S004", EFISKALIZACIJA_ERROR_MESSAGES["S004"])
        if greska is None and self.force_greska is not None:
            greska = (
                self.force_greska,
                EFISKALIZACIJA_ERROR_MESSAGES.get(self.force_greska, ""),
            )

        return httpx.Response(200, content=wrap_soap(self._odgovor(greska)))

    def _odgovor(self, greska: tuple[str, str] | None) -> etree._Element:
        root = etree.Element(f"{{{EFISK_NS}}}EvidentirajERacunOdgovor", nsmap={"efis": EFISK_NS})
        root.set(f"{{{EFISK_NS}}}id", str(uuid.uuid4()))
        vrijeme = etree.SubElement(root, f"{{{EFISK_NS}}}datumVrijemeSlanja")
        vrijeme.text = format_datum_vrijeme(datetime.now())
        odgovor = etree.SubElement(root, f"{{{EFISK_NS}}}Odgovor")
        id_zahtjeva = etree.SubElement(odgovor, f"{{{EFISK_NS}}}idZahtjeva")
        id_zahtjeva.text = str(uuid.uuid4())
        prihvacen = etree.SubElement(odgovor, f"{{{EFISK_NS}}}prihvacenZahtjev")
        prihvacen.text = "false" if greska is not None else "true"
        if greska is not None:
            greska_el = etree.SubElement(odgovor, f"{{{EFISK_NS}}}greska")
            sifra = etree.SubElement(greska_el, f"{{{EFISK_NS}}}sifra")
            sifra.text = greska[0]
            redni = etree.SubElement(greska_el, f"{{{EFISK_NS}}}redniBrojZapisa")
            redni.text = "1"
            opis = etree.SubElement(greska_el, f"{{{EFISK_NS}}}opis")
            opis.text = greska[1] or "greška"
        if self.sign_responses:
            root = sign_xades_enveloped(root, self._service_cert)
        return root

    def _fault(self, fault_string: str) -> httpx.Response:
        envelope = etree.Element(f"{{{SOAP_ENV_NS}}}Envelope", nsmap={"soapenv": SOAP_ENV_NS})
        body = etree.SubElement(envelope, f"{{{SOAP_ENV_NS}}}Body")
        fault = etree.SubElement(body, f"{{{SOAP_ENV_NS}}}Fault")
        code = etree.SubElement(fault, "faultcode")
        code.text = "soapenv:Client"
        string = etree.SubElement(fault, "faultstring")
        string.text = fault_string
        return httpx.Response(500, content=etree.tostring(envelope))
