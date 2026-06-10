"""
FastAPI application — entry point.

Single public endpoint
----------------------
GET /badge.png
    Returns a freshly rendered TryHackMe profile badge as a PNG image.

Request flow
------------
1. Validate that THM_USERNAME is configured.
2. Return the cached badge immediately if it is still fresh.
3. Scrape the TryHackMe profile, render a new PNG via Pillow, and save it.
4. On scraping/rendering failure, fall back to the stale cached badge (if any).
5. If no badge is available at all, return a JSON 503 error.

Additional endpoint
-------------------
GET /health  — liveness check (returns JSON {"status": "ok"}).
"""
from __future__ import annotations

import logging
import traceback

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, Response

from .badge_renderer import generate_badge
from .cache import get_cached_badge, is_cache_valid, save_badge
from .config import CACHE_DIR, CACHE_MAX_AGE_HOURS, THM_USERNAME
from .scraper import _HEADERS, _IMPERSONATE, _TIMEOUT, fetch_user_profile

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="TryHackMe Dynamic Badge",
    description="Generates and serves a live PNG badge for a TryHackMe profile.",
    version="1.0.0",
)


@app.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    """Landing page — lets Render (and any browser) confirm the service is up."""
    return HTMLResponse(content="""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>TryHackMe Dynamic Badge</title></head>
<body>
  <h1>TryHackMe Dynamic Badge</h1>
  <p>Service opérationnel.</p>
  <p><a href="/badge.png">badge.png</a> &mdash; <a href="/health">health</a></p>
</body>
</html>""")


@app.get("/badge.png", response_class=Response)
async def get_badge() -> Response:
    """
    Return the TryHackMe profile badge as a PNG image.

    HTTP responses:
        200  image/png  — badge (fresh or cached)
        500  JSON       — THM_USERNAME env var is not set
        503  JSON       — scraping failed and no cache is available
    """
    # ── Pre-flight: verify configuration ─────────────────────────────────
    if not THM_USERNAME:
        logger.error("THM_USERNAME is not configured.")
        return JSONResponse(
            status_code=500,
            content={
                "error": "Server misconfiguration: THM_USERNAME environment variable is not set."
            },
        )

    # ── Cache hit: return immediately ─────────────────────────────────────
    if is_cache_valid(CACHE_DIR, CACHE_MAX_AGE_HOURS):
        logger.info("Returning cached badge for '%s'.", THM_USERNAME)
        cached = get_cached_badge(CACHE_DIR)
        if cached:
            return Response(content=cached, media_type="image/png")

    # ── Fresh fetch ───────────────────────────────────────────────────────────
    fetch_error: Exception | None = None
    try:
        logger.info("Scraping TryHackMe profile for '%s'…", THM_USERNAME)
        profile = fetch_user_profile(THM_USERNAME)
        logger.info(
            "Profile: rank=%s top=%s%% badges=%s streak=%s rooms=%s cap=%s",
            profile.rank, profile.top_percentage, profile.badge_count,
            profile.streak, profile.completed_rooms, profile.capability_score,
        )
        image_bytes = generate_badge(profile)
        save_badge(CACHE_DIR, image_bytes, profile=profile)
        return Response(content=image_bytes, media_type="image/png")
    except Exception as exc:
        logger.error("Badge fetch failed: %s", exc, exc_info=True)
        fetch_error = exc

    # ── Stale-cache fallback ──────────────────────────────────────────────────
    stale = get_cached_badge(CACHE_DIR)
    if stale:
        logger.warning(
            "Returning stale cached badge for '%s' (reason: %s).",
            THM_USERNAME,
            fetch_error,
        )
        return Response(content=stale, media_type="image/png")

    # ── Total failure ─────────────────────────────────────────────────────────
    return JSONResponse(
        status_code=503,
        content={
            "error": "Unable to fetch the TryHackMe badge and no cached badge exists.",
            "detail": str(fetch_error),
        },
    )


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Liveness / readiness probe endpoint."""
    return {"status": "ok", "username": THM_USERNAME or "(not configured)"}


@app.get("/debug/thm")
async def debug_thm() -> dict:
    """
    Diagnostic endpoint — attempts a raw HTTP call to each TryHackMe
    endpoint and returns full details (status code, headers, body excerpt,
    errors) so cloud-platform failures can be diagnosed without a local
    repro.  Does NOT hit the badge cache.
    """
    from curl_cffi import requests as creq  # local import to keep scope clean

    username = THM_USERNAME or "Cronix3"
    endpoints = [
        f"https://tryhackme.com/api/v2/public-profile?username={username}",
        f"https://tryhackme.com/api/discord/user/{username}",
    ]

    results = []
    for url in endpoints:
        entry: dict = {"url": url}
        try:
            resp = creq.get(
                url,
                headers=_HEADERS,
                impersonate=_IMPERSONATE,
                timeout=_TIMEOUT,
            )
            diag_headers = {
                k: v for k, v in resp.headers.items()
                if k.lower() in {
                    "content-type", "cf-ray", "cf-cache-status", "server",
                    "x-vercel-id", "x-vercel-cache", "location",
                    "set-cookie", "www-authenticate", "x-ratelimit-limit",
                }
            }
            try:
                body_json = resp.json()
                body_repr = body_json
            except Exception:
                body_repr = resp.text[:500]

            entry.update({
                "status_code": resp.status_code,
                "final_url": str(resp.url),
                "content_length": len(resp.content),
                "diag_headers": diag_headers,
                "body_preview": body_repr,
                "error": None,
            })
        except Exception as exc:
            entry.update({
                "status_code": None,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            })
        results.append(entry)

    # Also try to build a full profile to see if the whole pipeline works.
    profile_summary: dict = {}
    try:
        profile = fetch_user_profile(username)
        profile_summary = {
            "ok": True,
            "rank": profile.rank,
            "top_percentage": profile.top_percentage,
            "streak": profile.streak,
            "badge_count": profile.badge_count,
            "completed_rooms": profile.completed_rooms,
            "capability_score": profile.capability_score,
            "total_points": profile.total_points,
            "level": profile.level,
            "level_label": profile.level_label,
        }
    except Exception as exc:
        profile_summary = {"ok": False, "error": str(exc)}

    return {
        "configured_username": username,
        "impersonate": _IMPERSONATE,
        "timeout": _TIMEOUT,
        "endpoints": results,
        "pipeline": profile_summary,
    }
