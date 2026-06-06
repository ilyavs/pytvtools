FROM python:3.11-slim-bookworm AS base

# Install Chromium + socat (works on both ARM64 and x86_64)
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-sandbox \
    socat \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Pre-install runtime deps (cached layer — only re-runs if deps change).
# pytvtools itself is installed editable at container start from the bind mount.
RUN pip install --no-cache-dir httpx websockets

ENV TV_CDP_PORT=9222
ENV TV_URL=https://www.tradingview.com/chart/
ENV TV_CHROME_BINARY=/usr/bin/chromium
ENV TV_USER_DATA_DIR=/data/chrome-profile

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
