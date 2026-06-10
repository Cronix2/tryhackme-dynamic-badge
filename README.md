# TryHackMe Dynamic Badge

A lightweight **Python / FastAPI** service that generates a dynamic PNG badge
for any public TryHackMe profile — automatically refreshed every 24 hours.

[![TryHackMe Badge](https://your-domain.com/badge.png)](https://tryhackme.com/p/your_username)

---

## How it works

1. A request arrives at `GET /badge.png`.
2. The service checks for a locally cached badge (`cache/badge.png`).
3. If the cache is fresh (< `CACHE_MAX_AGE_HOURS`), it is returned immediately.
4. Otherwise the TryHackMe public API and profile page are scraped for the latest stats.
5. A new PNG badge is rendered with Pillow and saved to disk.
6. If scraping fails but a cached badge exists, the stale cache is served.
7. If no data is available at all, a `503` JSON error is returned.

---

## Badge contents

| Field           | Description                                        |
|-----------------|----------------------------------------------------|
| Profile picture | Avatar downloaded from TryHackMe                   |
| Username        | TryHackMe handle                                   |
| Level           | User level (e.g. Beginner → Gold → King)           |
| Global Rank     | Leaderboard position                               |
| Top %           | Percentile among all users                         |
| Badges          | Number of earned badges                            |
| Streak          | Current day-streak (flame / consecutive-day count) |
| Rooms           | Total completed rooms                              |
| Score           | Capability / point score                           |

---

## Project structure

```txt
tryhackme-dynamic-badge/
├── app/
│   ├── __init__.py          # Package marker
│   ├── main.py              # FastAPI routes
│   ├── scraper.py           # TryHackMe data extraction
│   ├── badge_renderer.py    # Pillow image generation
│   ├── cache.py             # Cache read / write / validation
│   └── config.py            # Environment variable configuration
├── cache/                   # Runtime badge cache (git-ignored)
├── .env.example             # Environment variable template
├── .dockerignore
├── .gitignore
├── Dockerfile
├── requirements.txt
└── README.md
```

---

## Environment variables

| Variable              | Required | Default   | Description                                  |
|-----------------------|----------|-----------|----------------------------------------------|
| `THM_USERNAME`        | **Yes**  | —         | TryHackMe username to generate the badge for |
| `CACHE_DIR`           | No       | `cache`   | Directory for cached badge files             |
| `CACHE_MAX_AGE_HOURS` | No       | `24`      | Cache TTL in hours                           |
| `HOST`                | No       | `0.0.0.0` | Uvicorn bind host                            |
| `PORT`                | No       | `8000`    | Uvicorn bind port                            |

---

## Setup

### Prerequisites

- Python 3.11+
- pip

### Installation

```bash
git clone https://github.com/your-username/tryhackme-dynamic-badge.git
cd tryhackme-dynamic-badge

python -m venv .venv

# macOS / Linux
source .venv/bin/activate
# Windows (PowerShell)
.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

---

## Local launch

Copy the environment template and fill in your username:

```bash
cp .env.example .env
# Edit .env — set THM_USERNAME=your_username
```

Start the development server (the `.env` file is loaded automatically):

```bash
uvicorn app.main:app --reload
```

Or pass the variable inline:

```bash
# macOS / Linux
THM_USERNAME=your_username uvicorn app.main:app --reload

# Windows (PowerShell)
$env:THM_USERNAME="your_username"; uvicorn app.main:app --reload
```

Visit the badge at <http://localhost:8000/badge.png>  
Health check at <http://localhost:8000/health>

---

## Docker

### Build

```bash
docker build -t tryhackme-badge .
```

### Run

```bash
docker run -p 8000:8000 -e THM_USERNAME=your_username tryhackme-badge
```

With a persistent cache volume so the badge survives container restarts:

```bash
docker run -p 8000:8000 \
  -e THM_USERNAME=your_username \
  -v "$(pwd)/cache:/app/cache" \
  tryhackme-badge
```

---

## Deployment

### Fly.io

```bash
fly launch            # follow prompts, select a region
fly secrets set THM_USERNAME=your_username
fly deploy
```

### Railway / Render

Set the `THM_USERNAME` environment variable in the platform dashboard
and point the start command to:

```txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The `PORT` environment variable is also respected if the platform sets it
automatically.

---

## Usage in your profile README

After deploying, embed the badge in any Markdown file:

```markdown
![TryHackMe Badge](https://your-domain.com/badge.png)
```

With a clickable link to your TryHackMe profile:

```markdown
[![TryHackMe Badge](https://your-domain.com/badge.png)](https://tryhackme.com/p/your_username)
```

---

## License

MIT
