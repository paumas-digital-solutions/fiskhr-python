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
│   ├── xmldsig.py        # enveloped signature create + verify     [done]
│   └── transport.py      # SOAP 1.1 client, TLS 1.2+, retries      [done]
│
├── f1/                   # Fiskalizacija 1.0 — B2C, CIS
│   ├── zki.py            # offline ZKI computation                 [done]
│   ├── service.py        # endpoints, SCHEMA_VERSION               [done]
│   ├── error_codes.py    # s001–s013 table from the spec           [done]
│   ├── models.py         # Racun, Porez, BrojRacuna, ... (Pydantic) [done]
│   ├── messages.py       # request/response XML serialisation      [done]
│   ├── client.py         # FiskalizacijaClient (public F1 surface) [done]
│   └── schemas/          # vendored XSDs, versioned                [done: v1.10]
│
├── f2/                   # Fiskalizacija 2.0 — eRačun              [Phase 2+]
│   ├── ubl/              # UBL 2.1 builder, BT-/BG- models, CIUS rules
│   ├── validation/       # XSD + Schematron, structured reports
│   ├── fiskalizacija.py  # EvidentirajERacun
│   ├── izvjestavanje.py  # EvidentirajNaplatu, EvidentirajOdbijanje
│   ├── posrednik/        # delivery adapters (base protocol + FINA)
│   └── schemas/
│
├── testing/              # public test utilities for downstream users
│   ├── mock_cis.py       # XSD-validating, response-signing mock   [done]
│   └── fixtures.py
│
└── cli.py                # `fiskalhr` command                      [growing]
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
- **XML-DSig: `signxml`** (over `lxml` + `xmlsec`). Rationale: pure-Python
  dependency chain (lxml + cryptography, no libxmlsec system library),
  supports the exact spec profile (enveloped + exc-c14n requests,
  inclusive-c14n responses, RSA-SHA256 with an explicit legacy SHA-1 path),
  and refuses SHA-1 by default, matching our secure-by-default posture.
  ``tests/test_xmldsig.py`` pins the produced XML to the spec profile so a
  library upgrade cannot silently change the wire format. Revisit only if
  the demo-environment smoke test surfaces an interop failure.

## Open questions (resolve before the relevant phase)

- Whether the FINA e-Račun module's own signing makes the `Posrednik` adapter
  thinner than expected (open question with FINA support; affects Phase 4).
