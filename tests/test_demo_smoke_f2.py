"""F2 smoke tests against the real demo environment. Manual only.

Never run in CI (no secrets there, ever). Same configuration as the F1
smoke tests (`tests/test_demo_smoke.py`):

    export FISKHR_DEMO_P12=/path/to/fiskalDemo.p12
    export FISKHR_DEMO_P12_PASSWORD=...
    export FISKHR_DEMO_OIB=...        # the OIB the demo cert is issued to
    make smoke-test

These prove the XAdES-B signature profile and the message format against
the real eFiskalizacija / eIzvještavanje services — the F2 counterpart of
the "JIR from demo" milestone. Note the F2 demo endpoint
(``cistest.apis-it.hr:8509``) requires an application certificate whose DN
carries the OIB; the service rejects others with S003/S006.
"""

from __future__ import annotations

import os
from datetime import date, datetime
from decimal import Decimal

import pytest

from fiskhr.core.certs import Certificate
from fiskhr.core.environment import Environment
from fiskhr.f2.fiskalizacija import EFiskalizacijaClient
from fiskhr.f2.izvjestavanje import EIzvjestavanjeClient, Naplata
from fiskhr.f2.ubl import ERacun, ERacunBuilder

pytestmark = pytest.mark.demo

_P12_VAR = "FISKHR_DEMO_P12"
_PASSWORD_VAR = "FISKHR_DEMO_P12_PASSWORD"
_OIB_VAR = "FISKHR_DEMO_OIB"


@pytest.fixture(scope="module")
def certificate() -> Certificate:
    missing = [var for var in (_P12_VAR, _PASSWORD_VAR, _OIB_VAR) if not os.environ.get(var)]
    if missing:
        pytest.skip(f"demo environment not configured: set {', '.join(missing)}")
    return Certificate.from_p12(os.environ[_P12_VAR], os.environ[_PASSWORD_VAR])


@pytest.fixture
def eracun() -> ERacun:
    oib = os.environ[_OIB_VAR]
    # Unique document number per run — the service deduplicates on
    # (number, issue date, issuer OIB) and answers S008 for repeats.
    broj = f"SMOKE-{datetime.now():%Y%m%d%H%M%S}-P1-1"
    return (
        ERacunBuilder()
        .izdavatelj(
            oib=oib,
            naziv="fiskhr smoke test d.o.o.",
            ulica="Ulica 1",
            grad="Zagreb",
            postanski_broj="10000",
        )
        # The spec's own example reports the same OIB on both sides.
        .primatelj(
            oib=oib,
            naziv="fiskhr smoke test d.o.o.",
            ulica="Ulica 1",
            grad="Zagreb",
            postanski_broj="10000",
        )
        .operater(oib=oib, oznaka="Smoke1")
        .broj(broj)
        .datum_izdavanja(date.today(), datetime.now().time().replace(microsecond=0))
        .dospijece(date.today())
        .stavka(naziv="Smoke test", kpd="62.20.20", kolicina=1, cijena="1.00", pdv_stopa=25)
        .build()
    )


def test_evidentiraj_izlazni(certificate: Certificate, eracun: ERacun) -> None:
    client = EFiskalizacijaClient(certificate, env=Environment.DEMO)

    odgovor = client.evidentiraj_izlazni(eracun)

    assert odgovor.prihvacen
    print(f"\neFiskalizacija demo accepted request: {odgovor.id_zahtjeva}")


def test_evidentiraj_naplatu(certificate: Certificate, eracun: ERacun) -> None:
    client = EFiskalizacijaClient(certificate, env=Environment.DEMO)
    client.evidentiraj_izlazni(eracun)

    izvj = EIzvjestavanjeClient(certificate, env=Environment.DEMO)
    odgovor = izvj.evidentiraj_naplatu(
        Naplata.za_eracun(eracun, datum_naplate=date.today(), naplaceni_iznos=Decimal("1.25"))
    )

    assert odgovor.prihvacen


def test_ovlastenja(certificate: Certificate) -> None:
    oib = os.environ[_OIB_VAR]
    client = EIzvjestavanjeClient(certificate, env=Environment.DEMO)

    oibi = client.ovlastenja(oib)

    print(f"\nAuthorised OIBs for {oib}: {oibi}")
