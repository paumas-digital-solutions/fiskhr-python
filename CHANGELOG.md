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

- `fiskalhr.f1.radno_vrijeme` — working-hours registration (schema v1.10):
  models for the full schedule structure (`Redovno` with `PoDogovoru` /
  `Jednokratno` / `Dvokratno` / `ParniNeparni`, exceptions, deletion), the
  three message types (`prijavi`/`obrisi`/`dohvati_radno_vrijeme` on the
  client), and parsing of fetched schedules back into models. `DanUTjednu`
  1–7 are Monday–Sunday, 8 is a public holiday (praznik). The bulk
  `PrijaviRadnoVrijemeZaPoslovnice` method is not implemented yet.
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
  XSD-validating and signing as before. Radno-vrijeme methods (new in
  schema v1.10) remain unimplemented for now.

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
