"""HTTP helper with timeouts and retry/backoff for every external call."""
from __future__ import annotations

import logging
import time
from typing import Any

import requests

from src.config import HTTP_TIMEOUT

log = logging.getLogger(__name__)

USER_AGENT = "AutoLinkediner/1.0 (+https://github.com/kneat2448/AutoLinkediner)"
RETRY_STATUS = {429, 500, 502, 503, 504}


def request(
    method: str,
    url: str,
    *,
    retries: int = 3,
    backoff: float = 2.0,
    timeout: float = HTTP_TIMEOUT,
    **kwargs: Any,
) -> requests.Response:
    """Make an HTTP request, retrying on network errors and 429/5xx with exponential backoff.

    Raises ``requests.HTTPError`` for a final non-2xx response.
    """
    headers = {"User-Agent": USER_AGENT, **kwargs.pop("headers", {})}
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            resp = requests.request(method, url, headers=headers, timeout=timeout, **kwargs)
            if resp.status_code in RETRY_STATUS and attempt < retries - 1:
                wait = backoff * (2 ** attempt)
                retry_after = resp.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    wait = max(wait, min(int(retry_after), 60))
                log.warning("HTTP %s from %s, retrying in %.0fs", resp.status_code, _host(url), wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
            if attempt < retries - 1:
                wait = backoff * (2 ** attempt)
                log.warning("%s on %s, retrying in %.0fs", type(exc).__name__, _host(url), wait)
                time.sleep(wait)
    assert last_exc is not None
    raise last_exc


def get(url: str, **kwargs: Any) -> requests.Response:
    return request("GET", url, **kwargs)


def post(url: str, **kwargs: Any) -> requests.Response:
    return request("POST", url, **kwargs)


def _host(url: str) -> str:
    """Host only, so tokens embedded in URL paths (e.g. Telegram) never reach the logs."""
    return url.split("/")[2] if "://" in url else url
