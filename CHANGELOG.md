# Changelog

All notable changes to `fiskalhr` are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/).
Every release also records which Tax Administration spec/schema revision it
targets (see `docs/specs/SOURCES.md`).

## [Unreleased]

### Changed

- **ZKI now defaults to RSA-SHA256** per tech spec v2.7 (pseudocode ch. 12).
  The test environment rejects RSA-SHA1 since 2026-07-01; production keeps
  accepting it until end of 2026 (from 2027-01-01 SHA-256 only).
  `izracunaj_zki` takes `method=SignatureMethod.RSA_SHA1` to reproduce
  legacy ZKIs.

### Added

- CLI: `fiskalhr ovlastenja CERT.p12 [oib]` — asks the F2 service which
  OIBs the certificate holder may report for (OIB defaults to the one in
  the certificate subject); `fiskalhr validate --json` prints a
  machine-readable report for CI pipelines. The CLI remains
  diagnostic-only by design — it never fiscalizes.

- Document-level allowances and charges (BG-20/21): `ERacunBuilder.popust()`
  and `.trosak()` join the VAT breakdown per EN 16931 — each group's taxable
  base is its lines minus its allowances plus its charges, and the totals
  carry `AllowanceTotalAmount`/`ChargeTotalAmount` with
  `TaxExclusiveAmount` = lines − allowances + charges (BT-109). Exempt (E)
  or out-of-scope (O) charges get the HR category mark and exemption reason
  (HR-BR-11/13), trigger the `HRFISK20Data` extension (HR-BR-26/30), and
  the extension splits out-of-scope amounts into `OutOfScopeOfVATAmount`
  exactly like the official examples. The eFiskalizacija digest reports
  them as `DokumentPopust`/`DokumentTrosak` with the matching totals.

- Credit notes (odobrenje, UNCL 1001 type 381): `ERacunBuilder.odobrenje()`
  marks the document and references the corrected invoice; type 381
  serialises as a UBL **CreditNote** (`CreditNoteTypeCode`,
  `CreditNoteLine`/`CreditedQuantity`, due date via
  `PaymentMeans/PaymentDueDate`) and passes the full official validation
  with zero findings. Preceding-invoice references (BG-3,
  `BillingReference`, HR-BR-6) are available on all document types via
  `.prethodni_racun()` and flow into the eFiskalizacija digest. KPD codes
  are now optional exactly on the document types HR-BR-25 exempts (381,
  386, …) and enforced at model level otherwise; credit notes don't
  require a due date (HR-BR-4 negates their payable amount).

- `fiskalhr.f2.izvjestavanje` — payment and rejection reporting:
  `EIzvjestavanjeClient.evidentiraj_naplatu` (issuer reports collections;
  `Naplata.za_eracun` fills the eRačun identifier from the UBL model and
  defaults to paid-in-full), `evidentiraj_odbijanje` (recipient reports
  rejections with the `N`/`U`/`O` reason codebook), and `ovlastenja` (which
  OIBs the certificate holder may report for). Shares the endpoint and the
  XAdES-B signature profile with eFiskalizacija; signed requests validate
  against the vendored `eIzvjestavanjeSchema.xsd` in tests.
  `fiskalhr.testing.MockEIzvjestavanje` covers all the operations,
  including `evidentiraj_isporuku` — `EvidentirajIsporukuZaKojuNijeIzdanERacun`
  reports invoices for deliveries where no eRačun was issued (fixed
  ``vrstaRacuna`` ``IR``), reusing the same `EvidencijaERacun` digest as
  eFiskalizacija (the schema types are field-identical).

- `fiskalhr.f2.fiskalizacija` — the F2 reporting leg (`EvidentirajERacun`):
  `EFiskalizacijaClient` reports outgoing/incoming eRačuni directly to the
  Tax Administration's eFiskalizacija service (no intermediary needed for
  reporting), 1–100 records per call. `EvidencijaERacun.from_eracuna`
  derives the reported digest (identifiers, parties, totals, VAT breakdown
  with HR category marks, per-line data with KPD) from the same
  `fiskalhr.f2.ubl.ERacun` model that produced the UBL document, so the
  report matches the invoice by construction. Requests are signed with
  **XAdES-B** (ETSI EN 319 132-1) enveloped signatures per spec ch. 11 —
  new `fiskalhr.core.xades` module, with the wire format pinned by tests
  (two references, enveloped-signature + exc-c14n, RSA-SHA256,
  `SigningCertificateV2`); response signatures are verified by default.
  Endpoints (`:8509`, test path `FiskalizacijaServiceEprod`) in
  `fiskalhr.f2.service`; error table `S001`–`S012` verbatim from the
  schema. `fiskalhr.testing.MockEFiskalizacija` answers with XSD-validated,
  signature-verified, signed responses for offline end-to-end testing.

- `fiskalhr.f2.ubl` — eRačun construction: `ERacunBuilder` (fluent API),
  Pydantic models (`ERacun`, `Stavka`, `Stranka`, `Operater`,
  `KategorijaPdv`) and `to_xml()` producing UBL 2.1 Invoices under HR CIUS
  2025 + ext-2025. Documents carry the required `CustomizationID`,
  `ProfileID`, operator contact (HR-BR-9/37), per-item KPD classification
  (HR-BR-25, `listID="CG"`), the HR VAT category mark `cbc:Name`
  (HR-BT-12, `HR:PDV25`/`HR:E`/…) and line-level exemption reasons
  (HR-BR-16/36), plus the `HRFISK20Data` extension with the HR VAT
  breakdown when exempt (E) or out-of-scope (O) categories are present
  (HR-BR-26/32). Totals are computed, never supplied; category/rate
  consistency, OIB checksums and exemption reasons are enforced at model
  construction. The test suite proves built invoices pass the complete
  official validation — XSD plus the full HR Schematron — with **zero
  findings**.

- `fiskalhr.f2.validation` — eRačun validation returning a structured
  `ValidationReport` (never raises on findings): XSD against the vendored
  UBL 2.1 schemas (Invoice and CreditNote auto-detected), then the HR CIUS
  2025 Schematron rules executed as a pre-compiled XSLT under SaxonC-HE.
  Schematron needs the optional `fiskalhr[validation]` extra (`saxonche`);
  without it, XSD-only validation still works. The conformance tests pin
  the exact rule set that fires on the official examples (their sample data
  uses pre-2026 dates and dummy OIBs), proving the embedded `u:ctrlOIB`
  checksum function executes.
- CLI: `fiskalhr validate racun.xml` — prints findings with rule ids and
  exits non-zero on errors; `--no-schematron` for XSD-only.

- Vendored the complete F2 (Fiskalizacija 2.0 / eRačun) specification set
  from the Tax Administration: HR CIUS 2025 + ext-2025 spec, **HR Schematron
  1.0.0** (13.03.2026, XSLT 2.0 binding), UBL 2.1 XSDs with the HR extension
  schema, eFiskalizacija / eIzvještavanje / LIPO service schemas and WSDLs,
  the F2, AMS, AS4 and ApplicationResponse specification PDFs, and the
  official example corpora (20 eRačuni, 13 signed fiscalization messages,
  eIzvještavanje samples) as the start of the conformance corpus. All
  recorded in `docs/specs/SOURCES.md`, including known defects in the
  shipped examples.

- `fiskalhr.f1.radno_vrijeme` — working-hours registration (schema v1.10):
  models for the full schedule structure (`Redovno` with `PoDogovoru` /
  `Jednokratno` / `Dvokratno` / `ParniNeparni`, exceptions, deletion), the
  three message types (`prijavi`/`obrisi`/`dohvati_radno_vrijeme` on the
  client), and parsing of fetched schedules back into models. `DanUTjednu`
  1–7 are Monday–Sunday, 8 is a public holiday (praznik). The bulk
  `prijavi_radno_vrijeme_za_poslovnice` method registers hours for up to
  100 premises in one call, with per-premises outcomes
  (`PoslovniceOdgovor`); `MockCis` answers it like the rest.
- CLI: `fiskalhr zki` (offline ZKI computation, `--legacy-sha1` for the
  transition period) and `fiskalhr echo` (CIS connectivity test,
  `--env demo|production`).

- Follow-up F1 message types, completing the receipt lifecycle:
  `fiskaliziraj_napojnicu` (tips), `promijeni_nacin_placanja`,
  `promijeni_podatke_racuna` (payment-method / receiver-OIB changes, empty
  OIB allowed per `OibPromjenaType`), and `provjeri` (receipt check,
  demo-environment only — guarded, and its error list is returned rather
  than raised). New models: `Napojnica`, `PorukaOdgovora`,
  `PromjenaOdgovor`, `ProvjeraOdgovor`. `MockCis` answers all of them,
  XSD-validating and signing as before.

- `fiskalhr.f1.client.FiskalizacijaClient` — the public F1 surface:
  `izracunaj_zki` (offline), `fiskaliziraj` (build, sign, send, verify
  response signature, parse; raises structured `CisError` on rejection),
  and `echo`. Response-signature verification is on by default; disabling
  requires the loudly named `allow_unverified_response=True`.
- `fiskalhr.core.transport.SoapClient` — SOAP 1.1 over httpx with a TLS 1.2
  floor and no way to disable certificate verification; retries apply only
  to connection failures, never after a response was received.
- `fiskalhr.testing.MockCis` — public in-process CIS mock that validates
  requests against the official XSD, verifies request signatures, and signs
  its responses with a throwaway certificate, so downstream integrations can
  test the full loop without the demo environment or a FINA certificate.
- `TransportError`; `CisError` now carries the full `greske` list.

- `fiskalhr.f1.models` — Pydantic v2 models mirroring FiskalizacijaSchema
  v1.10 (`Racun`, `Porez`, `PorezOstalo`, `Naknada`, `BrojRacuna`,
  `NacinPlacanja`, `OznakaSlijednosti`, `RacunOdgovor`); frozen, unknown
  fields rejected, OIB fields checksum-validated.
- `fiskalhr.f1.messages` — `build_racun_zahtjev` / `parse_racun_odgovor`;
  every built document is validated against the vendored official XSD in
  tests, signed and unsigned.
- `fiskalhr.core.xmldsig` — enveloped XML-DSig signing and verification per
  spec v2.7 ch. 7 (exclusive-c14n requests, inclusive-c14n responses,
  RSA-SHA256 default with explicit legacy SHA-1, `KeyInfo` with certificate
  + issuer/serial). Built on `signxml`; verification requires an expected
  certificate or a loud `trust_embedded_certificate=True` opt-in. Tests pin
  the produced XML to the spec profile.
- Vendored F1 specification set, targeting **tech spec v2.7 (21.07.2026)**
  and **schema/WSDL v1.10**: `FiskalizacijaSchema.xsd`, W3C xmldsig schema,
  EDUC + PROD WSDLs (shipped inside the package), spec PDF and release notes
  under `docs/specs/f1/`, all recorded in `docs/specs/SOURCES.md`.
- `fiskalhr.core.signing.SignatureMethod` — RSA-SHA256 / RSA-SHA1 with the
  migration timeline documented, shared by ZKI and (upcoming) XML-DSig.
- `fiskalhr.f1.service` — authoritative demo/production endpoint URLs
  (spec §6.1) and `SCHEMA_VERSION`; documents that the official PROD WSDL
  bundle ships with the test URL in `soap:address`.
- `fiskalhr.f1.error_codes.CIS_ERROR_MESSAGES` — the full s001–s013 error
  table from spec v2.7, verbatim Croatian server messages.

- Project scaffold: src layout, `pyproject.toml` (hatchling + uv), ruff,
  mypy `--strict`, pytest with coverage gate, pre-commit (incl. secret
  scanning and a hard block on committing certificate files), CI on
  Python 3.11–3.13.
- `fiskalhr.core.types`: OIB validation (ISO 7064 MOD 11,10), verified
  against publicly known real OIBs.
- `fiskalhr.core.errors`: structured exception hierarchy (`code`,
  `message_hr` on every error).
- `fiskalhr.core.certs.Certificate`: P12/PFX loading, validity checks,
  best-effort OIB extraction from the subject; private key excluded from
  `repr()`, passwords never retained or echoed.
- `fiskalhr.f1.zki`: offline ZKI computation (`izracunaj_zki`,
  `zki_payload`, `format_iznos`).
- CLI: `fiskalhr --version`, `fiskalhr cert info <file.p12>` (password via
  `FISKALHR_P12_PASSWORD` or interactive prompt — never a CLI argument).
