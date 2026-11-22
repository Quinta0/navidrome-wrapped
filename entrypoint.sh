#!/bin/sh
# Regenerate the recap every REFRESH_HOURS and serve it as static files.
mkdir -p /data/site
(
  while true; do
    if python /app/wrapped.py --out /data/site; then
      sleep $(( ${REFRESH_HOURS:-24} * 3600 ))
    else
      echo "generation failed, retrying in 15 minutes"; sleep 900
    fi
  done
) &
# ponytail: stdlib static server, fine for a personal recap; put a reverse proxy in front for TLS
exec python -m http.server -d /data/site "${PORT:-8080}"
