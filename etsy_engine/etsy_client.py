"""Etsy Open API v3 client (official API only - no scraping, which Etsy's terms forbid).

Auth model:
  * every request sends   x-api-key: <keystring>:<shared_secret>   (required since Feb 2026)
  * shop endpoints also send an OAuth2 bearer token (authorization code + PKCE flow)
"""
from __future__ import annotations

import logging
import time
from typing import Any, Iterator

from .http import ApiError, HttpClient
from .secrets_store import TokenStore

log = logging.getLogger(__name__)

API_BASE = "https://openapi.etsy.com/v3/application"
TOKEN_URL = "https://api.etsy.com/v3/public/oauth/token"
AUTH_URL = "https://www.etsy.com/oauth/connect"
SCOPES = ["listings_r", "listings_w", "shops_r", "transactions_r"]
BAD_RECEIPT_STATES = {"canceled", "fully refunded"}


def money(obj: Any) -> float:
    if isinstance(obj, dict):
        divisor = obj.get("divisor") or 100
        return round(float(obj.get("amount", 0)) / float(divisor), 2)
    try:
        return float(obj or 0)
    except (TypeError, ValueError):
        return 0.0


def normalize_listing(raw: dict) -> dict:
    images = sorted(raw.get("images") or [], key=lambda im: im.get("rank", 99))
    price = raw.get("price") or {}
    return {
        "listing_id": int(raw["listing_id"]),
        "shop_id": raw.get("shop_id"),
        "title": raw.get("title") or "",
        "description": raw.get("description") or "",
        "url": raw.get("url") or f"https://www.etsy.com/listing/{raw['listing_id']}",
        "price": money(price),
        "currency": price.get("currency_code", "USD") if isinstance(price, dict) else "USD",
        "quantity": raw.get("quantity") or 0,
        "tags": raw.get("tags") or [],
        "materials": raw.get("materials") or [],
        "image_urls": [im.get("url_fullxfull") or im.get("url_570xN") for im in images if im],
        "has_video": bool(raw.get("videos")),
        "taxonomy_id": raw.get("taxonomy_id"),
        "state": raw.get("state", "active"),
        "created_ts": raw.get("original_creation_timestamp") or raw.get("creation_timestamp") or 0,
        "updated_ts": raw.get("last_modified_timestamp") or raw.get("updated_timestamp") or 0,
        "views": raw.get("views") or 0,
        "num_favorers": raw.get("num_favorers") or 0,
    }


class EtsyClient:
    def __init__(self, api_key: str, shared_secret: str, store: TokenStore,
                 refresh_token_seed: str = "", shop_id: str | int | None = None, qps: float = 4.0):
        if not api_key or not shared_secret:
            raise ValueError("ETSY_API_KEY and ETSY_SHARED_SECRET are required")
        self.api_key = api_key
        self.shared_secret = shared_secret
        self.store = store
        self.refresh_token_seed = refresh_token_seed
        self._shop_id = int(shop_id) if shop_id else None
        self.http = HttpClient(qps=qps)

    # ---- auth --------------------------------------------------------------
    @property
    def key_header(self) -> dict[str, str]:
        return {"x-api-key": f"{self.api_key}:{self.shared_secret}"}

    @classmethod
    def exchange_code(cls, api_key: str, code: str, verifier: str, redirect_uri: str) -> dict:
        resp = HttpClient().request("POST", TOKEN_URL, data={
            "grant_type": "authorization_code",
            "client_id": api_key,
            "redirect_uri": redirect_uri,
            "code": code,
            "code_verifier": verifier,
        })
        return resp.json()

    def _refresh(self) -> str:
        saved = self.store.get("etsy")
        candidates = [t for t in (saved.get("refresh_token"), self.refresh_token_seed) if t]
        last_error: Exception | None = None
        for refresh_token in dict.fromkeys(candidates):  # de-duplicate, keep order
            try:
                resp = self.http.request("POST", TOKEN_URL, data={
                    "grant_type": "refresh_token",
                    "client_id": self.api_key,
                    "refresh_token": refresh_token,
                })
            except ApiError as exc:
                last_error = exc
                continue
            tok = resp.json()
            self.store.set("etsy", {
                "access_token": tok["access_token"],
                "refresh_token": tok.get("refresh_token", refresh_token),
                "expires_at": time.time() + int(tok.get("expires_in", 3600)) - 120,
            })
            return tok["access_token"]
        raise RuntimeError(
            "Etsy token refresh failed. Run `python -m etsy_engine auth etsy` again and update "
            f"ETSY_REFRESH_TOKEN. Last error: {last_error}"
        )

    def access_token(self) -> str:
        saved = self.store.get("etsy")
        if saved.get("access_token") and saved.get("expires_at", 0) > time.time():
            return saved["access_token"]
        return self._refresh()

    def _headers(self, auth: bool) -> dict[str, str]:
        headers = dict(self.key_header)
        if auth:
            headers["Authorization"] = f"Bearer {self.access_token()}"
        return headers

    def call(self, method: str, path: str, auth: bool = True, **kwargs: Any) -> Any:
        url = f"{API_BASE}{path}"
        try:
            resp = self.http.request(method, url, headers=self._headers(auth), **kwargs)
        except ApiError as exc:
            if exc.status == 401 and auth:  # token revoked/expired early: refresh once
                self.store.set("etsy", {"expires_at": 0})
                resp = self.http.request(method, url, headers=self._headers(auth), **kwargs)
            else:
                raise
        return resp.json() if resp.content else {}

    # ---- shop data -----------------------------------------------------------
    @property
    def shop_id(self) -> int:
        if self._shop_id is None:
            me = self.call("GET", "/users/me")
            if not me.get("shop_id"):
                raise RuntimeError("This Etsy account has no shop")
            self._shop_id = int(me["shop_id"])
        return self._shop_id

    def get_shop(self) -> dict:
        return self.call("GET", f"/shops/{self.shop_id}")

    def iter_active_listings(self) -> Iterator[dict]:
        offset = 0
        includes = "Images,Videos"
        while True:
            try:
                page = self.call("GET", f"/shops/{self.shop_id}/listings", params={
                    "state": "active", "limit": 100, "offset": offset, "includes": includes,
                })
            except ApiError as exc:
                if exc.status == 400 and includes != "Images":
                    includes = "Images"  # older API versions don't know the Videos include
                    continue
                raise
            results = page.get("results", [])
            for raw in results:
                yield normalize_listing(raw)
            offset += len(results)
            if not results or offset >= page.get("count", 0):
                break

    def iter_sales(self, min_created: int) -> Iterator[dict]:
        offset = 0
        while True:
            page = self.call("GET", f"/shops/{self.shop_id}/receipts", params={
                "min_created": min_created, "limit": 100, "offset": offset,
            })
            results = page.get("results", [])
            for receipt in results:
                if str(receipt.get("status", "")).lower() in BAD_RECEIPT_STATES:
                    continue
                for tx in receipt.get("transactions", []) or []:
                    if not tx.get("listing_id"):
                        continue
                    yield {
                        "transaction_id": int(tx["transaction_id"]),
                        "receipt_id": receipt.get("receipt_id"),
                        "listing_id": int(tx["listing_id"]),
                        "quantity": int(tx.get("quantity") or 1),
                        "price": money(tx.get("price")),
                        "created_ts": int(tx.get("created_timestamp") or receipt.get("created_timestamp") or 0),
                    }
            offset += len(results)
            if not results or offset >= page.get("count", 0):
                break

    def search_active_listings(self, keywords: str, limit: int = 100) -> dict:
        """Public marketplace search (API key only). Used for competitor research."""
        results: list[dict] = []
        count = 0
        offset = 0
        while len(results) < limit:
            page = self.call("GET", "/listings/active", auth=False, params={
                "keywords": keywords, "limit": min(100, limit - len(results)), "offset": offset,
                "sort_on": "score", "sort_order": "desc",
            })
            batch = page.get("results", [])
            count = page.get("count", count)
            results.extend(normalize_listing(r) for r in batch)
            offset += len(batch)
            if not batch or offset >= count:
                break
        return {"count": count, "results": results}

    def update_listing(self, listing_id: int, fields: dict[str, Any]) -> dict:
        """PATCH a listing, then verify Etsy stored the tags exactly (the docs describe the array
        both as string[] and as a comma-separated list, so fall back to a JSON body if needed)."""
        path = f"/shops/{self.shop_id}/listings/{listing_id}"
        data = {k: ",".join(v) if isinstance(v, (list, tuple)) else v for k, v in fields.items()}
        result = self.call("PATCH", path, data=data)
        wanted = [t.lower() for t in fields.get("tags", [])]
        if wanted and sorted(t.lower() for t in result.get("tags", [])) != sorted(wanted):
            log.info("Tags not stored as expected via form body - retrying as JSON")
            result = self.call("PATCH", path, json={"tags": list(fields["tags"])})
            if sorted(t.lower() for t in result.get("tags", [])) != sorted(wanted):
                raise ApiError(422, f"Etsy stored tags {result.get('tags')} instead of {wanted}")
        return result
