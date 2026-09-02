# Architecture

This document records the load-bearing decisions. If a change contradicts
something here, either the change is wrong or this document must be updated in
the same PR.

## The one big decision: F1 and F2 are separate

Fiskalizacija 1.0 (B2C receipts → CIS) and Fiskalizacija 2.0 (B2B eRačun) are
two genuinely different systems that happen to share terminology and
certificates. The package structure models that honestly:

```
src/fiskalhr/
├── core/                 # regime-agnostic; may not import f1 or f2
│   ├── certs.py          # P12 loading, cert inspection            [done]
│   ├── environment.py    # DEMO / PRODUCTION selection             [done]
│   ├── errors.py         # exception hierarchy                     [done]
│   ├── signing.py        # SignatureMethod (SHA-256/SHA-1 timeline)[done]
│   ├── types.py          # OIB validation, shared value objects    [done]
│   ├── xmldsig.py        # enveloped signature create + verify (F1)[done]
│   ├── xades.py          # XAdES-B enveloped signatures (F2)       [done]
│   ├── wsse.py           # WS-Security envelope signatures (FINA)  [done]
│   └── transport.py      # SOAP 1.1 client, TLS 1.2+, mTLS, retries[done]
│
├── f1/                   # Fiskalizacija 1.0 — B2C, CIS
│   ├── zki.py            # offline ZKI computation                 [done]
│   ├── service.py        # endpoints, SCHEMA_VERSION               [done]
│   ├── error_codes.py    # s001–s013 table from the spec           [done]
│   ├── models.py         # Racun, Porez, BrojRacuna, ... (Pydantic) [done]
│   ├── messages.py       # request/response XML serialisation      [done]
│   ├── client.py         # FiskalizacijaClient (public F1 surface) [done]
│   ├── radno_vrijeme.py  # working-hours registration (v1.10)      [done]
│   └── schemas/          # vendored XSDs, versioned                [done: v1.10]
│
├── f2/                   # Fiskalizacija 2.0 — eRačun              [Phase 2+]
│   ├── ubl/              # UBL 2.1 builder, BT-/BG- models, CIUS rules [done]
│   ├── validation/       # XSD + Schematron, structured reports    [done]
│   ├── fiskalizacija/    # EvidentirajERacun (XAdES-B, direct)     [done]
│   ├── izvjestavanje/    # EvidentirajNaplatu/Odbijanje, Ovlastenja [done]
│   ├── posrednik/        # delivery: Posrednik protocol + FINA     [done]
│   └── schemas/
│
├── testing/              # public test utilities for downstream users
│   ├── mock_cis.py       # F1 mock: XSD-validating, response-signing [done]
│   ├── mock_efiskalizacija.py  # F2 reporting mock (XAdES)         [done]
│   ├── mock_eizvjestavanje.py  # F2 payment/rejection mock         [done]
│   ├── mock_posrednik.py # F2 delivery mock (WS-Security)          [done]
│   └── fixtures.py
│
└── cli.py                # cert info, zki, echo                    [growing]
```

Import rules, enforced by review (and later by lint):

1. `core` never imports from `f1` or `f2`.
2. `f1` and `f2` never import from each other.
3. `testing` may import anything; nothing outside tests imports `testing`.

## Design principles

1. **Stateless clients.** Construct with a certificate and an environment;
   every method is request → response. No hidden session state, no background
   threads. Retry queues, outboxes, and persistence belong to the caller.
2. **Sync first, async next.** The sync client is built on `httpx`; the async
   client shares the same message layer (Phase 4). Message
   construction/parsing never does I/O, which is what makes this cheap.
3. **Typed everywhere.** Full type hints, `py.typed`, mypy `--strict` in CI.
4. **Errors are structured, not strings.** `FiskalizacijaError` is the base;
   server-reported errors carry `.code` (`s001`, …) and `.message_hr`.
   Signature-verification failure is its own type
   (`SignatureVerificationError`) because a response whose signature does not
   verify must never be handled as a transport hiccup.
5. **Offline where the domain demands it.** ZKI computation never touches the
   network — a receipt must print its ZKI even when CIS is down.
6. **Vendored, versioned schemas.** The Tax Administration updates schemas in
   production (most recently 25 Jan 2026). Schemas are vendored under a
   version directory, exposed via a `SCHEMA_VERSION` constant, and every
   release documents its target spec revision in the changelog.
   `docs/specs/SOURCES.md` records where each artifact came from and when.

## Language policy

Decided once, applied everywhere:

- Code, docstrings, README, error messages: **English**.
- Domain terms: **Croatian, exactly as the spec spells them** — `zki`, `jir`,
  `oib`, `oznPosPr`, `brOznRac`, `nacinPlac`, `izracunaj_zki`.

Every user of this library reads the Croatian spec alongside the code.
A translated field name forces a mental mapping and is a constant source of
bugs, so spec field names are never translated.

## Security posture

- TLS chain verification and response-signature verification are **on by
  default**; disabling either requires an explicit, loudly-named parameter.
- No certificate, key, or P12 file may enter the repository — enforced by
  `.gitignore` and a hard-failing pre-commit hook. Tests generate throwaway
  self-signed certificates at runtime.
- Passwords: never stored on objects, never logged, never echoed in error
  messages, never accepted as CLI arguments (env var or interactive prompt).
- SHA-1/MD5 appear only where the F1 spec mandates them (ZKI, XML-DSig
  profile) and are marked as such at the call site.

## The Posrednik boundary (F2 delivery)

Building an AS4/Peppol access point is explicitly out of scope. The library
ends at a `Posrednik` protocol: it hands over a finished, signed, validated
UBL document and receives delivery status back. One reference adapter (FINA
e-Račun) ships with the library; the community can add more. Anything that
smells like transport-level AS4 belongs behind that interface, in someone
else's package.

The boundary held, and the national specification is the reason it had to:
the ERP-to-intermediary hop is explicitly outside the AS4 profile ("Način
komunikacije i protokoli prijenosa podataka u ovom koraku procesa nisu
predmet ove specifikacije"), so every intermediary defines its own
interface. `Posrednik` is where that variation stops.

One consequence the protocol has to carry rather than hide:
**an intermediary may fiscalize on your behalf.** FINA reports invoices sent
through it to the Tax Administration for its B2B and B2G users, so a caller
that also calls `EFiskalizacijaClient` for the same invoice files it twice.
`Posrednik.fiskalizira` states the adapter's behaviour so that is a decision
made once, not a guess made per invoice.

## What stays out of the library

The test for whether something belongs here: *if two competing ERPs would
implement it identically because the spec leaves no choice, it belongs in the
library.* Consequently these are **callers' problems, permanently**: invoice
numbering strategy, retry queues and outboxes, persistence, the 48-hour
late-submission workflow's scheduling, storno business rules, multi-tenant
certificate management, KPD assignment heuristics.

## Testing strategy

Five layers, from `CONTRIBUTING.md`'s point of view:

1. **Unit, no network** — ZKI vectors, formatting, OIB checksums (verified
   against publicly known real OIBs), cert handling with runtime-generated
   throwaway certs.
2. **Golden fixtures** — every message type has stored request/response XML;
   regenerating a fixture is a deliberate, reviewable act.
3. **Mock CIS server** — shipped as public API (`fiskalhr.testing`) so
   downstream users can test their integration without the demo environment.
4. **Demo smoke tests** — `pytest -m demo`, skipped by default, run manually
   with FINA demo certificates, never in CI.
5. **Conformance corpus** — known-valid and known-invalid UBL samples;
   validation tests assert the correct rule fires on each invalid one.

## Decisions made

- **Models: Pydantic v2** (over plain dataclasses). The validation is the
  product: OIB checksums, schema patterns (``BrOznRac``, ``OznPosPr``), and
  frozen value semantics come for free, and the library's primary consumers
  (FastAPI-based systems) already carry the dependency. Models are frozen
  and reject unknown fields (``extra="forbid"``) so typos fail loudly.
- **Schematron: pre-compiled XSLT + `saxonche` as an optional extra.** The
  official HR rules declare ``queryBinding="xslt2"`` and embed XSLT
  functions (``u:ctrlOIB``), so a real XSLT 2.0 engine is unavoidable.
  The ``.sch`` is compiled once with SchXslt (Apache-2.0) and the compiled
  stylesheet is vendored, so runtime needs only SaxonC-HE (``saxonche``),
  installed via ``fiskalhr[validation]``. Core install stays lean; XSD-only
  validation works without the extra. Regeneration procedure in SOURCES.md.
- **XML-DSig: `signxml`** (over `lxml` + `xmlsec`). Rationale: pure-Python
  dependency chain (lxml + cryptography, no libxmlsec system library),
  supports the exact spec profile (enveloped + exc-c14n requests,
  inclusive-c14n responses, RSA-SHA256 with an explicit legacy SHA-1 path),
  and refuses SHA-1 by default, matching our secure-by-default posture.
  ``tests/test_xmldsig.py`` pins the produced XML to the spec profile so a
  library upgrade cannot silently change the wire format. Revisit only if
  the demo-environment smoke test surfaces an interop failure.

## Resolved: what the FINA leg actually requires

The Phase 4 open question — whether FINA's own signing makes the `Posrednik`
adapter thinner — is answered, and the answer is the opposite: it makes it
thicker. A FINA request carries **two independent signatures**, and the
library must produce both.

1. **The envelope**, signed with WS-Security (`core/wsse.py`): one reference
   over a `wsu:Id`-tagged SOAP `Body`, exclusive c14n with an
   `InclusiveNamespaces` PrefixList, RSA-SHA256, and the certificate carried
   as a `wsse:SecurityTokenReference`/`KeyIdentifier` rather than
   `ds:X509Data`.
2. **The invoice**, signed with XAdES inside its own `UBLExtensions` — the
   `sac:SignatureInformation` slot `f2/ubl/xml.py` has always emitted empty.
   Its profile differs from the Tax Administration's message signatures in
   two ways that matter: the data reference uses the XPath transform
   `not(ancestor-or-self::sig:UBLDocumentSignatures)` rather than the
   enveloped-signature transform, and the signed properties carry
   `xades:SigningCertificate` (ETSI v1.3.2), not `SigningCertificateV2`.

Two further consequences for the boundary:

- **2-way TLS.** Unlike the Tax Administration's services, FINA authenticates
  the client at the transport layer as well, so `SoapClient` takes an
  optional `client_certificate`.
- **The OIB in the invoice must match the OIB in the signing certificate**,
  or FINA rejects the message before it enters their system. That coupling
  between document content and transport credential is the adapter's, not
  the caller's, to check.

FINA's interface definitions are deliberately not vendored (see
`docs/specs/SOURCES.md`); the profiles above were derived from their sample
requests and are pinned by tests instead of by a schema.
