"""
Cache layer for the generated badge image.

A cache entry consists of three files inside CACHE_DIR:
    badge.png    — the last successfully generated PNG badge
    meta.json    — metadata containing the UTC timestamp of that generation
    profile.json — the raw scraped profile (debug / introspection)

A cache hit requires badge.png and meta.json to exist and the timestamp to
be within CACHE_MAX_AGE_HOURS hours of the current UTC time.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_BADGE_FILENAME = "badge.png"
_META_FILENAME = "meta.json"
_PROFILE_FILENAME = "profile.json"


def is_cache_valid(cache_dir: Path, max_age_hours: int) -> bool:
    """
    Return True if a fresh cached badge exists.

    Args:
        cache_dir: Directory that holds badge.png and meta.json.
        max_age_hours: Maximum allowed age of the cached badge in hours.
    """
    badge_path = cache_dir / _BADGE_FILENAME
    meta_path = cache_dir / _META_FILENAME

    if not badge_path.exists() or not meta_path.exists():
        logger.debug("Cache miss: one or both files absent in %s.", cache_dir)
        return False

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        last_updated = datetime.fromisoformat(meta["last_updated"])
        age = datetime.utcnow() - last_updated
        if age < timedelta(hours=max_age_hours):
            logger.debug("Cache hit (age=%s).", age)
            return True
        logger.debug("Cache stale (age=%s > %sh).", age, max_age_hours)
        return False
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("Corrupted cache metadata — treating as stale: %s", exc)
        return False


def get_cached_badge(cache_dir: Path) -> bytes | None:
    """Return raw PNG bytes from the on-disk cache, or None if absent."""
    badge_path = cache_dir / _BADGE_FILENAME
    return badge_path.read_bytes() if badge_path.exists() else None


def save_badge(
    cache_dir: Path,
    image_bytes: bytes,
    profile: Any | None = None,
) -> None:
    """
    Write *image_bytes* to badge.png, record the current UTC timestamp in
    meta.json, and (if *profile* is provided) dump the scraped data to
    profile.json for debugging.  The directory is created if it does not
    exist.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.utcnow().isoformat()

    (cache_dir / _BADGE_FILENAME).write_bytes(image_bytes)
    (cache_dir / _META_FILENAME).write_text(
        json.dumps({"last_updated": now}, indent=2),
        encoding="utf-8",
    )

    if profile is not None:
        try:
            payload = asdict(profile) if is_dataclass(profile) else profile
        except TypeError:
            payload = {"repr": repr(profile)}
        payload = {"scraped_at": now, "profile": payload}
        (cache_dir / _PROFILE_FILENAME).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

    logger.info("Badge cached at %s.", cache_dir / _BADGE_FILENAME)
