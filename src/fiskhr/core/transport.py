"""SOAP 1.1 transport over HTTPS (httpx).

Wraps a payload element in a SOAP envelope, POSTs it, and unwraps the
response body. Policy, per the tech spec and this library's posture:

- **TLS 1.2 minimum.** The test environment rejects TLS 1.1 since
  2026-07-01, production from 2027-01-01; we never offer less anywhere.
  Certificate verification is always on; there is deliberately no parameter
  to disable it.
- **1-way TLS**: the client authenticates messages by signing them
  (XML-DSig), not with a TLS client certificate.
- **Retries only below the response boundary.** Connection errors and
  timeouts are retried (the request may never have arrived); once any HTTP
  response is received, it is never retried here — resubmission of an
  unanswered fiscalization message is the caller's regulated workflow
  (naknadna dostava), not a transport concern.
- A SOAP Fault raises `TransportError` with the fault string; the F1 layer's
  business errors travel inside regular responses, not faults.
"""

from __future__ import annotations

import ssl
import time

import httpx
from lxml import etree

from fiskhr.core.errors import TransportError

__all__ = ["SOAP_ENV_NS", "SoapClient"]

SOAP_ENV_NS = "http://schemas.xmlsoap.org/soap/envelope/"

_TIMEOUT = 30.0
_RETRIES = 2
_BACKOFF_S = 1.0


def _ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def wrap_soap(payload: etree._Element) -> bytes:
    """Wrap a payload element in a SOAP 1.1 envelope."""
    envelope = etree.Element(f"{{{SOAP_ENV_NS}}}Envelope", nsmap={"soapenv": SOAP_ENV_NS})
    body = etree.SubElement(envelope, f"{{{SOAP_ENV_NS}}}Body")
    body.append(payload)
    return etree.tostring(envelope, xml_declaration=True, encoding="UTF-8")


def unwrap_soap(data: bytes) -> etree._Element:
    """Extract the single payload element from a SOAP 1.1 envelope.

    Raises:
        TransportError: On malformed XML, a SOAP Fault, or an empty body.
    """
    try:
        envelope = etree.fromstring(data)
    except etree.XMLSyntaxError as exc:
        raise TransportError(f"response is not well-formed XML: {exc}") from exc

    fault = envelope.find(f".//{{{SOAP_ENV_NS}}}Fault")
    if fault is not None:
        fault_string = fault.findtext("faultstring") or "unknown SOAP fault"
        raise TransportError(f"SOAP fault from service: {fault_string}")

    body = envelope.find(f"{{{SOAP_ENV_NS}}}Body")
    if body is None or len(body) == 0:
        raise TransportError("SOAP response has no body payload")
    return body[0]


class SoapClient:
    """Minimal SOAP 1.1 client for the CIS service.

    Args:
        url: Service endpoint (`fiskhr.f1.service.SERVICE_URLS`).
        timeout: Per-request timeout in seconds.
        retries: Extra attempts after connection errors/timeouts only —
            never after an HTTP response was received.
        transport: Optional httpx transport, injectable for testing
            (e.g. ``httpx.MockTransport`` or `fiskhr.testing.MockCis`).
    """

    def __init__(
        self,
        url: str,
        *,
        timeout: float = _TIMEOUT,
        retries: int = _RETRIES,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.url = url
        self.retries = retries
        self._client = httpx.Client(
            verify=_ssl_context() if transport is None else True,
            timeout=timeout,
            transport=transport,
        )

    def call(self, payload: etree._Element, *, soap_action: str) -> etree._Element:
        """POST a payload and return the unwrapped response payload element.

        Raises:
            TransportError: If the service is unreachable after retries,
                answers with an unexpected HTTP status and no SOAP body, or
                returns a SOAP fault.
        """
        request_body = wrap_soap(payload)
        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": f'"{soap_action}"',
        }

        last_error: httpx.TransportError | None = None
        for attempt in range(self.retries + 1):
            if attempt:
                time.sleep(_BACKOFF_S * attempt)
            try:
                response = self._client.post(self.url, content=request_body, headers=headers)
            except httpx.TransportError as exc:
                last_error = exc
                continue
            # A response was received: from here on, never retry.
            # CIS answers SOAP faults with HTTP 500, so parse before status.
            try:
                return unwrap_soap(response.content)
            except TransportError:
                if response.status_code != 200 and not response.content:
                    raise TransportError(
                        f"service answered HTTP {response.status_code} with an empty body"
                    ) from None
                raise

        raise TransportError(
            f"cannot reach {self.url} after {self.retries + 1} attempts: {last_error}"
        ) from last_error

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SoapClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
