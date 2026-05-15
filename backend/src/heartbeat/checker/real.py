import socket
import ssl
import time

import httpx

from heartbeat.checker import CheckOutcome, ErrorCategory
from heartbeat.models.endpoint import Endpoint


class RealChecker:
    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._client = http_client

    async def check(self, endpoint: Endpoint) -> CheckOutcome:
        start = time.monotonic()
        try:
            response = await self._client.get(
                endpoint.url,
                timeout=endpoint.timeout_seconds,
            )
            latency_ms = int((time.monotonic() - start) * 1000)
            if 200 <= response.status_code < 300:
                return CheckOutcome(
                    outcome="success",
                    latency_ms=latency_ms,
                    status_code=response.status_code,
                    error_category=None,
                    error_message=None,
                )
            return CheckOutcome(
                outcome="failure",
                latency_ms=latency_ms,
                status_code=response.status_code,
                error_category=ErrorCategory.non_2xx,
                error_message=f"HTTP {response.status_code}",
            )
        except httpx.TimeoutException as e:
            latency_ms = int((time.monotonic() - start) * 1000)
            return CheckOutcome(
                outcome="failure",
                latency_ms=latency_ms,
                status_code=None,
                error_category=ErrorCategory.timeout,
                error_message=str(e) or "Request timed out",
            )
        except httpx.ConnectError as e:
            latency_ms = int((time.monotonic() - start) * 1000)
            cause = e.__cause__
            msg = str(e).lower()
            if isinstance(cause, ssl.SSLError) or any(
                k in msg for k in ("ssl", "tls", "certificate")
            ):
                category = ErrorCategory.tls
            elif isinstance(cause, socket.gaierror) or any(
                k in msg for k in ("getaddrinfo", "name or service", "nodename", "name resolution")
            ):
                category = ErrorCategory.dns
            else:
                category = ErrorCategory.connection_refused
            return CheckOutcome(
                outcome="failure",
                latency_ms=latency_ms,
                status_code=None,
                error_category=category,
                error_message=str(e) or "Connection error",
            )
        except httpx.HTTPError as e:
            latency_ms = int((time.monotonic() - start) * 1000)
            return CheckOutcome(
                outcome="failure",
                latency_ms=latency_ms,
                status_code=None,
                error_category=ErrorCategory.other,
                error_message=str(e) or "HTTP error",
            )
