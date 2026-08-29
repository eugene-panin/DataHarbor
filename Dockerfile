FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml README.md setup.py ./
COPY apps ./apps
COPY bundles ./bundles
COPY extractors ./extractors
# Lockfile is optional on first build; prefer frozen when present
COPY uv.lock* ./

# Core + crawl toolkit (CDX/WARC used by store_intel and similar bundles)
RUN if [ -f uv.lock ]; then uv sync --frozen --no-dev --extra crawl; else uv sync --no-dev --extra crawl; fi

RUN mkdir -p /tmp/dagster_home

COPY . .

CMD ["python", "-m", "apps.dagster_app.run_dev"]
