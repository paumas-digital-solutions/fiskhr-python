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
| `f2/Tehnicka_specifikacija_eRacun_MPS.pdf` | MPS (metapodatkovni servis) specification — the REST lookup that resolves a recipient's access point | Companion to the AMS DNS lookup; 22 pages |
| `f2/Tehnicka_specifikacija_LIPO.pdf` | LIPO specification — "Web servis - Lista identifikatora poreznih obveznika" (21 pages) | The prose spec for the `lipo` XSD/WSDL vendored above, which until now shipped without one |
| `f2/TS_odbijanje_eRacuna_HUP.pdf` | "Tehnički model implementacije odbijanja eRačuna" (8 pages) | The rejection flow end to end: ApplicationResponse to the supplier **and** `EvidentirajOdbijanje` to the Tax Administration |
| `f2/pts/*.pdf` | Portal za testiranje sukladnosti — official per-scenario test instructions (`upute za testiranje`) | Eight scenarios: slanje/zaprimanje eRačuna, fiskalizacija izlaznog/ulaznog eRačuna, eIzvještavanje naplate/odbijanja, MPS kreiranje/brisanje zapisa. These define what the conformance portal actually exercises, so they drive the demo-environment milestone. |

## Deliberately not vendored — FINA

FINA's e-Račun interface definitions (`SendB2BOutgoingInvoicePKIWebService`,
`B2BFinaInvoiceWebService`, `ReceiveB2BIncomingInvoiceWebService` and the
sample requests that go with them) are **not** kept in this repository.
This is a public repository and those are FINA's artifacts, distributed to
their service users; redistributing them here is not ours to do.

The consequence for contributors: the `Posrednik` FINA adapter is written
against message shapes documented in code, and its tests pin golden XML
rather than validating against a vendored XSD the way the Porezna uprava
messages do. What the FINA bundles establish, recorded here so the code can
cite it without shipping the files:

- **Two independent signatures.** The SOAP envelope carries a WS-Security
  header (`wsu:Timestamp`, plus a `ds:Signature` over a `wsu:Id`-tagged
  `soapenv:Body`; exclusive c14n with `InclusiveNamespaces`, RSA-SHA256,
  `SecurityTokenReference`/`KeyIdentifier`). The UBL document carries its
  own XAdES signature inside
  `ext:UBLExtensions/…/sig:UBLDocumentSignatures/sac:SignatureInformation`
  — reference `URI=""` under the XPath transform
  `not(ancestor-or-self::sig:UBLDocumentSignatures)`, a second reference to
  `SignedProperties`, and `xades:SigningCertificate` (ETSI v1.3.2), **not**
  the `SigningCertificateV2` the Tax Administration's own messages use.
- **Two-way TLS.** The client authenticates with a certificate, unlike the
  Porezna uprava services, where the message signature is the only client
  authentication.
- **OIB binding.** FINA rejects a message whose invoice XML carries an OIB
  different from the one in the signing certificate.
- **Endpoints are not in the WSDLs** — both ship a placeholder
  `soap:address` (`http://ADDRESS/…`), so hosts come from the service
  contract. Confirmed in writing by FINA support (2026-09-02).
- **Party identifiers are scheme-prefixed** (`9934:<oib>`) on both legs —
  `HeaderSupplier/SupplierID` and `HeaderBuyer/BuyerID` alike — even though
  the sync bundle's schema annotates `BuyerID` with a bare example. `9934`
  is the ISO 6523 / CEF EAS code for a Croatian OIB, and is what FINA's own
  signed samples and every Porezna uprava example use.

## Still to vendor

- `UBL-ApplicationResponse-2.1.xsd`. The Tax Administration's `UBL2.1
  eRačun.zip` ships only the Invoice and CreditNote maindoc schemas, so the
  rejection document `fiskalhr.f2.izvjestavanje.odbijanje` produces is the
  one document here with no schema to validate against — its shape is
  pinned by tests instead. The schema is part of the OASIS UBL 2.1
  distribution; vendoring it from there would close the gap.

When vendoring, add exact rows to the tables above.
