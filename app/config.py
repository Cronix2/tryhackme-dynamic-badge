"""Application configuration — all values loaded from environment variables."""
from __future__ import annotations

import os
from pathlib import Path

# Load .env file when present (no-op if python-dotenv is not installed)
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Required
# ---------------------------------------------------------------------------

#: TryHackMe username whose profile badge will be generated.
THM_USERNAME: str = os.environ.get("THM_USERNAME", "")

# ---------------------------------------------------------------------------
# Optional — all have sensible defaults
# ---------------------------------------------------------------------------

#: Directory where badge.png and meta.json are stored between refreshes.
CACHE_DIR: Path = Path(os.environ.get("CACHE_DIR", "cache"))

#: Maximum age of a cached badge before it is re-generated (hours).
CACHE_MAX_AGE_HOURS: int = int(os.environ.get("CACHE_MAX_AGE_HOURS", "24"))

#: Uvicorn bind host.
HOST: str = os.environ.get("HOST", "0.0.0.0")

#: Uvicorn bind port.
PORT: int = int(os.environ.get("PORT", "8000"))
