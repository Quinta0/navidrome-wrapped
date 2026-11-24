#!/bin/sh
# REFRESH=monthly: a recap of each month, built on the 1st of the next month.
# REFRESH=yearly:  a recap of Jan 1 - Dec 31, built on Jan 1.
# REFRESH=both (default): both, so January 1 brings December's recap and the year's.
# On startup it builds the periods in progress so the page isn't empty, then any past ones still missing.
# Each recap goes to /data/site/2026 or /data/site/2026-11; /data/site/index.html lists them.
mode=${REFRESH:-both}
mkdir -p /data/site
python /app/wrapped.py --index /data/site  # so / shows "being built" during the first build

build() {  # build YEAR [MONTH], retrying every 15 minutes until it works
  dir=/data/site/$1${2:+-$(printf %02d "$2")}
  until python /app/wrapped.py --year "$1" ${2:+--month "$2"} --out "$dir"; do
    echo "generation failed, retrying in 15 minutes"; sleep 900
  done
  python /app/wrapped.py --index /data/site
}

(
  y=$(date +%Y); m=$(date +%m); m=${m#0}
  [ "$mode" != yearly ] && build "$y" "$m"
  [ "$mode" != monthly ] && build "$y"
  # past months/years that have no recap yet; one pass over the history, skipped quickly once all exist
  REFRESH=$mode python /app/wrapped.py --backfill /data/site || echo "backfill failed, it retries on the next restart"
  python /app/wrapped.py --index /data/site
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
exec python /app/serve.py
