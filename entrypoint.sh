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
# no-cache: the page is regenerated in place, so browsers must revalidate instead of showing yesterday's recap
exec python -c '
import functools, http.server, os
class H(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()
http.server.ThreadingHTTPServer(("", int(os.environ.get("PORT", 8080))), functools.partial(H, directory="/data/site")).serve_forever()
' 
