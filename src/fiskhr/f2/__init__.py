"""Fiskalizacija 2.0 — B2B eRačun (UBL 2.1, HR CIUS 2025).

Covers building and validating eRačun documents and the Tax Administration's
``eFiskalizacija`` / ``eIzvještavanje`` reporting services. Delivery to the
buyer goes through an informacijski posrednik behind the ``Posrednik``
adapter interface (Phase 4).

Vendored schemas live under ``schemas/`` (see ``docs/specs/SOURCES.md``):
UBL 2.1 + the HR extension XSD, the HR CIUS 2025 Schematron (1.0.0,
``queryBinding="xslt2"``), and the eFiskalizacija / eIzvještavanje / LIPO
service schemas.

Key constants of the regime (from the official examples and CIUS spec):

- ``CustomizationID``: ``urn:cen.eu:en16931:2017#compliant#
  urn:mfin.gov.hr:cius-2025:1.0#conformant#urn:mfin.gov.hr:ext-2025:1.0``
- ``ProfileID``: ``P1``

Phase 2 modules are in place: ``fiskhr.f2.ubl`` (models, `ERacunBuilder`,
``to_xml``) and ``fiskhr.f2.validation`` (XSD + Schematron with structured
reports). Phase 3 adds the eFiskalizacija messages.
"""
