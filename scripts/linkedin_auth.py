"""One-time local OAuth helper: prints a LinkedIn access token to store as a GitHub secret.

Usage (on your own computer):
    set LINKEDIN_CLIENT_ID=...        (PowerShell: $env:LINKEDIN_CLIENT_ID="...")
    set LINKEDIN_CLIENT_SECRET=...
    python scripts/linkedin_auth.py

Add http://localhost:8765/callback as an Authorized redirect URL in your LinkedIn app's Auth tab first.
"""
from __future__ import annotations

import os
import secrets
import sys
import webbrowser
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import requests

PORT = 8765
REDIRECT_URI = f"http://localhost:{PORT}/callback"
SCOPES = "openid profile w_member_social"
AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"


def main() -> None:
    client_id = os.environ.get("LINKEDIN_CLIENT_ID", "").strip()
    client_secret = os.environ.get("LINKEDIN_CLIENT_SECRET", "").strip()
    if not (client_id and client_secret):
        sys.exit("Set LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET environment variables first.")

    state = secrets.token_urlsafe(16)
    result: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            query = parse_qs(urlparse(self.path).query)
            if query.get("state", [""])[0] != state:
                result["error"] = "state mismatch"
            elif "error" in query:
                result["error"] = query.get("error_description", query["error"])[0]
            else:
                result["code"] = query.get("code", [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Done. You can close this tab and return to the terminal.")

        def log_message(self, *args: object) -> None:
            pass

    url = AUTH_URL + "?" + urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "state": state,
        "scope": SCOPES,
    })
    print("Opening LinkedIn in your browser. If it doesn't open, visit:\n" + url)
    webbrowser.open(url)
    server = HTTPServer(("localhost", PORT), Handler)
    while not result:
        server.handle_request()
    if "error" in result:
        sys.exit(f"Authorization failed: {result['error']}")

    resp = requests.post(TOKEN_URL, data={
        "grant_type": "authorization_code",
        "code": result["code"],
        "redirect_uri": REDIRECT_URI,
        "client_id": client_id,
        "client_secret": client_secret,
    }, timeout=30)
    resp.raise_for_status()
    token = resp.json()
    sub = requests.get(
        "https://api.linkedin.com/v2/userinfo",
        headers={"Authorization": f"Bearer {token['access_token']}"},
        timeout=30,
    ).json().get("sub", "?")

    print("\nSuccess. Store these as GitHub Actions secrets:\n")
    print(f"LINKEDIN_ACCESS_TOKEN = {token['access_token']}")
    print(f"LINKEDIN_TOKEN_ISSUED = {date.today().isoformat()}")
    print(f"\n(expires in ~{int(token.get('expires_in', 0)) // 86400} days; person URN: urn:li:person:{sub})")


if __name__ == "__main__":
    main()
