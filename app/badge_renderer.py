"""
Badge image generator using Pillow + cairosvg.

Layout (target reference)
-------------------------
A wide pill-shaped card with a thick green border.

Left   : circular avatar with a light ring.
Middle : username in large bold, with a level pill "[0xH] LEAGUE" placed
         to its right.
Below  : a large trophy icon on the left with `totalPoints` to its right,
         and "Top N%" caption underneath.
Right  : row of icon + value stats — flame/streak, badge/badges,
         door/rooms, diamond/capability score.

SVG assets are loaded from the `img/` directory at the project root and
rasterised with cairosvg.
"""
from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Callable, Optional

import cairosvg
import requests
from PIL import Image, ImageDraw, ImageFont

from .scraper import UserProfile

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Layout constants (pixels)
# ---------------------------------------------------------------------------

WIDTH = 1280
HEIGHT = 280
PADDING = 32
CORNER_RADIUS = 42
BORDER_WIDTH = 5

# Avatar
AVATAR_SIZE = 180
AVATAR_X = PADDING + 8
AVATAR_Y = (HEIGHT - AVATAR_SIZE) // 2
AVATAR_RING_WIDTH = 5

# Two content columns: left half is name + trophy, right half is icon row
CONTENT_X = AVATAR_X + AVATAR_SIZE + 36

# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------

C_BG = (15, 22, 38)              # dark navy
C_BORDER = (134, 204, 20)        # THM bright green
C_TEXT = (240, 242, 245)         # primary text
C_AVATAR_RING = (245, 247, 250)  # light ring around avatar
C_LEVEL_BRACKET = (240, 242, 245)
C_LEVEL_LEAGUE = (130, 138, 158)

# Per-icon text colours (match the SVG fills)
C_TROPHY = (245, 178, 60)        # gold
C_FLAME = (255, 138, 30)         # orange
C_BADGE = (200, 162, 230)        # lilac
C_DOOR = (113, 156, 249)         # blue
C_DIAMOND = (240, 242, 245)      # white

# ---------------------------------------------------------------------------
# Font sizes
# ---------------------------------------------------------------------------

FS_USERNAME = 52
FS_LEVEL = 32
FS_TROPHY_NUM = 44
FS_TOP_CAP = 32
FS_STAT_NUM = 40

# ---------------------------------------------------------------------------
# Asset paths
# ---------------------------------------------------------------------------

IMG_DIR = Path(__file__).resolve().parent.parent / "img"

ICON_FILES = {
    "trophy":     IMG_DIR / "trophy.svg",
    "flame":      IMG_DIR / "flame.svg",
    "badge":      IMG_DIR / "badge.svg",
    "room":       IMG_DIR / "room.svg",
    "capability": IMG_DIR / "capability.svg",
}

# Cache rasterised icons so we only call cairosvg once per (name, height)
_icon_cache: dict[tuple[str, int], Image.Image] = {}


# ---------------------------------------------------------------------------
# Font loader
# ---------------------------------------------------------------------------


def _load_font(size: int, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont:
    """
    Try common TrueType font paths; fall back to Pillow's built-in bitmap
    font if none are available. `mono=True` selects a monospace font for
    the "[0xH]" level marker.
    """
    if mono:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
            if bold else
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "DejaVuSansMono-Bold.ttf" if bold else "DejaVuSansMono.ttf",
            "C:/Windows/Fonts/consolab.ttf" if bold else "C:/Windows/Fonts/consola.ttf",
            "/Library/Fonts/Menlo.ttc",
        ]
    else:
        suffix = "-Bold" if bold else ""
        candidates = [
            f"/usr/share/fonts/truetype/dejavu/DejaVuSans{suffix}.ttf",
            f"DejaVuSans{suffix}.ttf",
            "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
            "/Library/Fonts/Arial Bold.ttf" if bold else "/Library/Fonts/Arial.ttf",
        ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            pass
    logger.warning("No TrueType font found; using Pillow default bitmap font.")
    return ImageFont.load_default()


# ---------------------------------------------------------------------------
# SVG + avatar helpers
# ---------------------------------------------------------------------------


def _load_icon(name: str, height: int) -> Image.Image:
    """Rasterise the SVG *name* to a Pillow image at the given height."""
    key = (name, height)
    if key in _icon_cache:
        return _icon_cache[key]

    path = ICON_FILES[name]
    png_bytes = cairosvg.svg2png(url=str(path), output_height=height)
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    _icon_cache[key] = img
    return img


def _circle_crop(img: Image.Image, size: int) -> Image.Image:
    """Resize *img* to *size* × *size* and clip it to a circle."""
    img = img.resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    result = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    result.paste(img.convert("RGBA"), mask=mask)
    return result


def _placeholder_avatar(size: int, username: str) -> Image.Image:
    """Single-letter fallback when the real avatar download fails."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((0, 0, size - 1, size - 1), fill=(40, 42, 60))
    letter = username[0].upper() if username else "?"
    font = _load_font(size // 2, bold=True)
    bbox = draw.textbbox((0, 0), letter, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        ((size - tw) // 2 - bbox[0], (size - th) // 2 - bbox[1]),
        letter, fill=C_BORDER, font=font,
    )
    return img


def _download_avatar(url: str) -> Optional[Image.Image]:
    """Download an avatar image; return None on any failure."""
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        return Image.open(io.BytesIO(resp.content)).convert("RGBA")
    except Exception as exc:
        logger.warning("Avatar download failed (%s): %s", url, exc)
        return None


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------


def _text_size(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont
) -> tuple[int, int, tuple[int, int, int, int]]:
    """Return (width, height, bbox) of *text* rendered with *font*."""
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1], bbox


def _draw_text_centered_y(
    draw: ImageDraw.ImageDraw,
    text: str,
    x: int,
    cy: int,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, ...],
) -> int:
    """Draw *text* at *x*, vertically centred on *cy*. Returns end-x."""
    w, h, bbox = _text_size(draw, text, font)
    draw.text((x - bbox[0], cy - h // 2 - bbox[1]), text, fill=fill, font=font)
    return x + w


def _paste_icon_centered(
    canvas: Image.Image, icon: Image.Image, cx: int, cy: int
) -> None:
    """Paste *icon* on *canvas* centred at (cx, cy) with alpha blending."""
    x = cx - icon.width // 2
    y = cy - icon.height // 2
    canvas.paste(icon, (x, y), mask=icon)


def _format_int(n: int) -> str:
    """Pretty-print an integer with thin-space thousand separators."""
    return f"{n:,}".replace(",", " ")


def _sanitize_username(username: str) -> str:
    """
    Remove characters that DejaVuSansMono cannot render (emoji, regional
    indicators) so the badge does not show empty boxes next to the name.

    Keeps Latin letters, digits, common punctuation, and the basic Latin-1
    supplement range (accented characters).
    """
    out: list[str] = []
    for ch in username:
        cp = ord(ch)
        if (
            0x20 <= cp <= 0x7E              # ASCII printable
            or 0xA0 <= cp <= 0x024F        # Latin-1 + Latin-Extended A/B
            or 0x2018 <= cp <= 0x201F      # quotes
        ):
            out.append(ch)
    return "".join(out).strip() or username


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_badge(profile: UserProfile) -> bytes:
    """
    Render a PNG badge for *profile* and return the raw PNG bytes.

    Never raises — missing fields render as 0 or are omitted gracefully.
    """
    # ── Canvas with rounded green border ───────────────────────────────────
    img = Image.new("RGBA", (WIDTH, HEIGHT), C_BG + (255,))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        (BORDER_WIDTH // 2, BORDER_WIDTH // 2,
         WIDTH - BORDER_WIDTH // 2 - 1, HEIGHT - BORDER_WIDTH // 2 - 1),
        radius=CORNER_RADIUS,
        fill=C_BG + (255,),
        outline=C_BORDER + (255,),
        width=BORDER_WIDTH,
    )

    # ── Avatar with light ring ─────────────────────────────────────────────
    raw_avatar = _download_avatar(profile.avatar_url) if profile.avatar_url else None
    if raw_avatar is None:
        avatar_circle = _placeholder_avatar(AVATAR_SIZE, profile.username)
    else:
        avatar_circle = _circle_crop(raw_avatar, AVATAR_SIZE)

    ring_size = AVATAR_SIZE + AVATAR_RING_WIDTH * 2
    ring = Image.new("RGBA", (ring_size, ring_size), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse(
        (0, 0, ring_size - 1, ring_size - 1), fill=C_AVATAR_RING + (255,)
    )
    img.paste(ring, (AVATAR_X - AVATAR_RING_WIDTH, AVATAR_Y - AVATAR_RING_WIDTH),
              mask=ring)
    img.paste(avatar_circle, (AVATAR_X, AVATAR_Y), mask=avatar_circle)

    # ── Fonts ──────────────────────────────────────────────────────────────
    font_username   = _load_font(FS_USERNAME, bold=True, mono=True)
    font_level      = _load_font(FS_LEVEL, bold=True, mono=True)
    font_league     = _load_font(FS_LEVEL, bold=True)
    font_trophy_num = _load_font(FS_TROPHY_NUM)
    font_top        = _load_font(FS_TOP_CAP, bold=True)
    font_stat_num   = _load_font(FS_STAT_NUM)

    # ── Top row: username + level pill ─────────────────────────────────────
    top_y = PADDING + 18
    safe_name = _sanitize_username(profile.username)
    name_w, name_h, _ = _text_size(draw, safe_name, font_username)
    draw.text((CONTENT_X, top_y), safe_name, fill=C_TEXT, font=font_username)

    if profile.level is not None:
        level_text = f"[0x{profile.level:X}]"
        # Prefer the table-derived label (canonical) over the API league tier.
        league_text = (profile.level_label
                       or ("Legend" if profile.is_legend else "")
                       or (profile.league_tier or "").capitalize())
        # Place the level pill a fixed gap to the right of the username
        lx = CONTENT_X + name_w + 70
        ly = top_y + (FS_USERNAME - FS_LEVEL) // 2
        draw.text((lx, ly), level_text, fill=C_LEVEL_BRACKET, font=font_level)
        lw, _, _ = _text_size(draw, level_text, font_level)
        if league_text:
            draw.text((lx + lw + 6, ly), league_text,
                      fill=C_LEVEL_LEAGUE, font=font_league)

    # ── Trophy + RANK + "Top X%" (lower-left of content area) ──────────────
    trophy_icon = _load_icon("trophy", height=98)
    trophy_cx = CONTENT_X + trophy_icon.width // 2
    # Vertically position the trophy in the lower half of the card
    trophy_cy = top_y + name_h + 26 + trophy_icon.height // 2
    _paste_icon_centered(img, trophy_icon, trophy_cx, trophy_cy)

    # Rank — large number to the right of the trophy.
    rank_str = _format_int(profile.rank) if profile.rank else "—"
    pts_x = trophy_cx + trophy_icon.width // 2 + 18
    pts_y = trophy_cy - 18  # slightly above centre so "Top X%" sits below
    pw, ph, pbbox = _text_size(draw, rank_str, font_trophy_num)
    draw.text((pts_x - pbbox[0], pts_y - ph // 2 - pbbox[1]),
              rank_str, fill=C_TROPHY, font=font_trophy_num)

    # "Top N%" caption directly under the rank
    if profile.top_percentage is not None:
        if profile.top_percentage == int(profile.top_percentage):
            top_str = f"Top {int(profile.top_percentage)}%"
        else:
            top_str = f"Top {profile.top_percentage:g}%"
        draw.text((pts_x, pts_y + ph // 2 + 8),
                  top_str, fill=C_TROPHY, font=font_top)

    # ── Right side: row of icon + value stats ──────────────────────────────
    # streak (flame) | badges | rooms (door) | capability (diamond)
    stats: list[tuple[str, str, tuple[int, int, int]]] = [
        ("flame",      str(profile.streak),          C_FLAME),
        ("badge",      str(profile.badge_count),     C_BADGE),
        ("room",       str(profile.completed_rooms), C_DOOR),
        ("capability", f"{profile.capability_score:g}"
                       if profile.capability_score else "0", C_DIAMOND),
    ]

    # Compute pixel width of each stat (icon + gap + number) so the row can
    # be distributed evenly without overlap.
    icon_h = 60
    gap = 18
    stat_widths: list[tuple[int, int, int]] = []  # (icon_w, value_w, total)
    for icon_name, value, _colour in stats:
        ic = _load_icon(icon_name, height=icon_h)
        vw, _vh, _vb = _text_size(draw, value, font_stat_num)
        stat_widths.append((ic.width, vw, ic.width + gap + vw))

    # Right half of the card hosts the stats row; trophy/totalPoints ends
    # around CONTENT_X + 320, so the stats area begins after that with
    # some breathing room.
    right_x0 = CONTENT_X + 360
    right_x1 = WIDTH - PADDING - 16
    right_w = right_x1 - right_x0

    total_stat_w = sum(w[2] for w in stat_widths)
    spacing = max(28, (right_w - total_stat_w) // (len(stats) - 1)) \
        if len(stats) > 1 else 0

    stats_cy = trophy_cy
    cursor = right_x0
    for (icon_name, value, colour), (iw, vw, _tw) in zip(stats, stat_widths):
        icon_img = _load_icon(icon_name, height=icon_h)
        icon_cx = cursor + iw // 2
        _paste_icon_centered(img, icon_img, icon_cx, stats_cy)

        text_x = cursor + iw + gap
        _vw, vh, vbbox = _text_size(draw, value, font_stat_num)
        draw.text((text_x - vbbox[0], stats_cy - vh // 2 - vbbox[1]),
                  value, fill=colour, font=font_stat_num)

        cursor += iw + gap + vw + spacing

    # ── Serialise to PNG bytes ─────────────────────────────────────────────
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()
