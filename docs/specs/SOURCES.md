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


## Vendored artifacts — F2 (Fiskalizacija 2.0 / eRačun)

All retrieved 2026-08-13 by the maintainer from the Porezna uprava
Fiskalizacija 2.0 technical documentation downloads.

| File(s) | What it is | Notes |
|---|---|---|
| `f2/Specifikacija_osnovne_uporabe_eRacuna_s_prosirenjima.pdf` | HR CIUS 2025 + ext-2025 specification | Defines BT/BG constraints, `CustomizationID` (`urn:cen.eu:en16931:2017#compliant#urn:mfin.gov.hr:cius-2025:1.0#conformant#urn:mfin.gov.hr:ext-2025:1.0`), `ProfileID` `P1` |
| `f2/Tehnicka_specifikacija_Fiskalizacija_eRacuna_i_eIzvjestavanje.pdf` | F2 technical specification (eFiskalizacija + eIzvještavanje services) | Phase 3 reference |
| `f2/Tehnicka_specifikacija_eRacun_AMS.pdf` | AMS (metadata/adresar service) specification | Reference |
| `f2/Tehnicka_specifikacija_eRacun_PT_AS4.pdf` | AS4 transport profile specification | Reference only — AS4 is out of library scope (`Posrednik` boundary) |
| `f2/PU-AplikacijskiOdgovor-2026-07-27-v1.1.pdf` | ApplicationResponse (prihvat/odbijanje) specification v1.1 (27.07.2026) | |
| `f2/HR-UBL-Schematron-Uputa.pdf` | Instructions for the HR UBL Schematron | From `HRUBLSchematron_13032026-2.zip` |
| `src/fiskalhr/f2/schemas/schematron/*.sch` | **HR CIUS/EXT Schematron rules 1.0.0** (main + codelists), `queryBinding="xslt2"` | Bundle dated 13.03.2026; requires an XSLT 2.0 engine |
| `src/fiskalhr/f2/schemas/schematron/compiled/HR-CIUS-EXT-EN16931-UBL.xsl` | **Generated artifact**: the .sch compiled to an XSLT 2.0 validation stylesheet | Compiled 2026-08-13 with SchXslt 1.10.1 (Apache-2.0, `name.dmaus.schxslt:schxslt` from Maven Central) via `pipeline-for-svrl.xsl` under SaxonC-HE 13. Regenerate whenever the .sch changes and commit both together. |
| `src/fiskalhr/f2/schemas/ubl/**` | UBL 2.1 XSD subset (Invoice + CreditNote maindocs, common) incl. `HRExtensionAggregateComponents-1.xsd` | As distributed by Porezna uprava (`UBL2.1 eRačun.zip`) |
| `src/fiskalhr/f2/schemas/efiskalizacija/*` | eFiskalizacija XSD (17.12.2025) + WSDL (07.11.2025) | `xmldsig-core-schema.xsd` copied in from the F1 bundle — the zip references but does not ship it |
| `src/fiskalhr/f2/schemas/eizvjestavanje/*` | eIzvještavanje XSD (08.02.2026) + WSDL | Same xmldsig note |
| `src/fiskalhr/f2/schemas/lipo/*` | LIPO service XSD + WSDL (08.12.2025), ns `.../fin/2024/types/lipo` | Informacijski-posrednik registry service |
| `tests/conformance/f2/eracuni/*.xml` | 20 official eRačun examples (18 Invoice + 2 CreditNote) | All XSD-valid against the vendored UBL schemas |
| `tests/conformance/f2/fiskalizacija/*.xml` | 13 official signed `EvidentirajERacunZahtjev` examples (SOAP-wrapped) | Signatures are **redacted placeholders** (`Id="value-id- ... "` breaks `xsd:ID`); `signed_EvidentirajERacunZahtjev_NEOP-PP_Trosak.xml` is malformed as shipped (tag mismatch) — kept verbatim, excluded from valid-corpus tests |
| `tests/conformance/f2/eizvjestavanje/*.txt` | Official eIzvještavanje request/response examples | |

## Still to vendor (Phase 4+)

- FINA documentation (demo certificates, e-Račun B2B service) — needed for
  the Phase 4 `Posrednik` reference adapter.

When vendoring, add exact rows to the table above.
