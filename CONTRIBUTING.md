# Contributing to fiskalhr

Thanks for considering a contribution! This document covers setup, the rules
that keep the codebase consistent, and what makes a PR easy to merge.

## Development setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/paumas-digital-solutions/fiskhr-python
cd fiskhr-python
make install        # uv sync + pre-commit install
make check          # lint + mypy --strict + tests with coverage — same as CI
```

Individual steps: `make lint`, `make format`, `make typecheck`, `make test`.

## Ground rules

- **Language policy.** Code, docstrings, comments, and error messages are
  English. Croatian domain terms stay Croatian and are spelled exactly as in
  the spec: `zki`, `jir`, `oib`, `oznPosPr`, `brOznRac`. Never translate a
  spec field name. (Rationale in [ARCHITECTURE.md](ARCHITECTURE.md).)
- **Typing.** Everything passes `mypy --strict`. No `# type: ignore` without
  a reason on the same line.
- **Tests.** New behaviour comes with tests. Unit tests must not touch the
  network. Anything spec-derived (formats, checksums, message shapes) gets a
  golden vector or fixture, with a comment saying where it comes from.
- **Certificates and secrets.** Never commit certificate or key material —
  not even test fixtures. Pre-commit blocks `*.p12`/`*.pem`/etc. outright;
  tests generate throwaway self-signed certs at runtime (see
  `tests/conftest.py`). Never log or echo passwords, and never add secrets to
  CI.
- **Import boundaries.** `core` must not import `f1`/`f2`; `f1` and `f2` must
  not import each other.
- **Schemas.** Vendored schema updates are their own PR: the new files, the
  source URL and retrieval date in `docs/specs/SOURCES.md`, and a changelog
  entry naming the spec revision. Never mix a schema bump with feature work.

## Demo-environment smoke tests

`make smoke-test` (`pytest -m demo`) talks to the real CIS demo environment
and requires FINA demo certificates configured locally. These are manual-only
and never run in CI. A failing smoke test with a current demo certificate is
valuable information — please report it even without a fix.

## Pull requests

- Keep PRs focused; separate refactors from behaviour changes.
- Update `CHANGELOG.md` under `[Unreleased]` for anything user-visible.
- CI (ruff, mypy `--strict`, pytest on 3.11–3.13) must be green.

## Reporting issues

Bug reports with a failing test or a captured request/response XML (with OIBs
and identifiers redacted!) are gold. For questions about the regulations
themselves: this project cannot give tax advice — the
[Tax Administration](https://porezna-uprava.gov.hr) is the authority.

## Conduct

Be kind and assume good faith. Maintainer response times vary — this project
is maintained part-time; the goal is days, not hours.
