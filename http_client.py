"""Shared HTTP helper: connection-reuse, retry only on transient errors."""

import os
import time
from typing import Optional

import requests

RETRY_ATTEMPTS = int(os.environ.get("RETRY_ATTEMPTS", "3"))
RETRY_DELAY = int(os.environ.get("RETRY_DELAY", "2"))

# Module-level Session reuses TCP connections across requests (P2).
_session = requests.Session()


def _is_transient(exc: Optional[requests.RequestException], response: Optional[requests.Response]) -> bool:
    """True only for connection/timeout/5xx errors — not 4xx (P3)."""
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True
    if response is not None and 500 <= response.status_code < 600:
        return True
    return False


def fetch_with_retry(url: str, timeout: int = 30) -> requests.Response:
    """GET a URL, retrying only on transient errors. Reuses a Session.

    Args:
        url: URL to fetch.
        timeout: Request timeout in seconds.

    Returns:
        The requests.Response on success.

    Raises:
        requests.RequestException on permanent failure or after exhausting retries.
    """
    last_exception: Optional[requests.RequestException] = None
    for attempt in range(RETRY_ATTEMPTS):
        try:
            response = _session.get(url, timeout=timeout)
            if 500 <= response.status_code < 600 and attempt < RETRY_ATTEMPTS - 1:
                time.sleep(RETRY_DELAY)
                continue
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_exception = exc
            if not _is_transient(exc, None) or attempt >= RETRY_ATTEMPTS - 1:
                raise
            time.sleep(RETRY_DELAY)
    raise last_exception  # pragma: no cover
