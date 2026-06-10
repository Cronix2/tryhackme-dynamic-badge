"""
TryHackMe profile scraper.

Bypasses TryHackMe's Vercel/Cloudflare bot-protection by using `curl_cffi`,
which performs a real Chrome TLS handshake (JA3 fingerprint) and HTTP/2
frame ordering. Standard `requests` is blocked with HTTP 429.

Primary data source
-------------------
GET https://tryhackme.com/api/v2/public-profile?username={username}

This single endpoint returns every field needed for the badge:
    avatar, username, level, rank, topPercentage, streak,
    badgesNumber, completedRoomsNumber, capabilityScore, leagueTier,
    shouldShowCrown (Legend tier indicator).

Fallback
--------
GET https://tryhackme.com/api/discord/user/{username}

Returns a minimal subset (points, avatar, userRank) when the v2 endpoint
is unavailable. Used to populate any missing UserProfile fields.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from curl_cffi import requests as creq

logger = logging.getLogger(__name__)

_BASE = "https://tryhackme.com"
_V2_PROFILE = _BASE + "/api/v2/public-profile?username={username}"
_DISCORD_API = _BASE + "/api/discord/user/{username}"

_TIMEOUT = 20
_IMPERSONATE = "chrome"  # spoofs Chrome's TLS + HTTP/2 fingerprint

_HEADERS: dict[str, str] = {
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": _BASE + "/",
}


# ---------------------------------------------------------------------------
# Level table
# ---------------------------------------------------------------------------
# TryHackMe levels are derived from total experience points. Ordered from
# highest to lowest so the first match wins when iterating.
# (level_int, label, threshold_points, next_threshold)
LEVEL_TABLE: list[tuple[int, str, int]] = [
    (0x15, "GRANDMASTER", 150_000),
    (0x14, "MYTHIC",      130_000),
    (0x13, "ASCENDED",    110_000),
    (0x12, "SHOGUN",       95_000),
    (0x11, "VANGUARD",     80_000),
    (0x10, "SAGE",         65_000),
    (0x0F, "TITAN",        50_000),
    (0x0E, "Guardian",     35_000),
    (0x0D, "Legend",       20_000),
    (0x0C, "Guru",         17_000),
    (0x0B, "Master",       15_000),
    (0x0A, "Wizard",       12_000),
    (0x09, "Mage",          8_000),
    (0x08, "Hacker",        4_000),
    (0x07, "Adept",         3_000),
    (0x06, "Voyager",       2_000),
    (0x05, "Visionary",     1_500),
    (0x04, "Seeker",        1_000),
    (0x03, "Pathfinder",      500),
    (0x02, "Apprentice",      200),
    (0x01, "Neophyte",          0),
]


def level_from_points(points: int) -> tuple[int, str, int, Optional[int]]:
    """
    Resolve (level_int, label, threshold, next_threshold) from total points.

    *next_threshold* is None when the user is at the maximum level.
    """
    for i, (lvl, label, threshold) in enumerate(LEVEL_TABLE):
        if points >= threshold:
            next_threshold = LEVEL_TABLE[i - 1][2] if i > 0 else None
            return lvl, label, threshold, next_threshold
    # Should never reach here (Neophyte threshold is 0), but be safe.
    lvl, label, threshold = LEVEL_TABLE[-1]
    return lvl, label, threshold, LEVEL_TABLE[-2][2]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class UserProfile:
    """All TryHackMe profile fields used by the badge renderer."""

    username: str
    avatar_url: Optional[str] = None
    level: Optional[int] = None              # numeric level (e.g. 13)
    level_label: Optional[str] = None        # textual label e.g. "Legend"
    level_threshold: int = 0                 # min points for current level
    next_level_threshold: Optional[int] = None  # min points for next level
    league_tier: Optional[str] = None        # "novice" | "bronze" | "silver" | "gold" | "platinum" | "diamond"
    is_legend: bool = False                  # crown / "Legend" indicator
    rank: Optional[int] = None               # global leaderboard position
    top_percentage: Optional[float] = None   # e.g. 1.0 → "Top 1%"
    badge_count: int = 0
    streak: int = 0                          # current consecutive-day streak
    completed_rooms: int = 0
    capability_score: float = 0.0            # e.g. 73.4
    total_points: int = 0                    # raw user points
    country: Optional[str] = None
    user_role: Optional[str] = None          # e.g. "student"
    extras: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_user_profile(username: str) -> UserProfile:
    """
    Fetch a complete UserProfile for *username*.

    Tries the v2 public-profile endpoint first (returns every field), then
    merges any missing data from the Discord-user fallback endpoint.

    Raises:
        RuntimeError — both endpoints failed or returned no data.
    """
    profile = UserProfile(username=username)
    success_count = 0

    # Primary — v2 public-profile (returns everything in one call)
    try:
        data = _get_json(_V2_PROFILE.format(username=username))
        payload = _unwrap(data)
        if payload:
            _apply_v2_profile(payload, profile)
            success_count += 1
    except Exception as exc:
        logger.warning("v2 public-profile endpoint failed: %s", exc)

    # Fallback — discord endpoint (fills any gaps)
    try:
        data = _get_json(_DISCORD_API.format(username=username))
        _apply_discord(data, profile)
        success_count += 1
    except Exception as exc:
        logger.warning("discord fallback endpoint failed: %s", exc)

    if success_count == 0:
        raise RuntimeError(
            f"All TryHackMe endpoints failed for user '{username}'. "
            "The username may not exist or the profile may not be public."
        )

    # Always derive level + label from the points table — single source of
    # truth so the badge matches the TryHackMe in-app calculation.
    lvl, label, threshold, next_threshold = level_from_points(profile.total_points)
    profile.level = lvl
    profile.level_label = label
    profile.level_threshold = threshold
    profile.next_level_threshold = next_threshold
    profile.is_legend = lvl >= 0x0D  # Legend tier (0xD) and above

    return profile


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------


def _get_json(url: str) -> dict[str, Any]:
    """GET *url* with browser TLS impersonation and parse the JSON body."""
    logger.debug("GET %s", url)
    resp = creq.get(
        url,
        headers=_HEADERS,
        impersonate=_IMPERSONATE,
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    if "json" not in resp.headers.get("Content-Type", ""):
        raise RuntimeError(
            f"Non-JSON response from {url} "
            f"(Content-Type={resp.headers.get('Content-Type', '?')})"
        )
    return resp.json()


def _unwrap(data: Any) -> dict[str, Any]:
    """Pull the inner object out of `{"status": "success", "data": {...}}`."""
    if isinstance(data, dict):
        if data.get("status") == "success" and isinstance(data.get("data"), dict):
            return data["data"]
        if data.get("status") == "error":
            raise RuntimeError(data.get("message", "API returned error"))
        return data
    return {}


# ---------------------------------------------------------------------------
# Field mappers
# ---------------------------------------------------------------------------


def _apply_v2_profile(data: dict[str, Any], p: UserProfile) -> None:
    """Map fields from /api/v2/public-profile into the UserProfile."""
    p.avatar_url = data.get("avatar") or p.avatar_url
    p.level = _int(data.get("level")) or p.level
    p.league_tier = data.get("leagueTier") or p.league_tier
    p.is_legend = bool(data.get("shouldShowCrown")) or p.is_legend
    p.rank = _int(data.get("rank")) or p.rank
    p.top_percentage = _float(data.get("topPercentage")) or p.top_percentage
    p.badge_count = _int(data.get("badgesNumber")) or p.badge_count
    p.streak = _int(data.get("streak")) or p.streak
    p.completed_rooms = _int(data.get("completedRoomsNumber")) or p.completed_rooms
    p.total_points = _int(data.get("totalPoints")) or p.total_points
    p.country = data.get("country") or p.country
    p.user_role = data.get("userRole") or p.user_role

    # capabilityScore is a nested object: {"value": 73.4, "pov": "red"}
    cap = data.get("capabilityScore")
    if isinstance(cap, dict):
        p.capability_score = _float(cap.get("value")) or p.capability_score
    else:
        p.capability_score = _float(cap) or p.capability_score


def _apply_discord(data: dict[str, Any], p: UserProfile) -> None:
    """Fill gaps from /api/discord/user/{username}."""
    if not isinstance(data, dict):
        return
    if not p.avatar_url:
        p.avatar_url = data.get("avatar")
    if not p.rank:
        p.rank = _int(data.get("userRank"))
    if not p.total_points:
        p.total_points = _int(data.get("points")) or 0


# ---------------------------------------------------------------------------
# Type-coercion utilities
# ---------------------------------------------------------------------------


def _int(value: Any) -> Optional[int]:
    """Convert *value* to int; return None on failure."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> Optional[float]:
    """Convert *value* to float; return None on failure."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
