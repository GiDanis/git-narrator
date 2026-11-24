"""Zero-bloat async HTTPX engine, retry helper, and unified streaming transport."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = httpx.Timeout(
    timeout=90.0,
    connect=10.0,
    read=90.0,
    write=10.0,
    pool=10.0,
)

RETRYABLE_STATUS_CODES = {429, 502, 503, 504}


class TransportError(Exception):
    """Base exception for transport and networking failures."""


class HTTPStatusError(TransportError):
    """Raised when an HTTP response indicates a non-successful status code."""

    def __init__(self, status_code: int, message: str, url: str = ""):
        super().__init__(f"HTTP {status_code} error from {url}: {message}")
        self.status_code = status_code
        self.message = message
        self.url = url


class StreamTimeoutError(TransportError):
    """Raised when an active stream times out."""


def extract_error_detail(raw_body: str) -> str:
    """Extract concise human-readable error message from API JSON or raw text."""
    try:
        parsed = json.loads(raw_body)
        if isinstance(parsed, dict):
            err = parsed.get("error")
            if isinstance(err, dict):
                msg = err.get("message") or err.get("status")
                if msg:
                    return str(msg)
            elif isinstance(err, str):
                return err
            if "message" in parsed:
                return str(parsed["message"])
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return raw_body.strip() or "<Empty error body>"


def create_http_client(
    timeout: float | httpx.Timeout | None = None,
    limits: httpx.Limits | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.AsyncClient:
    """Create an AsyncClient configured for reliable LLM streaming."""
    if timeout is None:
        client_timeout = DEFAULT_TIMEOUT
    elif isinstance(timeout, (int, float)):
        client_timeout = httpx.Timeout(
            timeout=float(timeout),
            connect=10.0,
            read=float(timeout),
            write=10.0,
            pool=10.0,
        )
    else:
        client_timeout = timeout

    client_limits = limits or httpx.Limits(max_keepalive_connections=20, max_connections=50)

    return httpx.AsyncClient(
        timeout=client_timeout,
        limits=client_limits,
        transport=transport,
        follow_redirects=True,
    )


async def send_streaming_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json_payload: dict[str, Any] | None = None,
    max_retries: int = 2,
) -> httpx.Response:
    """Send streaming request with bounded retries on transient rate limits / network hiccups."""
    last_exc: Exception | None = None

    for attempt in range(max_retries + 1):
        request = client.build_request(
            method=method,
            url=url,
            headers=headers,
            params=params,
            json=json_payload,
        )
        try:
            response = await client.send(request, stream=True)
        except (httpx.ConnectError, httpx.ReadTimeout) as exc:
            last_exc = exc
            if attempt < max_retries:
                await asyncio.sleep(0.5 * (2**attempt))
                continue
            raise TransportError(f"Network error contacting {url}: {exc}") from exc
        except httpx.HTTPError as exc:
            raise TransportError(f"HTTP error contacting {url}: {exc}") from exc

        if response.status_code in RETRYABLE_STATUS_CODES and attempt < max_retries:
            await response.aclose()
            await asyncio.sleep(0.6 * (2**attempt))
            continue

        return response

    raise TransportError(f"Request failed after retries: {last_exc}")


async def check_response_status(response: httpx.Response) -> None:
    """Check if HTTP response is successful, reading error body if failed."""
    if not response.is_success:
        try:
            raw_text = (await response.aread()).decode("utf-8", errors="replace")
            error_text = extract_error_detail(raw_text)
        except (UnicodeDecodeError, httpx.HTTPError, OSError):
            error_text = "<Failed to read response body>"
        raise HTTPStatusError(
            status_code=response.status_code,
            message=error_text,
            url=str(response.url),
        )


async def aiter_sse_data(
    response: httpx.Response,
    stop_sentinel: str = "[DONE]",
) -> AsyncIterator[str]:
    """Unified Server-Sent Events (SSE) data stream reader."""
    await check_response_status(response)

    current_data_lines: list[str] = []

    try:
        async for raw_line in response.aiter_lines():
            line = raw_line.strip("\r")

            if not line:
                if current_data_lines:
                    combined = "\n".join(current_data_lines)
                    current_data_lines.clear()
                    if combined.strip() == stop_sentinel:
                        return
                    yield combined
                continue

            if line.startswith(":"):
                continue

            if line.startswith("data:"):
                payload = line[5:].lstrip()
                if payload == stop_sentinel:
                    return
                current_data_lines.append(payload)

        if current_data_lines:
            combined = "\n".join(current_data_lines)
            if combined.strip() != stop_sentinel:
                yield combined

    except httpx.TimeoutException as err:
        raise StreamTimeoutError(f"Stream timed out: {err}") from err
    except httpx.HTTPError as err:
        raise TransportError(f"HTTP streaming error: {err}") from err


async def aiter_ndjson_lines(response: httpx.Response) -> AsyncIterator[str]:
    """Unified newline-delimited JSON (NDJSON) streaming reader."""
    await check_response_status(response)

    try:
        async for line in response.aiter_lines():
            cleaned = line.strip()
            if cleaned:
                yield cleaned
    except httpx.TimeoutException as err:
        raise StreamTimeoutError(f"NDJSON stream timed out: {err}") from err
    except httpx.HTTPError as err:
        raise TransportError(f"HTTP streaming error: {err}") from err
