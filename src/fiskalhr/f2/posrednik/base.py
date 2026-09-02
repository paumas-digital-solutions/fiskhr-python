"""The ``Posrednik`` boundary — where this library hands an eRačun over.

Building an AS4/Peppol access point is out of scope (see ARCHITECTURE.md).
The library produces, signs and validates the document; an *informacijski
posrednik* delivers it. That handover is this protocol: a finished, signed
UBL document goes in, a delivery result comes back.

The ERP-to-intermediary hop is deliberately unstandardised — the national
AS4 specification says so in as many words ("Način komunikacije i protokoli
prijenosa podataka u ovom koraku procesa nisu predmet ove specifikacije") —
so every intermediary has its own interface. `fiskalhr.f2.posrednik.fina`
is the reference implementation; other adapters implement the same
protocol.

Note on fiscalization: sending through an intermediary may *also* report the
invoice to the Tax Administration on your behalf — FINA does this for its
B2B and B2G users. Where that is the case, calling
`fiskalhr.f2.fiskalizacija.EFiskalizacijaClient` for the same invoice would
report it twice. `Posrednik.fiskalizira` says which behaviour an adapter
has, so a caller can decide once rather than guess per invoice.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from lxml import etree

from fiskalhr.core.errors import FiskalizacijaError

__all__ = [
    "Isporuka",
    "Posrednik",
    "PosrednikError",
    "StatusIsporuke",
    "StatusOdgovor",
]


class PosrednikError(FiskalizacijaError):
    """An intermediary rejected a document or could not deliver it.

    Distinct from `fiskalhr.core.errors.CisError`, which is the Tax
    Administration rejecting a *report*: delivery and fiscalization fail
    independently and are recovered differently.
    """


class StatusIsporuke(enum.StrEnum):
    """Delivery status of a sent eRačun.

    The values are the intermediary's own vocabulary — FINA's
    ``DocumentStatusType`` — because a lowest-common-denominator enum would
    lose exactly the distinctions a caller acts on (a rejection is a
    business event with a deadline; a partial payment is not).
    """

    ZAPRIMLJEN = "RECEIVED"
    """Reached the intermediary."""
    ZAPRIMANJE_POTVRDJENO = "RECEIVING_CONFIRMED"
    """The recipient confirmed receipt."""
    PRIHVACEN = "APPROVED"
    """The recipient accepted the invoice."""
    ODBIJEN = "REJECTED"
    """The recipient rejected it — `StatusOdgovor.napomena` carries why."""
    NAPLATA_ZAPRIMLJENA = "PAYMENT_RECEIVED"
    PLACEN = "PAYMENT_FULFILLED"
    DJELOMICNO_PLACEN = "PAYMENT_PARTIALLY_FULFILLED"


@dataclass(frozen=True)
class Isporuka:
    """The outcome of handing one eRačun to an intermediary.

    Attributes:
        prihvacen: Whether the intermediary took the document. False means
            it was rejected outright — see ``greske``; nothing was delivered
            and nothing will be.
        id_posrednika: The intermediary's own identifier for the document,
            needed to ask about it later. FINA's ``InvoiceID``.
        broj_racuna: The invoice number as the sender knows it, echoed back.
        greske: ``(code, message)`` pairs when the document was rejected.
    """

    prihvacen: bool
    id_posrednika: str | None = None
    broj_racuna: str | None = None
    greske: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class StatusOdgovor:
    """Where a previously sent eRačun has got to.

    Attributes:
        status: The delivery status, or None when the intermediary reported
            a code this library does not know — ``status_kod`` keeps it
            verbatim so an unrecognised value is never silently dropped.
        status_kod: The raw code as received.
        id_posrednika: The intermediary's identifier for the document.
        vrijeme: When the status was set, if reported.
        napomena: Free text — the rejection reason, when rejected.
        djelomicni_iznos: Amount paid so far, for partial payments.
    """

    status: StatusIsporuke | None
    status_kod: str
    id_posrednika: str | None = None
    vrijeme: datetime | None = None
    napomena: str | None = None
    djelomicni_iznos: str | None = None
    dodatno: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class Posrednik(Protocol):
    """What this library needs from an informacijski posrednik.

    Implementations are stateless request/response, like every other client
    here: no queues, no retries beyond the transport's, no persistence. An
    outbox is the caller's, as it has to survive a process restart.
    """

    fiskalizira: bool
    """Whether sending through this intermediary also reports the invoice to
    the Tax Administration. When True, do **not** additionally call
    `fiskalhr.f2.fiskalizacija.EFiskalizacijaClient` for the same invoice."""

    def posalji(
        self, document: etree._Element, *, primatelj_oib: str, broj_racuna: str
    ) -> Isporuka:
        """Hand over one signed eRačun for delivery.

        Args:
            document: A signed UBL Invoice or CreditNote
                (`fiskalhr.f2.ubl.sign_eracun`).
            primatelj_oib: The recipient's OIB.
            broj_racuna: The invoice number in the sender's own system,
                which is how its status is looked up later.

        Raises:
            PosrednikError: The intermediary refused the message itself.
            TransportError: The service could not be reached.
        """
        ...

    def status(self, broj_racuna: str, *, godina: int) -> StatusOdgovor:
        """Ask what happened to a document that was sent earlier."""
        ...

    def echo(self, text: str = "ping") -> str:
        """Round-trip a string; proves credentials and connectivity."""
        ...
