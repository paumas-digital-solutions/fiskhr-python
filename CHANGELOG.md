# Changelog

All notable changes to `fiskalhr` are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/).
Every release also records which Tax Administration spec/schema revision it
targets (see `docs/specs/SOURCES.md`).

## [Unreleased]

### Added

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
