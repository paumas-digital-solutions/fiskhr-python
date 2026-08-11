"""Smoke tests against the real CIS demo environment. Manual only.

Never run in CI (no secrets there, ever). Run locally with FINA demo
certificates:

    export FISKALHR_DEMO_P12=/path/to/fiskalDemo.p12
    export FISKALHR_DEMO_P12_PASSWORD=...
    export FISKALHR_DEMO_OIB=...        # the OIB the demo cert is issued to
    make smoke-test

Getting a JIR back here is the v0.1 milestone.
"""

from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal

import pytest

from fiskalhr.core.certs import Certificate
from fiskalhr.core.environment import Environment
from fiskalhr.f1.client import FiskalizacijaClient
from fiskalhr.f1.models import BrojRacuna, NacinPlacanja, OznakaSlijednosti, Porez, Racun

pytestmark = pytest.mark.demo

_P12_VAR = "FISKALHR_DEMO_P12"
_PASSWORD_VAR = "FISKALHR_DEMO_P12_PASSWORD"
_OIB_VAR = "FISKALHR_DEMO_OIB"


@pytest.fixture(scope="module")
def demo_client() -> FiskalizacijaClient:
    missing = [var for var in (_P12_VAR, _PASSWORD_VAR, _OIB_VAR) if not os.environ.get(var)]
    if missing:
        pytest.skip(f"demo environment not configured: set {', '.join(missing)}")
    certificate = Certificate.from_p12(os.environ[_P12_VAR], os.environ[_PASSWORD_VAR])
    return FiskalizacijaClient(certificate, env=Environment.DEMO)


def test_echo(demo_client: FiskalizacijaClient) -> None:
    reply = demo_client.echo("fiskalhr smoke test")
    assert "fiskalhr smoke test" in reply


def test_fiskaliziraj_returns_jir(demo_client: FiskalizacijaClient) -> None:
    oib = os.environ[_OIB_VAR]
    racun = Racun(
        oib=oib,
        u_sust_pdv=True,
        dat_vrijeme=datetime.now(),
        ozn_slijed=OznakaSlijednosti.POSLOVNI_PROSTOR,
        br_rac=BrojRacuna(br_ozn_rac="1", ozn_pos_pr="SMOKE1", ozn_nap_ur="1"),
        pdv=(Porez(stopa=Decimal("25.00"), osnovica=Decimal("1.00"), iznos=Decimal("0.25")),),
        iznos_ukupno=Decimal("1.25"),
        nacin_plac=NacinPlacanja.OSTALO,
        oib_oper=oib,
    )

    odgovor = demo_client.fiskaliziraj(racun)

    assert odgovor.ok
    assert odgovor.jir is not None
    print(f"\nJIR from demo environment: {odgovor.jir}")
