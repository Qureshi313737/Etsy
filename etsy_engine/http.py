"""Shared HTTP helper: retries with backoff, Retry-After support and a simple QPS throttle."""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

import requests

log = logging.getLogger(__name__)

USER_AGENT = "etsy-growth-engine/1.0"


class ApiError(RuntimeError):
    def __init__(self, status: int, message: str, payload: Any = None):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.payload = payload


class HttpClient:
    def __init__(self, qps: float = 4.0, timeout: float = 30.0, max_retries: int = 4):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.min_interval = 1.0 / qps if qps > 0 else 0.0
        self.timeout = timeout
        self.max_retries = max_retries
        self._last = 0.0
        self._lock = threading.Lock()
        self.calls = 0

    def _throttle(self) -> None:
        with self._lock:
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", self.timeout)
        attempt = 0
        while True:
            self._throttle()
            self.calls += 1
            try:
                resp = self.session.request(method, url, **kwargs)
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt >= self.max_retries:
                    raise ApiError(0, f"network error: {exc}") from exc
                attempt += 1
                time.sleep(min(2 ** attempt, 30))
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt >= self.max_retries:
                    break
                attempt += 1
                retry_after = resp.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else min(2 ** attempt, 60)
                log.info("%s %s -> %s, retrying in %.0fs", method, url, resp.status_code, delay)
                time.sleep(delay)
                continue
            break
        if resp.status_code >= 400:
            try:
                payload = resp.json()
            except ValueError:
                payload = resp.text[:500]
            raise ApiError(resp.status_code, str(payload)[:500], payload)
        return resp
