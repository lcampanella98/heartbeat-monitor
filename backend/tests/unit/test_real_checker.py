import socket
import ssl
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from heartbeat.checker import ErrorCategory
from heartbeat.checker.real import RealChecker

_REQ = httpx.Request("GET", "http://example.com")


class _FakeEndpoint:
    url = "http://example.com"
    timeout_seconds = 10


class _StubResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


def _make_checker(*, response=None, exc=None) -> RealChecker:
    client = MagicMock()
    client.get = AsyncMock(return_value=response) if exc is None else AsyncMock(side_effect=exc)
    return RealChecker(http_client=client)


async def test_success_2xx():
    outcome = await _make_checker(response=_StubResponse(200)).check(_FakeEndpoint())
    assert outcome.outcome == "success"
    assert outcome.status_code == 200
    assert outcome.error_category is None
    assert outcome.error_message is None
    assert outcome.latency_ms >= 0


async def test_non_2xx_maps_to_failure():
    outcome = await _make_checker(response=_StubResponse(503)).check(_FakeEndpoint())
    assert outcome.outcome == "failure"
    assert outcome.status_code == 503
    assert outcome.error_category == ErrorCategory.non_2xx


async def test_404_maps_to_non_2xx():
    outcome = await _make_checker(response=_StubResponse(404)).check(_FakeEndpoint())
    assert outcome.error_category == ErrorCategory.non_2xx


async def test_201_is_success():
    outcome = await _make_checker(response=_StubResponse(201)).check(_FakeEndpoint())
    assert outcome.outcome == "success"


async def test_timeout_maps_to_timeout():
    outcome = await _make_checker(
        exc=httpx.ReadTimeout("timed out", request=_REQ)
    ).check(_FakeEndpoint())
    assert outcome.outcome == "failure"
    assert outcome.error_category == ErrorCategory.timeout
    assert outcome.status_code is None


async def test_connect_timeout_maps_to_timeout():
    outcome = await _make_checker(
        exc=httpx.ConnectTimeout("connect timed out", request=_REQ)
    ).check(_FakeEndpoint())
    assert outcome.outcome == "failure"
    assert outcome.error_category == ErrorCategory.timeout


async def test_connection_refused():
    outcome = await _make_checker(
        exc=httpx.ConnectError("Connection refused", request=_REQ)
    ).check(_FakeEndpoint())
    assert outcome.outcome == "failure"
    assert outcome.error_category == ErrorCategory.connection_refused


async def test_dns_error_by_message():
    outcome = await _make_checker(
        exc=httpx.ConnectError("getaddrinfo failed", request=_REQ)
    ).check(_FakeEndpoint())
    assert outcome.outcome == "failure"
    assert outcome.error_category == ErrorCategory.dns


async def test_dns_error_by_cause():
    exc = httpx.ConnectError("", request=_REQ)
    exc.__cause__ = socket.gaierror(socket.EAI_NONAME, "Name or service not known")
    outcome = await _make_checker(exc=exc).check(_FakeEndpoint())
    assert outcome.outcome == "failure"
    assert outcome.error_category == ErrorCategory.dns


async def test_tls_error_by_message():
    outcome = await _make_checker(
        exc=httpx.ConnectError("SSL certificate verify failed", request=_REQ)
    ).check(_FakeEndpoint())
    assert outcome.outcome == "failure"
    assert outcome.error_category == ErrorCategory.tls


async def test_tls_error_by_cause():
    exc = httpx.ConnectError("", request=_REQ)
    exc.__cause__ = ssl.SSLError("CERTIFICATE_VERIFY_FAILED")
    outcome = await _make_checker(exc=exc).check(_FakeEndpoint())
    assert outcome.outcome == "failure"
    assert outcome.error_category == ErrorCategory.tls


@pytest.mark.parametrize("keyword", ["ssl", "tls", "certificate"])
async def test_tls_keywords(keyword: str):
    outcome = await _make_checker(
        exc=httpx.ConnectError(f"error: {keyword} handshake", request=_REQ)
    ).check(_FakeEndpoint())
    assert outcome.error_category == ErrorCategory.tls


async def test_other_http_error():
    outcome = await _make_checker(
        exc=httpx.RemoteProtocolError("protocol error", request=_REQ)
    ).check(_FakeEndpoint())
    assert outcome.outcome == "failure"
    assert outcome.error_category == ErrorCategory.other
