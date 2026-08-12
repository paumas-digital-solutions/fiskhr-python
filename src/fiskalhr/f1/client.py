"""``FiskalizacijaClient`` — the public F1 surface.

Stateless: construct with a certificate and an environment; every method is
one request → response exchange. Retry queues, outboxes, and the 48-hour
late-submission workflow belong to the caller.

Every signed call follows the same flow: compute ZKI (offline) → build the
zahtjev → sign (XML-DSig) → send over SOAP → verify the response signature →
parse → return the parsed response or raise `CisError`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import httpx
from lxml import etree

from fiskalhr.core.certs import Certificate
from fiskalhr.core.environment import Environment
from fiskalhr.core.errors import CisError, FiskalizacijaError
from fiskalhr.core.signing import SignatureMethod
from fiskalhr.core.transport import SoapClient
from fiskalhr.core.xmldsig import sign_enveloped, verify_enveloped
from fiskalhr.f1.messages import (
    build_echo_request,
    build_napojnica_zahtjev,
    build_promijeni_nac_plac_zahtjev,
    build_promijeni_podatke_racuna_zahtjev,
    build_provjera_zahtjev,
    build_racun_zahtjev,
    parse_echo_response,
    parse_promjena_odgovor,
    parse_provjera_odgovor,
    parse_racun_odgovor,
)
from fiskalhr.f1.models import (
    Greska,
    NacinPlacanja,
    Napojnica,
    PromjenaOdgovor,
    ProvjeraOdgovor,
    Racun,
    RacunOdgovor,
)
from fiskalhr.f1.radno_vrijeme import (
    BrisanjeRadnogVremena,
    RadnoVrijeme,
    RadnoVrijemeOdgovor,
    VrstaRadnogVremena,
    build_dohvati_radno_vrijeme_zahtjev,
    build_obrisi_radno_vrijeme_zahtjev,
    build_prijavi_radno_vrijeme_zahtjev,
    parse_dohvati_radno_vrijeme_odgovor,
)
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

    def _send_signed(self, zahtjev: etree._Element, action: str) -> etree._Element:
        signed = sign_enveloped(zahtjev, self.certificate, method=self.signature_method)
        response = self._soap.call(
            etree.fromstring(signed), soap_action=f"{_SOAP_ACTION_BASE}/{action}"
        )
        if not self.allow_unverified_response:
            verify_enveloped(response, trust_embedded_certificate=True)
        return response

    def _zki_for(self, racun: Racun, zki: str | None) -> str:
        return zki if zki is not None else self.izracunaj_zki(racun)

    @staticmethod
    def _raise_on_greske(greske: tuple[Greska, ...]) -> None:
        if greske:
            first = greske[0]
            raise CisError(
                f"CIS rejected the message: {first.sifra} {first.poruka}",
                code=first.sifra,
                message_hr=first.poruka,
                greske=tuple((greska.sifra, greska.poruka) for greska in greske),
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
            self._zki_for(racun, zki),
            id_poruke=id_poruke,
            datum_vrijeme=datum_vrijeme,
        )
        odgovor = parse_racun_odgovor(self._send_signed(zahtjev, "racuni"))
        self._raise_on_greske(odgovor.greske)
        return odgovor

    def fiskaliziraj_napojnicu(
        self,
        racun: Racun,
        napojnica: Napojnica,
        *,
        zki: str | None = None,
        id_poruke: uuid.UUID | None = None,
        datum_vrijeme: datetime | None = None,
    ) -> PromjenaOdgovor:
        """Report a tip for an already-fiscalized receipt.

        ``racun`` must carry the original receipt's data unchanged, and
        ``zki`` the originally printed ZKI (recomputed if omitted). Pass
        ``datum_vrijeme`` as the report time when it differs from the
        receipt's issue time.

        Raises:
            CisError: On rejection (e.g. s009 date window, s010 mismatch).
        """
        zahtjev = build_napojnica_zahtjev(
            racun,
            self._zki_for(racun, zki),
            napojnica,
            id_poruke=id_poruke,
            datum_vrijeme=datum_vrijeme,
        )
        odgovor = parse_promjena_odgovor(
            self._send_signed(zahtjev, "napojnica"), expected="NapojnicaOdgovor"
        )
        self._raise_on_greske(odgovor.greske)
        return odgovor

    def promijeni_nacin_placanja(
        self,
        racun: Racun,
        promijenjeni_nacin_plac: NacinPlacanja,
        *,
        zki: str | None = None,
        id_poruke: uuid.UUID | None = None,
        datum_vrijeme: datetime | None = None,
    ) -> PromjenaOdgovor:
        """Change the payment method of a fiscalized receipt (same-day only).

        ``racun`` carries the original data including the *original*
        ``nacin_plac``; the new method is a separate argument.

        Raises:
            CisError: On rejection (e.g. s007 wrong date, s008 mismatch).
        """
        zahtjev = build_promijeni_nac_plac_zahtjev(
            racun,
            self._zki_for(racun, zki),
            promijenjeni_nacin_plac,
            id_poruke=id_poruke,
            datum_vrijeme=datum_vrijeme,
        )
        odgovor = parse_promjena_odgovor(
            self._send_signed(zahtjev, "promijeniNacPlac"), expected="PromijeniNacPlacOdgovor"
        )
        self._raise_on_greske(odgovor.greske)
        return odgovor

    def promijeni_podatke_racuna(
        self,
        racun: Racun,
        *,
        promijenjeni_nacin_plac: NacinPlacanja,
        promijenjeni_oib_primatelja_racuna: str,
        zki: str | None = None,
        id_poruke: uuid.UUID | None = None,
        datum_vrijeme: datetime | None = None,
    ) -> PromjenaOdgovor:
        """Change payment method and/or receiver OIB of a fiscalized receipt.

        Both change fields are mandatory in the schema; pass the unchanged
        value to keep it, or an empty string to clear the receiver OIB.

        Raises:
            CisError: On rejection (e.g. s011 wrong date, s012 mismatch).
        """
        zahtjev = build_promijeni_podatke_racuna_zahtjev(
            racun,
            self._zki_for(racun, zki),
            promijenjeni_nacin_plac,
            promijenjeni_oib_primatelja_racuna,
            id_poruke=id_poruke,
            datum_vrijeme=datum_vrijeme,
        )
        odgovor = parse_promjena_odgovor(
            self._send_signed(zahtjev, "promijeniPodatkeRacuna"),
            expected="PromijeniPodatkeRacunaOdgovor",
        )
        self._raise_on_greske(odgovor.greske)
        return odgovor

    def provjeri(
        self,
        racun: Racun,
        *,
        zki: str | None = None,
        id_poruke: uuid.UUID | None = None,
        datum_vrijeme: datetime | None = None,
    ) -> ProvjeraOdgovor:
        """Check a receipt without fiscalizing it. **Demo environment only.**

        Unlike the other methods, reported errors do NOT raise `CisError` —
        the error list is the whole point of the check, so the caller gets
        the full `ProvjeraOdgovor` either way.

        Raises:
            FiskalizacijaError: When called against production, which does
                not offer the ``provjera`` operation.
        """
        if self.env is not Environment.DEMO:
            raise FiskalizacijaError(
                "the provjera operation exists only in the demo environment "
                "(it is absent from the production WSDL)"
            )
        zahtjev = build_provjera_zahtjev(
            racun,
            self._zki_for(racun, zki),
            id_poruke=id_poruke,
            datum_vrijeme=datum_vrijeme,
        )
        return parse_provjera_odgovor(self._send_signed(zahtjev, "provjera"))

    def prijavi_radno_vrijeme(
        self,
        oib: str,
        ozn_pos_pr: str,
        radno_vrijeme: RadnoVrijeme,
        oib_oper: str,
        *,
        datum_vrijeme: datetime,
        id_poruke: uuid.UUID | None = None,
    ) -> PromjenaOdgovor:
        """Register working hours for a business premises (schema v1.10).

        No receipt and no ZKI are involved; the message is signed and sent.
        ``datum_vrijeme`` is the message timestamp (local Croatian time).
        """
        zahtjev = build_prijavi_radno_vrijeme_zahtjev(
            oib,
            ozn_pos_pr,
            radno_vrijeme,
            oib_oper,
            datum_vrijeme=datum_vrijeme,
            id_poruke=id_poruke,
        )
        odgovor = parse_promjena_odgovor(
            self._send_signed(zahtjev, "prijaviRadnoVrijeme"),
            expected="PrijaviRadnoVrijemeOdgovor",
        )
        self._raise_on_greske(odgovor.greske)
        return odgovor

    def obrisi_radno_vrijeme(
        self,
        oib: str,
        ozn_pos_pr: str,
        brisanje: BrisanjeRadnogVremena,
        oib_oper: str,
        *,
        datum_vrijeme: datetime,
        id_poruke: uuid.UUID | None = None,
    ) -> PromjenaOdgovor:
        """Delete registered working hours by their dates."""
        zahtjev = build_obrisi_radno_vrijeme_zahtjev(
            oib,
            ozn_pos_pr,
            brisanje,
            oib_oper,
            datum_vrijeme=datum_vrijeme,
            id_poruke=id_poruke,
        )
        odgovor = parse_promjena_odgovor(
            self._send_signed(zahtjev, "obrisiRadnoVrijeme"),
            expected="ObrisiRadnoVrijemeOdgovor",
        )
        self._raise_on_greske(odgovor.greske)
        return odgovor

    def dohvati_radno_vrijeme(
        self,
        oib: str,
        ozn_pos_pr: str,
        oib_oper: str,
        *,
        vrsta: VrstaRadnogVremena = VrstaRadnogVremena.SVE,
        datum_vrijeme: datetime,
        id_poruke: uuid.UUID | None = None,
    ) -> RadnoVrijemeOdgovor:
        """Fetch the currently registered working hours for a premises."""
        zahtjev = build_dohvati_radno_vrijeme_zahtjev(
            oib,
            ozn_pos_pr,
            vrsta,
            oib_oper,
            datum_vrijeme=datum_vrijeme,
            id_poruke=id_poruke,
        )
        odgovor = parse_dohvati_radno_vrijeme_odgovor(
            self._send_signed(zahtjev, "dohvatiRadnoVrijeme")
        )
        self._raise_on_greske(odgovor.greske)
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
