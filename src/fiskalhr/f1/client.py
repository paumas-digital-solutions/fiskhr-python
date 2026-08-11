"""``FiskalizacijaClient`` — the public F1 surface.

Stateless: construct with a certificate and an environment; every method is
one request → response exchange. Retry queues, outboxes, and the 48-hour
late-submission workflow belong to the caller.

The fiscalization flow per call: compute ZKI (offline) → build
``RacunZahtjev`` → sign (XML-DSig) → send over SOAP → verify the response
signature → parse → return the JIR or raise `CisError`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import httpx
from lxml import etree

from fiskalhr.core.certs import Certificate
from fiskalhr.core.environment import Environment
from fiskalhr.core.errors import CisError
from fiskalhr.core.signing import SignatureMethod
from fiskalhr.core.transport import SoapClient
from fiskalhr.core.xmldsig import sign_enveloped, verify_enveloped
from fiskalhr.f1.messages import (
    build_echo_request,
    build_racun_zahtjev,
    parse_echo_response,
    parse_racun_odgovor,
)
from fiskalhr.f1.models import Racun, RacunOdgovor
from fiskalhr.f1.service import SERVICE_URLS
from fiskalhr.f1.zki import izracunaj_zki

__all__ = ["FiskalizacijaClient"]

_SOAP_ACTION_BASE = (
    "http://e-porezna.porezna-uprava.hr/fiskalizacija/2012/services/FiskalizacijaService"
)


class FiskalizacijaClient:
    """Client for the CIS fiscalization service (Fiskalizacija 1.0).

    Args:
        certificate: The taxpayer's FISKAL certificate (demo certificate for
            `Environment.DEMO`).
        env: Target environment; selects the endpoint from
            `fiskalhr.f1.service.SERVICE_URLS`.
        signature_method: RSA-SHA256 by default. RSA-SHA1 exists only for
            the production transition period (until end of 2026) and is
            rejected by the demo environment.
        timeout: Per-request timeout in seconds.
        retries: Extra attempts on connection errors/timeouts only; never
            after a response was received.
        allow_unverified_response: **Dangerous.** Skips response-signature
            verification when True. Exists only for debugging against the
            demo environment; never set it in production code.
        transport: Optional httpx transport, injectable for testing —
            `fiskalhr.testing.MockCis` plugs in here.

    Response signatures are verified against the certificate embedded in the
    response by default, which proves integrity. Pinning the expected CIS
    certificate (``fiskalcis`` / ``fiskalcistest``) can be layered on by the
    caller via `fiskalhr.core.xmldsig.verify_enveloped` until certificate
    pinning ships as a first-class option.
    """

    def __init__(
        self,
        certificate: Certificate,
        env: Environment = Environment.DEMO,
        *,
        signature_method: SignatureMethod = SignatureMethod.RSA_SHA256,
        timeout: float = 30.0,
        retries: int = 2,
        allow_unverified_response: bool = False,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.certificate = certificate
        self.env = env
        self.signature_method = signature_method
        self.allow_unverified_response = allow_unverified_response
        self._soap = SoapClient(
            SERVICE_URLS[env], timeout=timeout, retries=retries, transport=transport
        )

    def izracunaj_zki(self, racun: Racun) -> str:
        """Compute the ZKI for a receipt. Fully offline — usable before
        sending, and required on the printed receipt even when CIS is down.
        """
        return izracunaj_zki(
            self.certificate.private_key,
            oib=racun.oib,
            datum_vrijeme=racun.dat_vrijeme,
            br_ozn_rac=racun.br_rac.br_ozn_rac,
            ozn_pos_pr=racun.br_rac.ozn_pos_pr,
            ozn_nap_ur=racun.br_rac.ozn_nap_ur,
            ukupan_iznos=racun.iznos_ukupno,
            method=self.signature_method,
        )

    def fiskaliziraj(
        self,
        racun: Racun,
        *,
        zki: str | None = None,
        id_poruke: uuid.UUID | None = None,
        datum_vrijeme: datetime | None = None,
    ) -> RacunOdgovor:
        """Fiscalize a receipt and return the response carrying the JIR.

        Args:
            racun: The receipt.
            zki: The ZKI already printed on the receipt. Computed on the fly
                when omitted — pass it explicitly for late submission so the
                sent value is byte-identical to the printed one.
            id_poruke: Message UUID; generated when omitted.
            datum_vrijeme: Message timestamp for late submission
                (``NakDost``); defaults to the receipt's issue time.

        Raises:
            CisError: The service processed the message and reported errors
                (no JIR was assigned).
            TransportError: The service could not be reached; the receipt is
                issued without a JIR and the message must be resubmitted.
            SignatureVerificationError: The response signature failed —
                never treat this as a transport hiccup.
        """
        zahtjev = build_racun_zahtjev(
            racun,
            zki if zki is not None else self.izracunaj_zki(racun),
            id_poruke=id_poruke,
            datum_vrijeme=datum_vrijeme,
        )
        signed = sign_enveloped(zahtjev, self.certificate, method=self.signature_method)
        response = self._soap.call(
            etree.fromstring(signed), soap_action=f"{_SOAP_ACTION_BASE}/racuni"
        )

        if not self.allow_unverified_response:
            verify_enveloped(response, trust_embedded_certificate=True)

        odgovor = parse_racun_odgovor(response)
        if odgovor.greske:
            first = odgovor.greske[0]
            raise CisError(
                f"CIS rejected the message: {first.sifra} {first.poruka}",
                code=first.sifra,
                message_hr=first.poruka,
                greske=tuple((greska.sifra, greska.poruka) for greska in odgovor.greske),
            )
        return odgovor

    def echo(self, text: str = "ping") -> str:
        """Call the ``echo`` connectivity-test method and return the reply."""
        response = self._soap.call(
            build_echo_request(text), soap_action=f"{_SOAP_ACTION_BASE}/echo"
        )
        return parse_echo_response(response)

    def close(self) -> None:
        self._soap.close()

    def __enter__(self) -> FiskalizacijaClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
