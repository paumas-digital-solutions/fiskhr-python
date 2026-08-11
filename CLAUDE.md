# fiskalhr — instructions for Claude Code

## Git conventions

- **Branch naming: do NOT prefix branches with `claude/`.** Use plain,
  descriptive names: `f1-xmldsig`, `fix-zki-rounding`, `docs-readme`.
  (If the platform has already assigned a branch to the session, keep using
  it; this rule applies to branches you create.)
- No AI attribution in commits or PRs (enforced via `.claude/settings.json`).
- Never mix a vendored schema/spec update with feature work in one commit.

## Project rules (details in ARCHITECTURE.md and CONTRIBUTING.md)

- Language policy: code/docs/errors in English; Croatian domain terms stay
  exactly as the spec spells them (`zki`, `jir`, `oib`, `oznPosPr`).
- Import boundaries: `core` never imports `f1`/`f2`; `f1` and `f2` never
  import each other.
- Never commit certificate/key material (`*.p12`, `*.pem`, ...). Tests
  generate throwaway certs at runtime (`tests/conftest.py`).
- Anything spec-derived cites the spec version and chapter; vendored files
  need a row in `docs/specs/SOURCES.md`.
- Target spec revisions: F1 tech spec v2.7 (21.07.2026), schema/WSDL v1.10.
  RSA-SHA256 is the default signature method everywhere (SHA-1 is legacy,
  production-only until end of 2026).

## Commands

- `make check` — lint + mypy --strict + tests with coverage (same as CI)
- `make test` / `make cov` / `make lint` / `make format` / `make typecheck`
- `make smoke-test` — demo-environment tests; manual only, needs FINA demo
  certs, never in CI
