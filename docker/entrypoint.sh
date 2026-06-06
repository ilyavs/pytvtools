#!/bin/bash
set -euo pipefail

cleanup() {
    kill "$CHROME_PID" 2>/dev/null || true
    kill "$SOCAT_PID" 2>/dev/null || true
}
trap cleanup EXIT

# Editable install so source from the bind mount is reflected without rebuild
pip install --no-cache-dir -e /app > /dev/null 2>&1

# Remove stale Chrome lock files from unclean shutdown
rm -f "$TV_USER_DATA_DIR/SingletonLock" "$TV_USER_DATA_DIR/SingletonCookie" "$TV_USER_DATA_DIR/SingletonSocket"

# Chrome M113+ ignores --remote-debugging-address=0.0.0.0 and binds only
# to 127.0.0.1.  We give it an *internal* port and use socat on 0.0.0.0
# so Docker port-publishing can reach the CDP endpoint.
TV_CDP_INTERNAL_PORT="${TV_CDP_INTERNAL_PORT:-9223}"

mkdir -p "$TV_USER_DATA_DIR"

chromium \
    --remote-debugging-port="$TV_CDP_INTERNAL_PORT" \
    --remote-allow-origins=* \
    --user-data-dir="$TV_USER_DATA_DIR" \
    --no-first-run \
    --no-default-browser-check \
    --disable-sync \
    --no-sandbox \
    --disable-gpu \
    --headless=new \
    --enable-unsafe-swiftshader \
    "$TV_URL" &
CHROME_PID=$!

# Wait for Chrome's CDP (internal port)
for i in $(seq 1 30); do
    if curl -sf "http://localhost:$TV_CDP_INTERNAL_PORT/json/version" > /dev/null 2>&1; then
        break
    fi
    sleep 1
done

# socat relays from the published port (0.0.0.0) to Chrome's loopback-only port
socat TCP-LISTEN:"$TV_CDP_PORT",fork,reuseaddr \
      TCP:127.0.0.1:"$TV_CDP_INTERNAL_PORT" &
SOCAT_PID=$!

# Verify socat is ready
for i in $(seq 1 5); do
    if curl -sf "http://localhost:$TV_CDP_PORT/json/version" > /dev/null 2>&1; then
        break
    fi
    sleep 1
done

echo "Chrome ready (pid=$CHROME_PID, CDP internal=$TV_CDP_INTERNAL_PORT external=$TV_CDP_PORT)"

# If CMD is provided, run it; otherwise keep container alive
if [ $# -gt 0 ]; then
    exec "$@"
else
    wait $CHROME_PID
fi
