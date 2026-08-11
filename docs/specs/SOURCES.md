# Specification sources

Every spec document, XSD, and Schematron file vendored into this repository
is recorded here with its origin and retrieval date, so a schema bump is
always traceable to an official source.

**Rules:**

1. Nothing enters `docs/specs/` or `src/fiskalhr/*/schemas/` without a row in
   this table.
2. A schema/spec update is its own PR, with a changelog entry naming the
   revision (see CONTRIBUTING.md).
3. Record the *exact* URL the file was retrieved from, even if it is ugly —
   the Tax Administration reorganises its pages, and "somewhere on
   porezna-uprava" is not a source.

## Vendored artifacts

| File(s) | What it is | Source URL | Retrieved | Notes |
|---|---|---|---|---|
| *(none yet)* | | | | Populate during Phase 1 (F1 XSDs + tech spec) and Phase 2 (UBL/CIUS/Schematron). |

## Where to look (starting points, not sources)

- Porezna uprava — Fiskalizacija (F1 technical specification, CIS XSDs,
  error-code list).
- Porezna uprava — Fiskalizacija 2.0 (eRačun, eFiskalizacija /
  eIzvještavanje schemas; production schema update of 25 Jan 2026).
- HR CIUS 2025 + ext-2025 specification and Schematron rules.
- FINA — demo certificates and the e-Račun service documentation.

When vendoring, replace this list's vagueness with exact URLs in the table
above.
