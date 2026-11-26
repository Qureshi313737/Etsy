"""Pinterest API v5 client.

Note on access tiers: apps start with *Trial* access, where Pins you create are visible
only to you (sandbox). Public Pins need *Standard* access (apply in the developer portal).
Until then the engine also publishes through the RSS feed and CSV bulk-upload channels.
"""
from __future__ import annotations

import base64
import logging
import time
from datetime import date
from typing import Any

from .http import ApiError, HttpClient
from .secrets_store import TokenStore

log = logging.getLogger(__name__)

API_BASE = "https://api.pinterest.com/v5"
SANDBOX_BASE = "https://api-sandbox.pinterest.com/v5"
AUTH_URL = "https://www.pinterest.com/oauth/"
TOKEN_URL = "https://api.pinterest.com/v5/oauth/token"
SCOPES = ["boards:read", "boards:write", "pins:read", "pins:write", "user_accounts:read"]


class PinterestClient:
    def __init__(self, app_id: str, app_secret: str, store: TokenStore,
                 refresh_token_seed: str = "", access_token: str = "", sandbox: bool = False):
        self.app_id = app_id
        self.app_secret = app_secret
        self.store = store
        self.refresh_token_seed = refresh_token_seed
        self.static_access_token = access_token
        self.base = SANDBOX_BASE if sandbox else API_BASE
        self.http = HttpClient(qps=2.0)
        self._boards: dict[str, str] | None = None

    # ---- auth ------------------------------------------------------------------
    @staticmethod
    def _basic(app_id: str, app_secret: str) -> dict[str, str]:
        token = base64.b64encode(f"{app_id}:{app_secret}".encode()).decode()
        return {"Authorization": f"Basic {token}"}

    @classmethod
    def exchange_code(cls, app_id: str, app_secret: str, code: str, redirect_uri: str) -> dict:
        resp = HttpClient().request("POST", TOKEN_URL, headers=cls._basic(app_id, app_secret), data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "continuous_refresh": "true",
        })
        return resp.json()

    def _refresh(self) -> str:
        saved = self.store.get("pinterest")
        candidates = [t for t in (saved.get("refresh_token"), self.refresh_token_seed) if t]
        last_error: Exception | None = None
        for refresh_token in dict.fromkeys(candidates):
            try:
                resp = self.http.request("POST", TOKEN_URL, headers=self._basic(self.app_id, self.app_secret),
                                         data={"grant_type": "refresh_token", "refresh_token": refresh_token})
            except ApiError as exc:
                last_error = exc
                continue
            tok = resp.json()
            self.store.set("pinterest", {
                "access_token": tok["access_token"],
                "refresh_token": tok.get("refresh_token", refresh_token),
                "expires_at": time.time() + int(tok.get("expires_in", 2592000)) - 3600,
            })
            return tok["access_token"]
        if self.static_access_token:
            return self.static_access_token
        raise RuntimeError(f"Pinterest token refresh failed: {last_error}")

    def access_token(self) -> str:
        saved = self.store.get("pinterest")
        if saved.get("access_token") and saved.get("expires_at", 0) > time.time():
            return saved["access_token"]
        if not (self.refresh_token_seed or saved.get("refresh_token")) and self.static_access_token:
            return self.static_access_token
        return self._refresh()

    def call(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = {"Authorization": f"Bearer {self.access_token()}"}
        resp = self.http.request(method, f"{self.base}{path}", headers=headers, **kwargs)
        return resp.json() if resp.content else {}

    # ---- account / boards --------------------------------------------------------
    def user_account(self) -> dict:
        return self.call("GET", "/user_account")

    def boards(self) -> dict[str, str]:
        if self._boards is None:
            self._boards = {}
            bookmark = None
            while True:
                params = {"page_size": 100}
                if bookmark:
                    params["bookmark"] = bookmark
                page = self.call("GET", "/boards", params=params)
                for b in page.get("items", []):
                    self._boards[b["name"].strip().lower()] = b["id"]
                bookmark = page.get("bookmark")
                if not bookmark:
                    break
        return self._boards

    def board_id(self, name: str, create: bool = True) -> str:
        boards = self.boards()
        key = name.strip().lower()
        if key not in boards and create:
            created = self.call("POST", "/boards", json={
                "name": name.strip()[:180],
                "description": f"{name.strip()} - handpicked finds",
                "privacy": "PUBLIC",
            })
            boards[key] = created["id"]
        return boards[key]

    # ---- pins --------------------------------------------------------------------
    def create_pin(self, board_id: str, title: str, description: str, link: str,
                   alt_text: str, image_bytes: bytes, content_type: str = "image/jpeg") -> dict:
        return self.call("POST", "/pins", json={
            "board_id": board_id,
            "title": title[:100],
            "description": description[:800],
            "link": link,
            "alt_text": alt_text[:500],
            "media_source": {
                "source_type": "image_base64",
                "content_type": content_type,
                "data": base64.b64encode(image_bytes).decode(),
            },
        })

    def pin_analytics(self, pin_id: str, start: date, end: date) -> dict[str, int]:
        data = self.call("GET", f"/pins/{pin_id}/analytics", params={
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "metric_types": "IMPRESSION,SAVE,PIN_CLICK,OUTBOUND_CLICK",
            "app_types": "ALL",
        })
        summary = (data.get("all") or {}).get("summary_metrics") or {}
        return {
            "impressions": int(summary.get("IMPRESSION", 0) or 0),
            "saves": int(summary.get("SAVE", 0) or 0),
            "pin_clicks": int(summary.get("PIN_CLICK", 0) or 0),
            "outbound_clicks": int(summary.get("OUTBOUND_CLICK", 0) or 0),
        }

    def trending_keywords(self, region: str = "US", trend_type: str = "growing", limit: int = 20) -> list[str]:
        data = self.call("GET", f"/trends/keywords/{region}/top/{trend_type}", params={"limit": limit})
        return [t.get("keyword", "") for t in data.get("trends", []) if t.get("keyword")]
