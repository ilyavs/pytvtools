#!/bin/bash
set -euo pipefail

# Start Chrome headless with CDP
mkdir -p "$TV_USER_DATA_DIR"

chromium \
    --remote-debugging-port="$TV_CDP_PORT" \
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

# Wait for CDP to become reachable
for i in $(seq 1 30); do
    if curl -sf "http://localhost:$TV_CDP_PORT/json/version" > /dev/null 2>&1; then
        break
    fi
    sleep 1
done

echo "Chrome ready (pid=$CHROME_PID, CDP port=$TV_CDP_PORT)"

# If CMD is provided, run it; otherwise drop into a shell
if [ $# -gt 0 ]; then
    exec "$@"
else
    exec /bin/bash
fi

# On exit, clean up Chrome
trap "kill $CHROME_PID 2>/dev/null" EXIT
