"""FINA e-Račun B2B service endpoints.

The vendored WSDLs ship ``<soap:address location="http://ADDRESS/..."/>``,
so the real hosts are not derivable from the interface definitions. These
were confirmed in writing by FINA support (e-mail, 2026-09-02) and match
FINA's published integration guides.

Two services, each with a demo and a production host:

- **Slanje računa** — ``SendB2BOutgoingInvoicePKIWebService``, the send leg.
- **Zaprimanje računa** — ``B2BFinaInvoiceWebService``, the recipient-side
  pull leg and status/registry operations.

Note the demo and production hosts differ (``prezdigitalneusluge.fina.hr``
vs ``webservisi.fina.hr``), and FINA issues separate demo and production
certificates: a demo certificate must never be used against production, or
the reverse.
"""

from __future__ import annotations

import enum

from fiskalhr.core.environment import Environment

__all__ = ["FINA_SERVICE_URLS", "FinaServis"]


class FinaServis(enum.StrEnum):
    """Which FINA service an endpoint belongs to."""

    SLANJE = "slanje"
    """Outgoing invoices: ``SendB2BOutgoingInvoicePKIWebService``."""
    ZAPRIMANJE = "zaprimanje"
    """Incoming invoices and status: ``B2BFinaInvoiceWebService``."""


_DEMO_HOST = "https://prezdigitalneusluge.fina.hr"
_PRODUCTION_HOST = "https://webservisi.fina.hr"

_SLANJE_PATH = "SendB2BOutgoingInvoicePKIWebService/services/SendB2BOutgoingInvoicePKIWebService"
_ZAPRIMANJE_PATH = "B2BFinaInvoiceWebService/services/B2BFinaInvoiceWebService"

FINA_SERVICE_URLS: dict[tuple[FinaServis, Environment], str] = {
    (FinaServis.SLANJE, Environment.DEMO): f"{_DEMO_HOST}/{_SLANJE_PATH}",
    (FinaServis.SLANJE, Environment.PRODUCTION): f"{_PRODUCTION_HOST}/{_SLANJE_PATH}",
    (FinaServis.ZAPRIMANJE, Environment.DEMO): f"{_DEMO_HOST}/{_ZAPRIMANJE_PATH}",
    (FinaServis.ZAPRIMANJE, Environment.PRODUCTION): f"{_PRODUCTION_HOST}/{_ZAPRIMANJE_PATH}",
}
