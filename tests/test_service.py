from __future__ import annotations

from fiskalhr.core.environment import Environment
from fiskalhr.f1.error_codes import CIS_ERROR_MESSAGES
from fiskalhr.f1.service import SCHEMA_VERSION, SERVICE_URLS, schema_dir


def test_every_environment_has_a_service_url() -> None:
    assert set(SERVICE_URLS) == set(Environment)
    for url in SERVICE_URLS.values():
        assert url.startswith("https://")


def test_vendored_schemas_ship_with_the_package() -> None:
    directory = schema_dir()
    assert directory.name == f"v{SCHEMA_VERSION}"

    names = {path.name for path in directory.iterdir()}
    assert "FiskalizacijaSchema.xsd" in names
    assert "xmldsig-core-schema.xsd" in names
    assert "FiskalizacijaService-educ.wsdl" in names
    assert "FiskalizacijaService-prod.wsdl" in names


def test_error_codes_cover_the_spec_table() -> None:
    # s001..s013 per tech spec v2.7; every code carries a non-empty message.
    assert set(CIS_ERROR_MESSAGES) == {f"s{n:03d}" for n in range(1, 14)}
    assert all(CIS_ERROR_MESSAGES.values())
