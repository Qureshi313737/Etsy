"""One-time OAuth setup helpers (run on your own computer).

Flow: open the printed URL -> approve -> the browser is sent to your redirect URI.
If a local server can catch it (http://localhost:3003/callback) it is captured
automatically; otherwise paste the full redirected URL into the terminal.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

from . import etsy_client, pinterest_client

DEFAULT_REDIRECT = "http://localhost:3003/callback"


def pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def etsy_auth_url(api_key: str, redirect_uri: str, state: str, challenge: str) -> str:
    return etsy_client.AUTH_URL + "?" + urllib.parse.urlencode({
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": " ".join(etsy_client.SCOPES),
        "client_id": api_key,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })


def pinterest_auth_url(app_id: str, redirect_uri: str, state: str) -> str:
    return pinterest_client.AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": app_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": ",".join(pinterest_client.SCOPES),
        "state": state,
    })


def _capture_code(redirect_uri: str, state: str, timeout: int = 300) -> str:
    parsed = urllib.parse.urlparse(redirect_uri)
    result: dict[str, str] = {}

    if parsed.hostname in ("localhost", "127.0.0.1") and parsed.port:
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                result.update({k: v[0] for k, v in qs.items()})
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write("<h2>Done! Terminal par wapas jaiye.</h2>".encode())

            def log_message(self, *args):
                return

        try:
            server = HTTPServer((parsed.hostname, parsed.port), Handler)
            thread = threading.Thread(target=server.handle_request, daemon=True)
            thread.start()
            print(f"Waiting for the redirect on {redirect_uri} ... (or paste the URL below)")
            thread.join(timeout=timeout)
            server.server_close()
        except OSError:
            pass

    if "code" not in result:
        pasted = input("Paste the full URL your browser was redirected to: ").strip()
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(pasted).query)
        result.update({k: v[0] for k, v in qs.items()})

    if result.get("state") != state:
        raise RuntimeError("OAuth state mismatch - start again")
    if "code" not in result:
        raise RuntimeError(f"No authorization code returned: {result}")
    return result["code"]


def run_etsy_flow(api_key: str, redirect_uri: str = DEFAULT_REDIRECT) -> dict:
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(16)
    url = etsy_auth_url(api_key, redirect_uri, state, challenge)
    print("\nOpen this URL and click 'Allow access':\n\n" + url + "\n")
    webbrowser.open(url)
    code = _capture_code(redirect_uri, state)
    return etsy_client.EtsyClient.exchange_code(api_key, code, verifier, redirect_uri)


def run_pinterest_flow(app_id: str, app_secret: str, redirect_uri: str = DEFAULT_REDIRECT) -> dict:
    state = secrets.token_urlsafe(16)
    url = pinterest_auth_url(app_id, redirect_uri, state)
    print("\nOpen this URL and click 'Give access':\n\n" + url + "\n")
    webbrowser.open(url)
    code = _capture_code(redirect_uri, state)
    return pinterest_client.PinterestClient.exchange_code(app_id, app_secret, code, redirect_uri)
