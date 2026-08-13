from __future__ import annotations

import httpx
import pytest
from lxml import etree

from fiskhr.core.errors import TransportError
from fiskhr.core.transport import SOAP_ENV_NS, SoapClient, unwrap_soap, wrap_soap

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
