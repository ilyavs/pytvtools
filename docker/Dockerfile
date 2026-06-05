FROM python:3.11-slim-bookworm AS base

# Install Chromium + socat (works on both ARM64 and x86_64)
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-sandbox \
    socat \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install pytvtools
COPY . .
RUN pip install --no-cache-dir .

ENV TV_CDP_PORT=9222
ENV TV_URL=https://www.tradingview.com/chart/
ENV TV_CHROME_BINARY=/usr/bin/chromium
ENV TV_USER_DATA_DIR=/data/chrome-profile

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
