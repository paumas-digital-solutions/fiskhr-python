"""`MockEIzvjestavanje` — an in-process eIzvještavanje service double.

The F2 counterpart mock for payment/rejection reporting: XSD-validates each
request against the vendored official schema, verifies its XAdES-B
signature, and answers with a signed response — so an
`EIzvjestavanjeClient` exercises its whole pipeline offline.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import httpx
from cryptography import x509
from lxml import etree

from fiskalhr.core.errors import SignatureVerificationError
from fiskalhr.core.transport import SOAP_ENV_NS, unwrap_soap, wrap_soap
from fiskalhr.core.xades import sign_xades_enveloped, verify_xades_enveloped
from fiskalhr.f2.fiskalizacija.messages import format_datum_vrijeme
from fiskalhr.f2.izvjestavanje.messages import EIZVJ_NS
from fiskalhr.f2.service import eizvjestavanje_schema_path
from fiskalhr.testing.mock_cis import _make_service_certificate

__all__ = ["MockEIzvjestavanje"]

_ERROR_MESSAGES = {
    "S004": "Neispravan potpis zahtjeva",
    "S005": "Poruka nije u skladu s XML shemom",
}

_RESPONSE_ROOTS = {
    "EvidentirajNaplatuZahtjev": "EvidentirajNaplatuOdgovor",
    "EvidentirajOdbijanjeZahtjev": "EvidentirajOdbijanjeOdgovor",
    "EvidentirajIsporukuZaKojuNijeIzdanERacunZahtjev": (
        "EvidentirajIsporukuZaKojuNijeIzdanERacunOdgovor"
    ),
}


class MockEIzvjestavanje:
    """In-process eIzvještavanje double for testing F2 payment reporting.

    Args:
        force_greska: When set, every evidencija request is rejected with
            this error code, attributed to record 1.
        soap_fault: When set, every call answers HTTP 500 with a SOAP fault.
        sign_responses: Sign responses with the mock's throwaway service
            certificate (default); turn off to test client refusal.
        ovlasteni_oibi: What ``OvlastenjaFiskalizacije`` answers; defaults
            to echoing the OIB from the request.

    Attributes:
        service_certificate: The throwaway certificate responses are signed
            with.
        requests: Every payload element received, in order.
    """

    def __init__(
        self,
        *,
        force_greska: str | None = None,
        soap_fault: str | None = None,
        sign_responses: bool = True,
        ovlasteni_oibi: tuple[str, ...] | None = None,
    ) -> None:
        self.force_greska = force_greska
        self.soap_fault = soap_fault
        self.sign_responses = sign_responses
        self.ovlasteni_oibi = ovlasteni_oibi
        self._service_cert = _make_service_certificate()
        self._xsd = etree.XMLSchema(etree.parse(eizvjestavanje_schema_path()))
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
        greska = self._check(payload)
        if tag == "OvlastenjaFiskalizacijeZahtjev":
            return httpx.Response(200, content=wrap_soap(self._ovlastenja_odgovor(payload)))
        if tag in _RESPONSE_ROOTS:
            if greska is None and self.force_greska is not None:
                greska = (
                    self.force_greska,
                    _ERROR_MESSAGES.get(self.force_greska, "greška"),
                )
            return httpx.Response(
                200, content=wrap_soap(self._odgovor(_RESPONSE_ROOTS[tag], greska))
            )
        return self._fault(f"unsupported request {tag!r}")

    def _check(self, payload: etree._Element) -> tuple[str, str] | None:
        if not self._xsd.validate(payload):
            return ("S005", f"Poruka nije u skladu s XML shemom: {self._xsd.error_log}")
        try:
            verify_xades_enveloped(payload, trust_embedded_certificate=True)
        except SignatureVerificationError:
            return ("S004", _ERROR_MESSAGES["S004"])
        return None

    def _odgovor(self, name: str, greska: tuple[str, str] | None) -> etree._Element:
        root = etree.Element(f"{{{EIZVJ_NS}}}{name}", nsmap={"eizv": EIZVJ_NS})
        root.set(f"{{{EIZVJ_NS}}}id", str(uuid.uuid4()))
        vrijeme = etree.SubElement(root, f"{{{EIZVJ_NS}}}datumVrijemeSlanja")
        vrijeme.text = format_datum_vrijeme(datetime.now())
        odgovor = etree.SubElement(root, f"{{{EIZVJ_NS}}}Odgovor")
        etree.SubElement(odgovor, f"{{{EIZVJ_NS}}}idZahtjeva").text = str(uuid.uuid4())
        etree.SubElement(odgovor, f"{{{EIZVJ_NS}}}prihvacenZahtjev").text = (
            "false" if greska is not None else "true"
        )
        if greska is not None:
            greska_el = etree.SubElement(odgovor, f"{{{EIZVJ_NS}}}greska")
            etree.SubElement(greska_el, f"{{{EIZVJ_NS}}}sifra").text = greska[0]
            etree.SubElement(greska_el, f"{{{EIZVJ_NS}}}redniBrojZapisa").text = "1"
            etree.SubElement(greska_el, f"{{{EIZVJ_NS}}}opis").text = greska[1] or "greška"
        if self.sign_responses:
            root = sign_xades_enveloped(root, self._service_cert)
        return root

    def _ovlastenja_odgovor(self, payload: etree._Element) -> etree._Element:
        root = etree.Element(
            f"{{{EIZVJ_NS}}}OvlastenjaFiskalizacijeOdgovor", nsmap={"eizv": EIZVJ_NS}
        )
        root.set(f"{{{EIZVJ_NS}}}id", str(uuid.uuid4()))
        vrijeme = etree.SubElement(root, f"{{{EIZVJ_NS}}}datumVrijemeSlanja")
        vrijeme.text = format_datum_vrijeme(datetime.now())
        oibi = self.ovlasteni_oibi
        if oibi is None:
            requested = payload.find(f"{{{EIZVJ_NS}}}oib")
            oibi = (requested.text,) if requested is not None and requested.text else ()
        for oib in oibi:
            etree.SubElement(root, f"{{{EIZVJ_NS}}}ovlasteniOib").text = oib
        if self.sign_responses:
            root = sign_xades_enveloped(root, self._service_cert)
        return root

    def _fault(self, fault_string: str) -> httpx.Response:
        envelope = etree.Element(f"{{{SOAP_ENV_NS}}}Envelope", nsmap={"soapenv": SOAP_ENV_NS})
        body = etree.SubElement(envelope, f"{{{SOAP_ENV_NS}}}Body")
        fault = etree.SubElement(body, f"{{{SOAP_ENV_NS}}}Fault")
        etree.SubElement(fault, "faultcode").text = "soapenv:Client"
        etree.SubElement(fault, "faultstring").text = fault_string
        return httpx.Response(500, content=etree.tostring(envelope))
