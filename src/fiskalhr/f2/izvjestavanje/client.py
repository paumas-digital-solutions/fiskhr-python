"""``EIzvjestavanjeClient`` — payment/rejection reporting (eIzvještavanje).

The second F2 reporting service: after an eRačun is fiscalized, the issuer
reports collections (``EvidentirajNaplatu``) and the recipient may report
rejections (``EvidentirajOdbijanje``). ``OvlastenjaFiskalizacije`` answers
which OIBs the calling taxpayer is authorised to report for.

Same flow and endpoint as `fiskalhr.f2.fiskalizacija.EFiskalizacijaClient`:
build → sign (XAdES-B) → SOAP 1.1 → verify response signature → parse.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import httpx
from lxml import etree

from fiskalhr.core.certs import Certificate
from fiskalhr.core.environment import Environment
from fiskalhr.core.errors import CisError
from fiskalhr.core.transport import SoapClient
from fiskalhr.core.xades import sign_xades_enveloped, verify_xades_enveloped
from fiskalhr.f2.fiskalizacija.models import EvidencijaOdgovor
from fiskalhr.f2.izvjestavanje.messages import (
    build_evidentiraj_naplatu_zahtjev,
    build_evidentiraj_odbijanje_zahtjev,
    build_ovlastenja_zahtjev,
    parse_izvjestavanje_odgovor,
    parse_ovlastenja_odgovor,
)
from fiskalhr.f2.izvjestavanje.models import Naplata, Odbijanje
from fiskalhr.f2.service import SERVICE_URLS

__all__ = ["EIzvjestavanjeClient"]


class EIzvjestavanjeClient:
    """Client for the eIzvještavanje service (payments and rejections).

    Args:
        certificate: The taxpayer's application certificate.
        env: Target environment; the endpoint is shared with eFiskalizacija
            (`fiskalhr.f2.service.SERVICE_URLS`).
        timeout: Per-request timeout in seconds.
        retries: Extra attempts on connection errors/timeouts only.
        allow_unverified_response: **Dangerous.** Skips response-signature
            verification when True; debugging only.
        transport: Optional httpx transport, injectable for testing —
            `fiskalhr.testing.MockEIzvjestavanje` plugs in here.
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

    def evidentiraj_naplatu(self, *naplate: Naplata) -> EvidencijaOdgovor:
        """Report 1-100 payments; issuer side.

        Raises `CisError` on rejection (``S0xx`` code attached).
        """
        zahtjev = build_evidentiraj_naplatu_zahtjev(
            naplate,
            id_zahtjeva=str(uuid.uuid4()),
            datum_vrijeme_slanja=datetime.now(),
        )
        return self._send(zahtjev)

    def evidentiraj_odbijanje(self, *odbijanja: Odbijanje) -> EvidencijaOdgovor:
        """Report 1-100 rejections; recipient side.

        Raises `CisError` on rejection (``S0xx`` code attached).
        """
        zahtjev = build_evidentiraj_odbijanje_zahtjev(
            odbijanja,
            id_zahtjeva=str(uuid.uuid4()),
            datum_vrijeme_slanja=datetime.now(),
        )
        return self._send(zahtjev)

    def ovlastenja(self, oib: str) -> tuple[str, ...]:
        """The OIBs this taxpayer is authorised to report for."""
        zahtjev = build_ovlastenja_zahtjev(
            oib,
            id_zahtjeva=str(uuid.uuid4()),
            datum_vrijeme_slanja=datetime.now(),
        )
        response = self._call(zahtjev)
        return parse_ovlastenja_odgovor(response)

    def _call(self, zahtjev: etree._Element) -> etree._Element:
        signed = sign_xades_enveloped(zahtjev, self.certificate)
        response = self._soap.call(signed, soap_action="")
        if not self.allow_unverified_response:
            verify_xades_enveloped(response, trust_embedded_certificate=True)
        return response

    def _send(self, zahtjev: etree._Element) -> EvidencijaOdgovor:
        odgovor = parse_izvjestavanje_odgovor(self._call(zahtjev))
        if not odgovor.prihvacen:
            greska = odgovor.greska
            if greska is not None:
                raise CisError(
                    f"eIzvjestavanje rejected the request: {greska.sifra} {greska.opis} "
                    f"(zapis {greska.redni_broj_zapisa})",
                    code=greska.sifra,
                    message_hr=greska.opis,
                    greske=((greska.sifra, greska.opis),),
                )
            raise CisError("eIzvjestavanje rejected the request without an error detail")
        return odgovor

    def close(self) -> None:
        self._soap.close()

    def __enter__(self) -> EIzvjestavanjeClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
