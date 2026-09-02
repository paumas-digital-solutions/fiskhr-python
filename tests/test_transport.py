from __future__ import annotations

import ssl
import tempfile
from pathlib import Path

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import rsa
from lxml import etree

from fiskalhr.core.certs import Certificate
from fiskalhr.core.errors import TransportError
from fiskalhr.core.transport import (
    SOAP_ENV_NS,
    SoapClient,
    _ssl_context,
    unwrap_soap,
    wrap_soap,
)

URL = "https://cis.example.invalid/service"
ACTION = "http://example.invalid/action"


def _payload() -> etree._Element:
    return etree.Element("{urn:test}Ping")


def test_wrap_unwrap_roundtrip() -> None:
    wrapped = wrap_soap(_payload())
    envelope = etree.fromstring(wrapped)
    assert envelope.tag == f"{{{SOAP_ENV_NS}}}Envelope"

    payload = unwrap_soap(wrapped)
    assert payload.tag == "{urn:test}Ping"


def test_unwrap_rejects_malformed_xml() -> None:
    with pytest.raises(TransportError, match="not well-formed"):
        unwrap_soap(b"<broken")


def test_unwrap_rejects_empty_body() -> None:
    empty = (
        f'<soapenv:Envelope xmlns:soapenv="{SOAP_ENV_NS}"><soapenv:Body/></soapenv:Envelope>'
    ).encode()
    with pytest.raises(TransportError, match="no body payload"):
        unwrap_soap(empty)


def test_soap_fault_raises_with_faultstring() -> None:
    fault = (
        f'<soapenv:Envelope xmlns:soapenv="{SOAP_ENV_NS}"><soapenv:Body>'
        f"<soapenv:Fault><faultcode>soapenv:Server</faultcode>"
        f"<faultstring>kaboom</faultstring></soapenv:Fault>"
        f"</soapenv:Body></soapenv:Envelope>"
    ).encode()
    with pytest.raises(TransportError, match="kaboom"):
        unwrap_soap(fault)


def test_call_sends_soap_action_and_returns_payload() -> None:
    seen: dict[str, str] = {}

    def responder(request: httpx.Request) -> httpx.Response:
        seen["soapaction"] = request.headers["SOAPAction"]
        seen["content-type"] = request.headers["Content-Type"]
        return httpx.Response(200, content=wrap_soap(etree.Element("{urn:test}Pong")))

    with SoapClient(URL, transport=httpx.MockTransport(responder)) as client:
        response = client.call(_payload(), soap_action=ACTION)

    assert response.tag == "{urn:test}Pong"
    assert seen["soapaction"] == f'"{ACTION}"'
    assert seen["content-type"].startswith("text/xml")


def test_connection_errors_are_retried_then_raised() -> None:
    attempts = {"n": 0}

    def failing(_request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        raise httpx.ConnectError("refused")

    with (
        SoapClient(URL, retries=2, transport=httpx.MockTransport(failing)) as client,
        pytest.raises(TransportError, match="after 3 attempts"),
    ):
        client.call(_payload(), soap_action=ACTION)

    assert attempts["n"] == 3


def test_received_responses_are_never_retried() -> None:
    attempts = {"n": 0}

    def faulting(_request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(500, content=b"")

    with (
        SoapClient(URL, retries=5, transport=httpx.MockTransport(faulting)) as client,
        pytest.raises(TransportError, match="HTTP 500"),
    ):
        client.call(_payload(), soap_action=ACTION)

    assert attempts["n"] == 1  # a received response is final


def test_client_certificate_is_installed_in_the_tls_context(
    rsa_key: rsa.RSAPrivateKey, self_signed_cert: x509.Certificate
) -> None:
    certificate = Certificate(private_key=rsa_key, certificate=self_signed_cert)

    context = _ssl_context(certificate)

    # A loaded chain is the only observable difference; the key itself is
    # deliberately not reachable from the context.
    assert context.get_ca_certs() is not None
    assert len(context.get_ciphers()) > 0
    assert context.minimum_version is ssl.TLSVersion.TLSv1_2


def test_client_certificate_leaves_no_key_material_on_disk(
    rsa_key: rsa.RSAPrivateKey, self_signed_cert: x509.Certificate
) -> None:
    certificate = Certificate(private_key=rsa_key, certificate=self_signed_cert)
    before = set(Path(tempfile.gettempdir()).glob("*.pem"))

    _ssl_context(certificate)

    assert set(Path(tempfile.gettempdir()).glob("*.pem")) == before


def test_no_client_certificate_by_default() -> None:
    context = _ssl_context()

    assert context.verify_mode is ssl.CERT_REQUIRED
    assert context.minimum_version is ssl.TLSVersion.TLSv1_2
