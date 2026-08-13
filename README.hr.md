# fiskhr

**Hrvatska fiskalizacija za Python — oba sustava, jedna biblioteka.**

- **Fiskalizacija 1.0 (F1)** — fiskalizacija računa u prometu gotovinom (B2C)
  prema CIS-u Porezne uprave: ZKI, XML-DSig potpis, SOAP, JIR.
- **Fiskalizacija 2.0 (F2)** — B2B eRačun: UBL 2.1 računi usklađeni s
  HR CIUS 2025 te poruke `eFiskalizacija` i `eIzvještavanje`.

> **Status: pre-alpha.** F1 je implementiran s kraja na kraj — certifikati,
> offline izračun ZKI-ja, XML-DSig potpis, SOAP transport,
> `FiskalizacijaClient` i mock CIS za testiranje bez demo okruženja. Na F2
> strani `ERacunBuilder` gradi UBL 2.1 račune koji prolaze službenu
> validaciju (XSD i kompletna HR CIUS 2025 Schematron pravila) bez ijednog
> nalaza. API nije stabilan prije verzije 1.0.

Potpuna dokumentacija je na engleskom — vidi [README.md](README.md). Nazivi
domenskih pojmova namjerno ostaju hrvatski i identični specifikaciji
(`zki`, `jir`, `oib`, `oznPosPr`, `brOznRac`), jer svatko tko integrira
fiskalizaciju čita hrvatsku specifikaciju uz kod.

## Zašto ova biblioteka

- Pokriva **oba** sustava fiskalizacije; postojeći Python paketi pokrivaju
  samo F1 i uglavnom se ne održavaju.
- Potpuno tipizirana (mypy `--strict`), temeljito testirana, bez mrežnih
  poziva u testovima.
- Sigurna prema zadanim postavkama: TLS i provjera potpisa odgovora uvijek su
  uključeni, certifikati se nikada ne mogu commitati u repozitorij, lozinke se
  nikada ne logiraju.

## Ograda od odgovornosti

Softver se isporučuje pod MIT licencom, **bez ikakvog jamstva**. Ovo nije
porezni ni pravni savjet, a korištenje biblioteke samo po sebi ne čini sustav
usklađenim s propisima o fiskalizaciji.
