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

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response

from .badge_renderer import generate_badge
from .cache import get_cached_badge, is_cache_valid, save_badge
from .config import CACHE_DIR, CACHE_MAX_AGE_HOURS, THM_USERNAME
from .scraper import fetch_user_profile

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
