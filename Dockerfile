# ── Base image ──────────────────────────────────────────────────────────────
FROM python:3.11-slim

# ── System dependencies ──────────────────────────────────────────────────────
# fonts-dejavu-core  → DejaVuSans / DejaVuSans-Bold / DejaVuSansMono for Pillow
# libcairo2 + libpango → required by cairosvg to rasterise SVG icons
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fonts-dejavu-core \
        libcairo2 \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Python dependencies (layer-cached separately from source) ─────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Application source ───────────────────────────────────────────────────
COPY app/ ./app/
COPY img/ ./img/

# ── Runtime cache directory ──────────────────────────────────────────────
RUN mkdir -p /app/cache

# ── Non-root user (security best practice) ───────────────────────────────
RUN adduser --disabled-password --gecos "" appuser \
    && chown -R appuser:appuser /app
USER appuser

# ── Exposed port ─────────────────────────────────────────────────────────
EXPOSE 8000

# ── Start server ─────────────────────────────────────────────────────────
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
