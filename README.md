# fiskalhr

[![CI](https://github.com/paumas-digital-solutions/fiskhr-python/actions/workflows/ci.yml/badge.svg)](https://github.com/paumas-digital-solutions/fiskhr-python/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Croatian fiscalization for Python — both regimes, one library.**

- **Fiskalizacija 1.0 (F1)** — real-time B2C receipt fiscalization against the
  Tax Administration's CIS service: ZKI, XML-DSig, SOAP, JIR.
- **Fiskalizacija 2.0 (F2)** — B2B eRačun: UBL 2.1 invoices conforming to
  HR CIUS 2025, plus the `eFiskalizacija` and `eIzvještavanje` messages.

> **Status: pre-alpha.** The core layer (certificates, OIB validation, offline
> ZKI computation) works and is fully tested. The F1 client is in progress;
> see the [roadmap](#roadmap). Nothing here is API-stable before v1.0.

*Hrvatska verzija: [README.hr.md](README.hr.md)*

---

## F1 vs F2 — which one do you need?

These are two genuinely separate systems that share terminology and
certificates but nothing else. This library models that separation honestly.

|  | Fiskalizacija 1.0 | Fiskalizacija 2.0 |
|---|---|---|
| What | Fiscalizing **retail (B2C) receipts** in real time | Issuing and reporting **B2B eRačun** (e-invoices) |
| Who | Anyone issuing cash/card receipts | VAT payers since 1 Jan 2026; **everyone else from 1 Jan 2027** |
| Wire format | Custom XML over SOAP to CIS | UBL 2.1 (EN 16931 + HR CIUS 2025) + fiscalization messages |
| Key artifacts | ZKI, JIR | eRačun XML, KPD codes, delivery via posrednik |
| In this library | `fiskalhr.f1` | `fiskalhr.f2` |

If you run a POS or issue receipts to consumers, you need F1. If you invoice
other businesses, you need F2. Many businesses need both.

## Install

```bash
pip install fiskalhr   # placeholder release — pin only from v0.1.0 onward
```

Requires Python 3.11+.

## Quickstart

What works today (v0.0.x):

```python
from datetime import datetime
from decimal import Decimal

from fiskalhr import Certificate
from fiskalhr.f1 import izracunaj_zki

cert = Certificate.from_p12("FISKAL_1.p12", password="...")
print(cert.subject, cert.oib, cert.not_valid_after)

# ZKI is computed fully offline — you need it on the printed receipt
# even when CIS is unreachable.
zki = izracunaj_zki(
    cert.private_key,
    oib="12345678903",
    datum_vrijeme=datetime.now(),
    br_ozn_rac="1",
    ozn_pos_pr="POSL1",
    ozn_nap_ur="12",
    ukupan_iznos=Decimal("125.00"),
)
```

And from the terminal:

```bash
fiskalhr cert info FISKAL_1.p12   # password prompted, never a CLI argument
```

### Target API (Phase 1, in progress)

```python
from fiskalhr import Certificate, Environment
from fiskalhr.f1 import FiskalizacijaClient, Racun

client = FiskalizacijaClient(cert, env=Environment.DEMO)
odgovor = client.fiskaliziraj(racun)  # signs, sends, verifies response signature
print(odgovor.jir)
```

## Scope

| Area | Included |
|---|---|
| Certificates | P12/PFX loading, cert type detection, expiry checks |
| Crypto | ZKI, XML-DSig enveloped signatures, response signature verification |
| F1 | All CIS message types, SOAP transport, retry/timeout policy |
| F2 documents | UBL 2.1 builder, HR CIUS 2025 + ext-2025 conformance, KPD fields |
| F2 validation | XSD + Schematron with structured reports |
| F2 messages | `EvidentirajERacun`, `EvidentirajNaplatu`, `EvidentirajOdbijanje` |
| Testing tools | Mock CIS server, golden fixtures, demo smoke-test harness |
| CLI | ZKI computation, validation, echo, cert inspection |

### Explicitly out of scope

- **Not an AS4/Peppol access point.** The library produces, signs, and
  validates documents; delivery goes through a pluggable `Posrednik` adapter
  interface (FINA e-Račun as the reference implementation).
- **Not an ERP, POS, or accounting system.** No invoice numbering policy, no
  ledger, no persistence — stateless request/response and document
  construction only.
- **Not tax advice.** Nothing in this project is tax or legal advice.
- **Not a compliance guarantee.** Certifying an integrated system remains the
  integrator's responsibility.

## Design principles

- **Stateless clients** — construct with a certificate and an environment;
  every method is request → response.
- **Typed everywhere** — full type hints, `py.typed`, mypy `--strict` in CI.
- **Structured errors** — every server error carries `.code` (`s001`, …) and
  `.message_hr`; signature-verification failure is its own exception type.
- **Croatian domain terms, English everything else** — `zki`, `jir`, `oib`,
  `oznPosPr` stay exactly as the spec spells them; code, docs, and error
  messages are English. See [ARCHITECTURE.md](ARCHITECTURE.md).
- **Vendored, versioned schemas** — schema bumps are explicit, reviewable
  changes; each release documents its target spec revision.
- **Secure by default** — TLS verification and response-signature verification
  are always on; certificate files can never be committed (enforced by
  pre-commit); passwords are never logged, stored, or accepted as CLI
  arguments.

## Roadmap

| Version | Milestone |
|---|---|
| v0.1.0 | F1 complete: a real receipt fiscalizes against the demo environment and returns a JIR |
| v0.2.0 | UBL 2.1 + HR CIUS 2025 building and validation |
| v0.3.0 | F2 fiscalization messages end-to-end |
| v0.4.0 | `Posrednik` delivery adapters, full CLI, async client |
| v1.0.0 | Docs site, API stability commitment |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Issues and PRs welcome — especially
conformance samples (valid/invalid UBL) and additional `Posrednik` adapters.

## Disclaimer

This software is provided under the MIT licence, **without warranty of any
kind**. It is not tax advice, and using it does not by itself make any system
compliant with Croatian fiscalization regulations.
