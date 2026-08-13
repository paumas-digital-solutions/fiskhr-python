"""``EFiskalizacijaClient`` — direct reporting to the eFiskalizacija service.

This is the *reporting* leg of Fiskalizacija 2.0: the taxpayer (or its
information intermediary) tells the Tax Administration about issued and
received eRačuni. Delivery of the eRačun to the buyer is a separate concern
(the ``Posrednik`` adapter boundary, Phase 4) — the Tax Administration's
service here can be called directly, no intermediary required.

Stateless, mirroring the F1 client: build → sign (XAdES-B) → send over
SOAP 1.1 → verify the response signature → parse → return or raise.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

import httpx

from fiskalhr.core.certs import Certificate
from fiskalhr.core.environment import Environment
from fiskalhr.core.errors import CisError
from fiskalhr.core.transport import SoapClient
from fiskalhr.core.xades import sign_xades_enveloped, verify_xades_enveloped
from fiskalhr.f2.fiskalizacija.messages import (
    build_evidentiraj_eracun_zahtjev,
    parse_evidentiraj_eracun_odgovor,
)
from fiskalhr.f2.fiskalizacija.models import (
    EvidencijaERacun,
    EvidencijaOdgovor,
    VrstaERacuna,
)
from fiskalhr.f2.service import SERVICE_URLS
from fiskalhr.f2.ubl.models import ERacun

__all__ = ["EFiskalizacijaClient"]


class EFiskalizacijaClient:
    """Client for the eFiskalizacija service (Fiskalizacija 2.0 reporting).

    Args:
        certificate: The taxpayer's application certificate (its DN must
            contain the OIB; demo certificate for `Environment.DEMO`).
        env: Target environment; selects the endpoint from
            `fiskalhr.f2.service.SERVICE_URLS`.
        timeout: Per-request timeout in seconds.
        retries: Extra attempts on connection errors/timeouts only; never
            after a response was received.
        allow_unverified_response: **Dangerous.** Skips response-signature
            verification when True. Exists only for debugging against the
            demo environment; never set it in production code.
        transport: Optional httpx transport, injectable for testing —
            `fiskalhr.testing.MockEFiskalizacija` plugs in here.
    """

    def __init__(
        self,
        certificate: Certificate,
        env: Environment = Environment.DEMO,
        *,
        timeout: float = 30.0,
        retries: int = 2,
        allow_unverified_response: bool = False,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.certificate = certificate
        self.env = env
        self.allow_unverified_response = allow_unverified_response
        self._soap = SoapClient(
            SERVICE_URLS[env], timeout=timeout, retries=retries, transport=transport
        )

    def evidentiraj_izlazni(self, *racuni: ERacun | EvidencijaERacun) -> EvidencijaOdgovor:
        """Report outgoing eRačuni (as their issuer)."""
        return self.evidentiraj(racuni, vrsta=VrstaERacuna.IZLAZNI)

    def evidentiraj_ulazni(self, *racuni: ERacun | EvidencijaERacun) -> EvidencijaOdgovor:
        """Report incoming eRačuni (as their recipient)."""
        return self.evidentiraj(racuni, vrsta=VrstaERacuna.ULAZNI)

    def evidentiraj(
        self,
        racuni: Sequence[ERacun | EvidencijaERacun],
        *,
        vrsta: VrstaERacuna,
    ) -> EvidencijaOdgovor:
        """Report 1-100 eRačuni in one ``EvidentirajERacun`` call.

        `fiskalhr.f2.ubl.ERacun` models are converted with
        `EvidencijaERacun.from_eracuna`; pre-built `EvidencijaERacun`
        digests pass through unchanged.

        Raises:
            CisError: The service rejected the request
                (``prihvacenZahtjev=false``); carries the ``S0xx`` code.
            TransportError: Network failure or SOAP fault.
            SignatureVerificationError: The response signature is missing
                or does not verify.
        """
        evidencije = tuple(
            r if isinstance(r, EvidencijaERacun) else EvidencijaERacun.from_eracuna(r)
            for r in racuni
        )
        zahtjev = build_evidentiraj_eracun_zahtjev(
            evidencije,
            vrsta=vrsta,
            id_zahtjeva=str(uuid.uuid4()),
            datum_vrijeme_slanja=datetime.now(),
        )
        signed = sign_xades_enveloped(zahtjev, self.certificate)
        response = self._soap.call(signed, soap_action="")
        if not self.allow_unverified_response:
            verify_xades_enveloped(response, trust_embedded_certificate=True)
        odgovor = parse_evidentiraj_eracun_odgovor(response)
        if not odgovor.prihvacen:
            greska = odgovor.greska
            if greska is not None:
                raise CisError(
                    f"eFiskalizacija rejected the request: {greska.sifra} {greska.opis} "
                    f"(zapis {greska.redni_broj_zapisa})",
                    code=greska.sifra,
                    message_hr=greska.opis,
                    greske=((greska.sifra, greska.opis),),
                )
            raise CisError("eFiskalizacija rejected the request without an error detail")
        return odgovor

    def close(self) -> None:
        self._soap.close()

    def __enter__(self) -> EFiskalizacijaClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
