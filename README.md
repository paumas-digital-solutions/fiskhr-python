# fiskalhr

[![CI](https://github.com/paumas-digital-solutions/fiskhr-python/actions/workflows/ci.yml/badge.svg)](https://github.com/paumas-digital-solutions/fiskhr-python/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Croatian fiscalization for Python — both regimes, one library.**

- **Fiskalizacija 1.0 (F1)** — real-time B2C receipt fiscalization against the
  Tax Administration's CIS service: ZKI, XML-DSig, SOAP, JIR.
- **Fiskalizacija 2.0 (F2)** — B2B eRačun: UBL 2.1 invoices conforming to
  HR CIUS 2025, plus the `eFiskalizacija` and `eIzvještavanje` messages.

> **Status: pre-alpha.** The F1 pipeline is implemented end to end —
> certificates, offline ZKI, XML-DSig, SOAP transport, `FiskalizacijaClient`,
> and a mock CIS server for offline testing. On the F2 side, `ERacunBuilder`
> produces UBL 2.1 invoices that pass the complete official validation (XSD
> plus the full HR CIUS 2025 Schematron) with zero findings, and
> `EFiskalizacijaClient` reports them to the Tax Administration with
> XAdES-B-signed `EvidentirajERacun` messages.
> Demo-environment validation is the next milestone; see the
> [roadmap](#roadmap). Nothing is API-stable before v1.0.
>
> Targets **F1 tech spec v2.7 (21.07.2026)** and **schema/WSDL v1.10**,
> including the RSA-SHA1 → RSA-SHA256 migration (SHA-256 is the default;
> the test environment rejects SHA-1 since July 2026).

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

```python
from datetime import datetime
from decimal import Decimal

from fiskalhr import Certificate, Environment
from fiskalhr.f1 import (
    BrojRacuna,
    FiskalizacijaClient,
    NacinPlacanja,
    OznakaSlijednosti,
    Porez,
    Racun,
)

cert = Certificate.from_p12("FISKAL_1.p12", password="...")

racun = Racun(
    oib="12345678903",
    u_sust_pdv=True,
    dat_vrijeme=datetime.now(),
    ozn_slijed=OznakaSlijednosti.POSLOVNI_PROSTOR,
    br_rac=BrojRacuna(br_ozn_rac="1", ozn_pos_pr="POSL1", ozn_nap_ur="12"),
    pdv=(Porez(stopa=Decimal("25.00"), osnovica=Decimal("100.00"), iznos=Decimal("25.00")),),
    iznos_ukupno=Decimal("125.00"),
    nacin_plac=NacinPlacanja.KARTICA,
    oib_oper="12345678903",
)

client = FiskalizacijaClient(cert, env=Environment.DEMO)

zki = client.izracunaj_zki(racun)  # offline — print it on the receipt first
odgovor = client.fiskaliziraj(racun, zki=zki)  # builds, signs, sends, verifies
print(odgovor.jir)
```

Test your integration without the demo environment or a FINA certificate —
the mock validates requests against the official XSD and signs its responses:

```python
from fiskalhr.testing import MockCis

mock = MockCis()  # or MockCis(force_greske=("s004",))
client = FiskalizacijaClient(cert, transport=mock.transport())
odgovor = client.fiskaliziraj(racun)  # never leaves the process
```

And from the terminal:

```bash
fiskalhr cert info FISKAL_1.p12    # password prompted, never a CLI argument
fiskalhr zki FISKAL_1.p12 --oib ... --datum-vrijeme '13.08.2026 12:00:00' \
    --br-ozn-rac 1 --ozn-pos-pr POSL1 --ozn-nap-ur 12 --iznos 125.00
fiskalhr echo --env demo           # CIS connectivity test
fiskalhr validate racun.xml        # XSD + full HR CIUS 2025 Schematron
fiskalhr validate racun.xml --json # machine-readable, for CI pipelines
fiskalhr ovlastenja FISKAL.p12     # which OIBs may this certificate report for (F2)
```

The CLI is deliberately diagnostic-only: it inspects, computes, validates,
and queries, but never fiscalizes — real tax records don't belong in shell
history.

### F2 — building an eRačun

```python
from datetime import date, time

from lxml import etree

from fiskalhr.f2.ubl import ERacunBuilder
from fiskalhr.f2.validation import validate

eracun = (
    ERacunBuilder()
    .izdavatelj(
        oib="12345678903",
        naziv="Tvrtka d.o.o.",
        ulica="Ulica 1",
        grad="Zagreb",
        postanski_broj="10000",
    )
    .primatelj(
        oib="00000000001",
        naziv="Kupac d.o.o.",
        ulica="Ulica 2",
        grad="Rijeka",
        postanski_broj="51000",
    )
    .operater(oib="12345678903", oznaka="Operater1")
    .broj("2026-42-P1-1")
    .datum_izdavanja(date(2026, 8, 13), time(12, 0))
    .datum_isporuke(date(2026, 7, 31))
    .dospijece(date(2026, 9, 12))
    .placanje(iban="HR1210010051863000160", poziv_na_broj="HR00 42")
    .stavka(naziv="Licenca za softver", kpd="62.20.20", kolicina=1, cijena="100.00", pdv_stopa=25)
)

xml = etree.tostring(eracun.to_xml(), xml_declaration=True, encoding="UTF-8")

report = validate(xml)  # official XSD + full HR CIUS 2025 Schematron
assert report.ok
```

Totals, tax subtotals and the `HRFISK20Data` extension are derived from the
line items — you never supply them. Invalid combinations (a standard-rated
line with 0 % PDV, an exempt line without a reason, a bad OIB checksum)
fail at construction time with the HR rule id in the message. The test
suite guarantees built invoices pass the complete official validation with
zero findings — Schematron included (install the `fiskalhr[validation]`
extra for that part).

Credit notes are one call away — `.odobrenje("2026-42-P1-1", date(2026, 8, 13))`
references the corrected invoice and switches the output to a UBL
CreditNote, with the HR rule differences (optional KPD, no due date)
handled for you. Document-level discounts and charges
(`.popust(...)` / `.trosak(...)`) join the VAT breakdown and totals per
EN 16931 automatically.

Reporting the invoice to the Tax Administration (eFiskalizacija) works
straight from the same model — the reported digest is derived from it, and
the request is signed with the XAdES-B profile the service requires:

```python
from fiskalhr import Certificate, Environment
from fiskalhr.f2.fiskalizacija import EFiskalizacijaClient

cert = Certificate.from_p12("FISKAL.p12", password="...")
client = EFiskalizacijaClient(cert, env=Environment.DEMO)

odgovor = client.evidentiraj_izlazni(eracun.build())  # as the issuer
print(odgovor.id_zahtjeva)  # server-assigned request UUID
```

Payments and rejections are reported the same way, referencing the invoice
by its identifier (filled in from the model for you):

```python
from datetime import date

from fiskalhr.f2.izvjestavanje import EIzvjestavanjeClient, Naplata

izvj = EIzvjestavanjeClient(cert, env=Environment.DEMO)
izvj.evidentiraj_naplatu(Naplata.za_eracun(eracun.build(), datum_naplate=date(2026, 9, 1)))
```

For offline testing there are `fiskalhr.testing.MockEFiskalizacija` and
`MockEIzvjestavanje`, the F2 counterparts of `MockCis`: they XSD-validate
requests, verify your XAdES signature, and answer with signed responses.

### F2 — signing and sending through FINA

Reporting is only half of F2: the invoice still has to reach the buyer,
which goes through an informacijski posrednik. FINA is the reference
adapter. It requires the invoice XML itself to be signed — and checks that
its OIB matches the signing certificate's:

```python
from lxml import etree

from fiskalhr.f2.posrednik import FinaPosrednik
from fiskalhr.f2.ubl import sign_eracun, to_xml

document = sign_eracun(to_xml(eracun.build()), cert)

posrednik = FinaPosrednik(cert, env=Environment.DEMO)
isporuka = posrednik.posalji(document, primatelj_oib="00000000001", broj_racuna="2026-42-P1-1")

if isporuka.prihvacen:
    print(isporuka.id_posrednika)  # FINA's identifier for the invoice
else:
    print(isporuka.greske)  # ((code, message), ...)

odgovor = posrednik.status("2026-42-P1-1", godina=2026)
print(odgovor.status)  # StatusIsporuke.PRIHVACEN, .ODBIJEN, ...
```

> **Do not report an invoice twice.** Sending through FINA also files it
> with the Tax Administration on your behalf, so an invoice delivered by
> `FinaPosrednik` must *not* also be reported with `EFiskalizacijaClient`.
> Every adapter states its behaviour in `Posrednik.fiskalizira`.

The delivery leg needs a FINA certificate — it authenticates three ways at
once (2-way TLS, a WS-Security signature over the SOAP body, and the XAdES
signature inside the invoice). `fiskalhr.testing.MockPosrednik` answers the
whole conversation in-process, verifying the WS-Security signature, so you
can build against it before a contract exists.

## Scope

| Area | Included |
|---|---|
| Certificates | P12/PFX loading, cert type detection, expiry checks |
| Crypto | ZKI, XML-DSig enveloped signatures, response signature verification |
| F1 | All CIS message types, SOAP transport, retry/timeout policy |
| F2 documents | UBL 2.1 builder, HR CIUS 2025 + ext-2025 conformance, KPD fields |
| F2 validation | XSD + Schematron with structured reports |
| F2 messages | `EvidentirajERacun`, `EvidentirajNaplatu`, `EvidentirajOdbijanje`, `EvidentirajIsporukuZaKojuNijeIzdanERacun`, `OvlastenjaFiskalizacije` |
| F2 signing | XAdES inside the invoice's own `UBLExtensions`, WS-Security over the SOAP envelope |
| F2 delivery | `Posrednik` protocol with a FINA e-Račun adapter (send, status, echo) |
| Testing tools | Mock CIS server, golden fixtures, demo smoke-test harness |
| CLI | ZKI computation, validation (`--json` for CI), echo, cert inspection, ovlastenja query |

### Explicitly out of scope

- **Not an AS4/Peppol access point.** The library produces, signs, and
  validates documents; delivery goes through the pluggable `Posrednik`
  adapter interface, with FINA e-Račun as the reference implementation. The
  national AS4 specification puts the ERP-to-intermediary hop outside its
  own scope, so that is exactly where this library stops.
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
