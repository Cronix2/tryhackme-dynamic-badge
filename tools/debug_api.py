"""Print raw API responses for both endpoints (debug helper)."""
from __future__ import annotations

import json
import sys

from curl_cffi import requests as creq

USERNAME = sys.argv[1] if len(sys.argv) > 1 else "Cronix3"

ENDPOINTS = [
    f"https://tryhackme.com/api/v2/public-profile?username={USERNAME}",
    f"https://tryhackme.com/api/discord/user/{USERNAME}",
]

for url in ENDPOINTS:
    print("=" * 70)
    print("GET", url)
    try:
        resp = creq.get(
            url,
            headers={
                "Accept": "application/json",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://tryhackme.com/",
            },
            impersonate="chrome",
            timeout=20,
        )
    except Exception as exc:
        print("ERROR:", exc)
        continue
    print("status", resp.status_code, "ctype", resp.headers.get("Content-Type"))
    try:
        body = resp.json()
        print(json.dumps(body, indent=2, ensure_ascii=False))
    except Exception:
        print(resp.text[:2000])
