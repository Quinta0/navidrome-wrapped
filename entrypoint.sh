#!/bin/sh
# Regenerate the recap every REFRESH_HOURS and serve it as static files.
mkdir -p /data/site
(
  while true; do
    python /app/wrapped.py --out /data/site || echo "generation failed, retrying next cycle"
    sleep $(( ${REFRESH_HOURS:-24} * 3600 ))
  done
) &
# ponytail: stdlib static server, fine for a personal recap; put a reverse proxy in front for TLS
exec python -m http.server -d /data/site "${PORT:-8080}"
