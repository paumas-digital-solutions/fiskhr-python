"""Delivery of an eRačun through an informacijski posrednik.

The library ends here: it produces, signs and validates the document, and
hands it over. `Posrednik` is that handover, `FinaPosrednik` the reference
implementation, and `fiskalhr.testing.MockPosrednik` the offline stand-in.

Building an AS4/Peppol access point stays out of scope (ARCHITECTURE.md) —
the ERP-to-intermediary hop is explicitly outside the national AS4
specification, so each intermediary defines its own interface behind this
protocol.
"""

from fiskalhr.f2.posrednik.base import (
    Isporuka,
    Posrednik,
    PosrednikError,
    StatusIsporuke,
    StatusOdgovor,
)
from fiskalhr.f2.posrednik.fina import FinaPosrednik
from fiskalhr.f2.posrednik.service import FINA_SERVICE_URLS, FinaServis

__all__ = [
    "FINA_SERVICE_URLS",
    "FinaPosrednik",
    "FinaServis",
    "Isporuka",
    "Posrednik",
    "PosrednikError",
    "StatusIsporuke",
    "StatusOdgovor",
]
