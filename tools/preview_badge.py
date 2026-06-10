"""Quick local preview: fetches Cronix3 and writes badge_preview.png next to it.

Also refreshes the on-disk cache (cache/badge.png + cache/profile.json) so
you can inspect the scraped data when something looks off.

Usage:
    python -m tools.preview_badge [username]
"""
from __future__ import annotations

import sys
from pathlib import Path

from app.badge_renderer import generate_badge
from app.cache import save_badge
from app.config import CACHE_DIR
from app.scraper import fetch_user_profile


def main() -> int:
    username = sys.argv[1] if len(sys.argv) > 1 else "Cronix3"
    profile = fetch_user_profile(username)
    print(
        f"level={profile.level} label={profile.level_label} "
        f"threshold={profile.level_threshold} next={profile.next_level_threshold} "
        f"legend={profile.is_legend}"
    )
    print(
        f"points={profile.total_points} rank={profile.rank} "
        f"top%={profile.top_percentage} streak={profile.streak} "
        f"badges={profile.badge_count} rooms={profile.completed_rooms} "
        f"cap={profile.capability_score}"
    )

    png = generate_badge(profile)
    save_badge(CACHE_DIR, png, profile=profile)

    out = Path(__file__).resolve().parent.parent / "badge_preview.png"
    out.write_bytes(png)
    print(f"wrote {len(png)} bytes → {out}")
    print(f"cache updated at {CACHE_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
