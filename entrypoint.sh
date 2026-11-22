#!/bin/sh
# REFRESH=monthly: a recap of each month, built on the 1st of the next month.
# REFRESH=yearly:  a recap of Jan 1 - Dec 31, built on Jan 1.
# REFRESH=both (default): both, so January 1 brings December's recap and the year's.
# On startup it builds the periods in progress so the page isn't empty.
# Each recap goes to /data/site/2026 or /data/site/2026-11; /data/site/index.html lists them.
mode=${REFRESH:-both}
mkdir -p /data/site

build() {  # build YEAR [MONTH], retrying every 15 minutes until it works
  dir=/data/site/$1${2:+-$(printf %02d "$2")}
  until python /app/wrapped.py --year "$1" ${2:+--month "$2"} --out "$dir"; do
    echo "generation failed, retrying in 15 minutes"; sleep 900
  done
  python -c '
import datetime as dt, html, os
d = "/data/site"
names = sorted((x for x in os.listdir(d) if os.path.isfile(f"{d}/{x}/index.html")), reverse=True)
label = lambda x: dt.datetime.strptime(x, "%Y-%m").strftime("%B %Y") if "-" in x else f"{x}, the whole year"
open(f"{d}/index.html", "w").write(
    "<!doctype html><meta charset=utf-8><meta name=viewport content=\"width=device-width,initial-scale=1\"><title>Wrapped</title>"
    "<style>body{font:18px/1.6 system-ui;max-width:30em;margin:2em auto;padding:0 16px}</style><h1>Wrapped</h1>"
    + "".join(f"<p><a href=\"{x}/\">{html.escape(label(x))}</a>" for x in names))'
}

(
  y=$(date +%Y); m=$(date +%m); m=${m#0}
  [ "$mode" != yearly ] && build "$y" "$m"
  [ "$mode" != monthly ] && build "$y"
  while true; do
    sleep "$(python -c '
import datetime as dt
n = dt.datetime.now()
print(int((dt.datetime(n.year + n.month // 12, n.month % 12 + 1, 1, 0, 5) - n).total_seconds()))')"
    y=$(date +%Y); m=$(date +%m); m=${m#0}  # the new month; recap the one that just ended
    py=$y pm=$((m - 1)); [ "$pm" = 0 ] && py=$((y - 1)) pm=12
    [ "$mode" != yearly ] && build "$py" "$pm"
    [ "$mode" != monthly ] && [ "$m" = 1 ] && build "$py"
  done
) &
# ponytail: stdlib static server, fine for a personal recap; put a reverse proxy in front for TLS
# no-cache: the page is regenerated in place, so browsers must revalidate instead of showing an old copy
exec python -c '
import functools, http.server, os
class H(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()
http.server.ThreadingHTTPServer(("", int(os.environ.get("PORT", 8080))), functools.partial(H, directory="/data/site")).serve_forever()
' 
