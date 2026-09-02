"""SOAP 1.1 transport over HTTPS (httpx).

Wraps a payload element in a SOAP envelope, POSTs it, and unwraps the
response body. Policy, per the tech spec and this library's posture:

- **TLS 1.2 minimum.** The test environment rejects TLS 1.1 since
  2026-07-01, production from 2027-01-01; we never offer less anywhere.
  Certificate verification is always on; there is deliberately no parameter
  to disable it.
- **1-way TLS by default**: against the Tax Administration's services the
  client authenticates messages by signing them (XML-DSig / XAdES), not with
  a TLS client certificate. FINA's e-Račun services are the exception — they
  require 2-way TLS *in addition* to the message signature — so a client
  certificate can be supplied explicitly with ``client_certificate=``.
- **Retries only below the response boundary.** Connection errors and
  timeouts are retried (the request may never have arrived); once any HTTP
  response is received, it is never retried here — resubmission of an
  unanswered fiscalization message is the caller's regulated workflow
  (naknadna dostava), not a transport concern.
- A SOAP Fault raises `TransportError` with the fault string; the F1 layer's
  business errors travel inside regular responses, not faults.
"""

from __future__ import annotations

import os
import ssl
import tempfile
import time
from pathlib import Path

import httpx
from cryptography.hazmat.primitives import serialization
from lxml import etree

from fiskalhr.core.certs import Certificate
from fiskalhr.core.errors import TransportError

__all__ = ["SOAP_ENV_NS", "SoapClient", "build_envelope", "unwrap_soap", "wrap_soap"]

SOAP_ENV_NS = "http://schemas.xmlsoap.org/soap/envelope/"

_TIMEOUT = 30.0
_RETRIES = 2
_BACKOFF_S = 1.0


def _ssl_context(client_certificate: Certificate | None = None) -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    if client_certificate is not None:
        _load_client_certificate(context, client_certificate)
    return context


def _load_client_certificate(context: ssl.SSLContext, certificate: Certificate) -> None:
    """Install a client certificate for 2-way TLS.

    `ssl.SSLContext.load_cert_chain` reads from the filesystem — there is no
    in-memory equivalent in the standard library — so the PEM is written to a
    private temporary file, loaded, and unlinked immediately. The file exists
    only for the duration of this call, is created 0600 by `mkstemp`, and the
    key lives on inside the context, not on disk.
    """
    pem = certificate.certificate.public_bytes(serialization.Encoding.PEM)
    for issuer in certificate.chain:
        pem += issuer.public_bytes(serialization.Encoding.PEM)
    pem += certificate.private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    handle, name = tempfile.mkstemp(suffix=".pem")
    path = Path(name)
    try:
        with os.fdopen(handle, "wb") as file:
            file.write(pem)
        context.load_cert_chain(path)
    except ssl.SSLError as exc:
        raise TransportError(f"cannot use the client certificate for TLS: {exc}") from exc
    finally:
        path.unlink()


def build_envelope(payload: etree._Element) -> etree._Element:
    """Wrap a payload element in a SOAP 1.1 envelope, as an element.

    Separate from `wrap_soap` because a WS-Security signature has to be
    applied to the envelope *before* it is serialised
    (`fiskalhr.core.wsse.sign_envelope_wsse`).
    """
    envelope = etree.Element(f"{{{SOAP_ENV_NS}}}Envelope", nsmap={"soapenv": SOAP_ENV_NS})
    body = etree.SubElement(envelope, f"{{{SOAP_ENV_NS}}}Body")
    body.append(payload)
    return envelope


def wrap_soap(payload: etree._Element) -> bytes:
    """Wrap a payload element in a SOAP 1.1 envelope."""
    return etree.tostring(build_envelope(payload), xml_declaration=True, encoding="UTF-8")


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
        url: Service endpoint (`fiskalhr.f1.service.SERVICE_URLS`).
        timeout: Per-request timeout in seconds.
        retries: Extra attempts after connection errors/timeouts only —
            never after an HTTP response was received.
        client_certificate: Certificate to present for 2-way TLS. Required by
            FINA's e-Račun services; the Tax Administration's services need
            none, and passing one there is harmless but pointless. Ignored
            when ``transport`` is set, since no TLS handshake happens then.
        transport: Optional httpx transport, injectable for testing
            (e.g. ``httpx.MockTransport`` or `fiskalhr.testing.MockCis`).
    """

    def __init__(
        self,
        url: str,
        *,
        timeout: float = _TIMEOUT,
        retries: int = _RETRIES,
        client_certificate: Certificate | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.url = url
        self.retries = retries
        self._client = httpx.Client(
            verify=_ssl_context(client_certificate) if transport is None else True,
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
        return unwrap_soap(self.post_envelope(wrap_soap(payload), soap_action=soap_action))

    def post_envelope(self, request_body: bytes, *, soap_action: str) -> bytes:
        """POST an already-serialised SOAP envelope; return the raw response.

        `call` wraps a payload and unwraps the answer, which is what the Tax
        Administration's services need. FINA's need the envelope signed
        before it goes out (`fiskalhr.core.wsse`), and re-wrapping would
        discard that header — so the signed bytes are posted as they are,
        through this same client and its TLS, timeout and retry policy.

        Raises:
            TransportError: If the service is unreachable after retries, or
                answers with an unexpected HTTP status and no body.
        """
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
            # CIS answers SOAP faults with HTTP 500, so a non-200 with a body
            # is handed back for parsing rather than treated as a failure.
            if response.status_code != 200 and not response.content:
                raise TransportError(
                    f"service answered HTTP {response.status_code} with an empty body"
                )
            return response.content

        raise TransportError(
            f"cannot reach {self.url} after {self.retries + 1} attempts: {last_error}"
        ) from last_error

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SoapClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
