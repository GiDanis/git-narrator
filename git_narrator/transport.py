"""Zero-bloat async HTTPX engine and unified streaming transport."""

import logging
from typing import AsyncIterator, Optional
import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = httpx.Timeout(
    timeout=90.0,
    connect=10.0,
    read=90.0,
    write=10.0,
    pool=10.0,
)


class TransportError(Exception):
    """Base exception for transport and networking failures."""
    pass


class HTTPStatusError(TransportError):
    """Raised when an HTTP response indicates a non-successful status code."""
    def __init__(self, status_code: int, message: str, url: str = ""):
        super().__init__(f"HTTP {status_code} error from {url}: {message}")
        self.status_code = status_code
        self.message = message
        self.url = url


class StreamTimeoutError(TransportError):
    """Raised when an active stream times out."""
    pass


def create_http_client(
    timeout: Optional[float | httpx.Timeout] = None,
    limits: Optional[httpx.Limits] = None,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> httpx.AsyncClient:
    """Create an AsyncClient configured for reliable LLM streaming.

    Args:
        timeout: Timeout in seconds or httpx.Timeout object.
        limits: Optional connection pool limits.
        transport: Optional custom transport (e.g. httpx.MockTransport for tests).

    Returns:
        Configured httpx.AsyncClient instance.
    """
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


async def check_response_status(response: httpx.Response) -> None:
    """Check if HTTP response is successful, reading error body if failed."""
    if not response.is_success:
        try:
            error_text = (await response.aread()).decode("utf-8", errors="replace")
        except Exception:
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
    """Unified Server-Sent Events (SSE) data stream reader.

    Reads `aiter_lines()` from an active streaming response, yields the payload
    of lines starting with 'data: ', handles multi-line blocks, and terminates cleanly
    on `stop_sentinel` or stream completion.

    Args:
        response: Streaming httpx.Response object.
        stop_sentinel: String indicating the end of the SSE stream (e.g. '[DONE]').

    Yields:
        Extracted data payloads.
    """
    await check_response_status(response)

    current_data_lines: list[str] = []

    try:
        async for line in response.aiter_lines():
            line = line.strip("\r")

            # SSE comment or empty line
            if not line:
                if current_data_lines:
                    combined = "\n".join(current_data_lines)
                    current_data_lines.clear()
                    if combined.strip() == stop_sentinel:
                        return
                    yield combined
                continue

            if line.startswith(":"):
                # Comment line, ignore
                continue

            if line.startswith("data:"):
                payload = line[5:].lstrip()
                if payload == stop_sentinel:
                    return
                current_data_lines.append(payload)

        # Flush any remaining buffer at end of stream
        if current_data_lines:
            combined = "\n".join(current_data_lines)
            if combined.strip() != stop_sentinel:
                yield combined

    except httpx.TimeoutException as err:
        raise StreamTimeoutError(f"Stream timed out: {err}") from err
    except httpx.HTTPError as err:
        raise TransportError(f"HTTP streaming error: {err}") from err


async def aiter_ndjson_lines(response: httpx.Response) -> AsyncIterator[str]:
    """Unified newline-delimited JSON (NDJSON) streaming reader.

    Used by local Ollama API (`/api/chat`) and line-based streaming protocols.

    Args:
        response: Streaming httpx.Response object.

    Yields:
        Each non-empty JSON line string.
    """
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
