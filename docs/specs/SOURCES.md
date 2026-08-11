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

| File(s) | What it is | Source | Retrieved | Notes |
|---|---|---|---|---|
| `f1/Fiskalizacija_Tehnicka_specifikacija_v2.7_2026-07-21.pdf` | F1 technical specification, **v2.7 (21.07.2026)** | Porezna uprava — Fiskalizacija technical documentation (downloaded by maintainer) | 2026-08-11 | Original filename: `Fiskalizacija - Tehnicka specifikacija za korisnike_v2.7 (21.07.2026.).pdf`. Defines ZKI (ch. 12, RSA-SHA256), XML-DSig profile (exc-c14n requests, inclusive-c14n responses), error codes s001–s013, endpoints (§6.1), SHA-1→SHA-256 and TLS 1.2 migration timeline. |
| `src/fiskalhr/f1/schemas/v1.10/FiskalizacijaSchema.xsd` | CIS XML schema, **v1.10** | Porezna uprava — `Fiskalizacija-WSDL-EDUC_v1.10.zip` / `Fiskalizacija-WSDL-PROD_v1.10.zip` (byte-identical in both) | 2026-08-11 | Bundle dated 05.11.2025 (EDUC) / 24.11.2025 (PROD). Adds `promijeniPodatkeRacuna` and radno-vrijeme methods. |
| `src/fiskalhr/f1/schemas/v1.10/xmldsig-core-schema.xsd` | W3C XML-DSig core schema | Same WSDL bundles | 2026-08-11 | Unmodified W3C schema as shipped by Porezna uprava. |
| `src/fiskalhr/f1/schemas/v1.10/FiskalizacijaService-educ.wsdl` | Service WSDL, test (EDUC) | `Fiskalizacija-WSDL-EDUC_v1.10.zip` | 2026-08-11 | Contains the demo-only `provjera` operation. |
| `src/fiskalhr/f1/schemas/v1.10/FiskalizacijaService-prod.wsdl` | Service WSDL, production | `Fiskalizacija-WSDL-PROD_v1.10.zip` | 2026-08-11 | **Caveat:** ships with the *test* URL in `soap:address`; the real production URL is in the spec §6.1 and `fiskalhr.f1.service.SERVICE_URLS`. No `provjera` operation. |
| `f1/Release-notes-WSDL-EDUC-v1.10.txt`, `f1/Release-notes-WSDL-PROD-v1.10.txt` | Release notes from the WSDL bundles | Same WSDL bundles | 2026-08-11 | |

## Still to vendor (Phase 2+)

- HR CIUS 2025 + ext-2025 specification and Schematron rules.
- eFiskalizacija / eIzvještavanje XSDs (production versions of 25.01.2026).
- FINA documentation (demo certificates, e-Račun service).

When vendoring, add exact rows to the table above.
