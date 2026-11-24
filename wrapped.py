#!/usr/bin/env python3
"""Music Wrapped from ListenBrainz + Last.fm + Navidrome. Stdlib only.

Config via env vars (each source optional, set at least one of LB/Last.fm):
  LB_USER, LB_TOKEN (optional)          ListenBrainz
  LASTFM_USER, LASTFM_KEY               Last.fm (key: https://www.last.fm/api/account/create)
  ND_URL, ND_USER, ND_PASS              Navidrome (durations, genres, library stats, slide audio)

Usage: python3 wrapped.py [--year 2026] [--month 11] [--out wrapped]
Output is a self-contained folder (index.html + media/) - zip it or put it on any static host to share.
"""
import argparse, base64, hashlib, json, os, secrets, sys, time, urllib.parse, urllib.request
from collections import Counter
from datetime import datetime, timedelta

from design import Gen, index_page, render

UA = "music-wrapped/1.0"
DEFAULT_SECS = 210  # fallback track length when no source knows it
CACHE = "cache"


def get(url, headers=None, raw=False):
    for attempt in range(5):
        req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return (r.read(), r.headers.get("Content-Type", "")) if raw else json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < 4:
                time.sleep(int(e.headers.get("X-RateLimit-Reset-In") or 2 ** attempt))
                continue
            raise


def key(artist, title=""):
    return (artist or "").strip().lower(), (title or "").strip().lower()


# ---------- sources: each yields dicts {ts, artist, title, album, secs?} ----------

def listenbrainz(user, token, start, end):
    hdr = {"Authorization": f"Token {token}"} if token else {}
    max_ts = end
    while True:
        q = urllib.parse.urlencode({"max_ts": max_ts, "count": 1000})  # API forbids min_ts+max_ts together
        listens = get(f"https://api.listenbrainz.org/1/user/{urllib.parse.quote(user)}/listens?{q}", hdr)["payload"]["listens"]
        if not listens:
            return
        for l in listens:
            m = l["track_metadata"]
            info = m.get("additional_info") or {}
            ms = info.get("duration_ms") or (info.get("duration") or 0) * 1000
            yield {"ts": l["listened_at"], "artist": m.get("artist_name"), "title": m.get("track_name"),
                   "album": m.get("release_name"), "secs": ms / 1000 if ms else None}
        max_ts = listens[-1]["listened_at"]
        if max_ts < start:
            return
        print(f"  listenbrainz: {datetime.fromtimestamp(max_ts):%Y-%m-%d}", file=sys.stderr)


def lastfm(user, api_key, start, end):
    page, pages = 1, 1
    while page <= pages:
        q = urllib.parse.urlencode({"method": "user.getrecenttracks", "user": user, "api_key": api_key,
                                    "from": start, "to": end, "limit": 200, "page": page, "format": "json"})
        rt = get(f"https://ws.audioscrobbler.com/2.0/?{q}")["recenttracks"]
        pages = int(rt["@attr"]["totalPages"])
        tracks = rt["track"] if isinstance(rt["track"], list) else [rt["track"]]
        for t in tracks:
            if "date" not in t:  # now playing
                continue
            yield {"ts": int(t["date"]["uts"]), "artist": t["artist"]["#text"], "title": t["name"],
                   "album": t["album"]["#text"], "secs": None}
        print(f"  last.fm: page {page}/{pages}", file=sys.stderr)
        page += 1


def subsonic(base, user, pw):
    """Returns url(endpoint, **params) with token auth."""
    def url(ep, **params):
        salt = secrets.token_hex(6)
        q = {"u": user, "t": hashlib.md5((pw + salt).encode()).hexdigest(), "s": salt,
             "v": "1.16.1", "c": "wrapped", "f": "json", **params}
        return f"{base.rstrip('/')}/rest/{ep}?{urllib.parse.urlencode(q)}"
    return url


def navidrome(nd):
    """Whole library via search3 with empty query (Navidrome supports it)."""
    songs, off = [], 0
    while True:
        r = get(nd("search3", query="", songCount=500, songOffset=off, artistCount=0, albumCount=0))["subsonic-response"]
        if r["status"] != "ok":
            raise SystemExit(f"navidrome: {r.get('error')}")
        batch = r.get("searchResult3", {}).get("song", [])
        songs += batch
        if len(batch) < 500:
            return songs
        off += 500


def prior_artists(name, listens_before):
    """Artists heard before the year. Cached: the past doesn't change (delete cache/ after big imports)."""
    path = os.path.join(CACHE, f"history-{name}.json")
    if os.path.exists(path):
        return set(json.load(open(path)))
    artists = sorted({key(l["artist"])[0] for l in listens_before})
    os.makedirs(CACHE, exist_ok=True)
    json.dump(artists, open(path, "w"))
    return set(artists)


def fetch_media(nd, songs, out):
    """Download audio (mp3 transcode) + cover for each slide's song into out/media."""
    os.makedirs(os.path.join(out, "media"), exist_ok=True)
    media = {}
    for slide, song in songs.items():
        if not song:
            continue
        m = {"title": song.get("title"), "artist": song.get("artist")}
        for kind, path, ep, params in (
                ("audio", f"media/{song['id']}.mp3", "stream", {"id": song["id"], "format": "mp3", "maxBitRate": 128}),
                ("cover", f"media/{song['id']}.jpg", "getCoverArt", {"id": song.get("coverArt") or song["id"], "size": 600})):
            full = os.path.join(out, path)
            if not os.path.exists(full):
                try:
                    data, ctype = get(nd(ep, **params), raw=True)
                except Exception as ex:
                    print(f"  skip {kind} for {m['title']}: {ex}", file=sys.stderr)
                    continue
                if not ctype.startswith(("audio", "image")):  # subsonic returns errors as JSON with 200
                    print(f"  skip {kind} for {m['title']}: {data[:120]!r}", file=sys.stderr)
                    continue
                open(full, "wb").write(data)
            m[kind] = path
        media[slide] = m
        print(f"  media: {slide} -> {m['title']}", file=sys.stderr)
    return media


# ---------- stats ----------

def merge(*sources):
    """Combine sources, drop cross-scrobbles (same track within 2 min)."""
    out, last = [], {}
    for s in sorted((s for src in sources for s in src), key=lambda s: s["ts"]):
        k = key(s["artist"], s["title"])
        if k in last and s["ts"] - last[k] < 120:
            continue
        last[k] = s["ts"]
        out.append(s)
    return out


def longest_streak(days):
    best = run = 0
    prev = None
    for d in sorted(days):
        run = run + 1 if prev and d - prev == timedelta(days=1) else 1
        best, prev = max(best, run), d
    return best


def genres_of(song):
    return [g.strip() for g in ((song or {}).get("genre") or "").split(";") if g.strip()]


def compute(listens, library, prior=frozenset()):
    lib = {key(s.get("artist"), s.get("title")): s for s in library}
    secs, genres = 0, Counter()
    for l in listens:
        l["song"] = lib.get(key(l["artist"], l["title"]))
        l["when"] = datetime.fromtimestamp(l["ts"])
        secs += l["secs"] or (l["song"] or {}).get("duration") or DEFAULT_SECS
        genres.update(genres_of(l["song"]))
    days = Counter(l["when"].date() for l in listens)
    artists = Counter(l["artist"] for l in listens if l["artist"])
    tracks = Counter((l["title"], l["artist"]) for l in listens if l["title"])
    albums = Counter((l["album"], l["artist"]) for l in listens if l["album"])
    new = [(a, n) for a, n in artists.most_common() if key(a)[0] not in prior]
    months = [sum(1 for l in listens if l["when"].month == m) for m in range(1, 13)]
    hours = [sum(1 for l in listens if l["when"].hour == h) for h in range(24)]
    top_day = days.most_common(1)[0] if days else None
    lib_top = sorted(library, key=lambda s: -s.get("playCount", 0))[:5]
    by_id = {s["id"]: s for s in library}

    def pick(pred=lambda l: True):
        """Most-played library song among listens matching pred."""
        c = Counter(l["song"]["id"] for l in listens if l["song"] and pred(l))
        return by_id[c.most_common(1)[0][0]] if c else None

    first = lambda c: c.most_common(1)[0][0] if c else None
    top_artist, second = (artists.most_common(2) + [(None, 0)] * 2)[:2]
    peak_m, peak_h = months.index(max(months)) + 1, hours.index(max(hours))
    songs = {
        "intro": pick(), "track": pick(), "summary": pick(),
        "artist": pick(lambda l: l["artist"] == top_artist[0]),
        "album": pick(lambda l: (l["album"], l["artist"]) == first(albums)),
        "explore": pick(lambda l: l["artist"] == second[0]),
        "new": pick(lambda l: new and l["artist"] == new[0][0]),
        "genre": pick(lambda l: first(genres) in genres_of(l["song"])),
        "month": pick(lambda l: l["when"].month == peak_m),
        "hour": pick(lambda l: l["when"].hour == peak_h),
        "streak": pick(lambda l: top_day and l["when"].date() == top_day[0]),
        "library": lib_top[0] if lib_top and lib_top[0].get("playCount") else None,
    }
    return {
        "plays": len(listens), "minutes": round(secs / 60),
        "artists": artists.most_common(10), "tracks": tracks.most_common(10), "albums": albums.most_common(10),
        "n_artists": len(artists), "n_tracks": len(tracks), "n_albums": len(albums),
        "new": new[:10], "n_new": len(new), "genres": genres.most_common(8),
        "months": months, "hours": hours, "peak_month": peak_m, "peak_hour": peak_h,
        "weekdays": [sum(1 for l in listens if l["when"].weekday() == d) for d in range(7)],
        "streak": longest_streak(days), "active_days": len(days), "top_day": top_day,
        "lib_songs": len(library), "lib_starred": sum(1 for s in library if s.get("starred")),
        "lib_top": lib_top, "never_played": sum(1 for s in library if not s.get("playCount")),
        "songs": songs,
    }


def build_index(site):
    """site/index.html: a card for every site/<period>/ that has a page, from the meta.json written next to it."""
    recaps = []
    for x in os.listdir(site):
        if os.path.isfile(os.path.join(site, x, "index.html")):
            try:
                recaps.append((x, json.load(open(os.path.join(site, x, "meta.json")))))
            except (OSError, ValueError):  # recaps built before meta.json existed still get a plain card
                recaps.append((x, {}))
    with open(os.path.join(site, "index.html"), "w") as f:
        f.write(index_page(recaps))


def period_range(year, month=None):
    """(first, last) unix second of a year, or of one month of it."""
    first = datetime(year, month or 1, 1)
    after = datetime(year + (month or 12) // 12, (month or 12) % 12 + 1, 1)
    return int(first.timestamp()), int(after.timestamp()) - 1


def slug(year, month=None):
    return f"{year}-{month:02d}" if month else str(year)


def history(env, start, end):
    """Listens in [start, end] from every configured source, cross-scrobbles merged."""
    sources = []
    if env("LB_USER"):
        sources.append(list(listenbrainz(env("LB_USER"), env("LB_TOKEN"), start, end)))
    if env("LASTFM_USER") and env("LASTFM_KEY"):
        sources.append(list(lastfm(env("LASTFM_USER"), env("LASTFM_KEY"), max(1, start), end)))
    if not sources:
        sys.exit("Set LB_USER and/or LASTFM_USER + LASTFM_KEY")
    return [l for l in merge(*sources) if start <= l["ts"] <= end]


def build(year, month, listens, prior, library, nd, out, seed=None):
    """Write one recap (index.html, media/, meta.json) to out."""
    end = period_range(year, month)[1]
    stats = compute(listens, library, prior)
    os.makedirs(out, exist_ok=True)
    media = fetch_media(nd, stats["songs"], out) if nd and listens else {}
    cover = (media.get("artist") or {}).get("cover") or (media.get("summary") or {}).get("cover")
    if cover:  # inline so the canvas export isn't blocked as cross-origin on file://
        media["card_art"] = "data:image/jpeg;base64," + base64.b64encode(open(os.path.join(out, cover), "rb").read()).decode()
    seed = int(seed) if seed is not None else secrets.randbits(64)
    with open(os.path.join(out, "index.html"), "w") as f:
        f.write(render(stats, year, media, seed, month))
    a_col, b_col = (g := Gen(seed)).palette[0]
    top = lambda k: stats[k][0][0] if stats[k] else None
    json.dump({"minutes": stats["minutes"], "plays": stats["plays"], "artist": top("artists"), "a": a_col, "b": b_col, "fg": g.fg,
               "cover": (media.get("artist") or media.get("summary") or {}).get("cover"), "partial": end > time.time(), "seed": seed},
              open(os.path.join(out, "meta.json"), "w"))
    print(f"{len(listens)} listens -> {out}/index.html (design seed {seed}, set THEME_SEED to keep it)")


def missing(site, first_ts, mode, now=None, empty=()):
    """Finished periods since the first listen with no recap in site yet. mode: monthly, yearly or both (REFRESH).
    empty: slugs known to have no listens (gaps in the history), which never get a recap."""
    now, d = now or datetime.now(), datetime.fromtimestamp(first_ts)
    out = []
    if mode != "yearly":
        y, m = d.year, d.month
        while (y, m) < (now.year, now.month):
            out.append((y, m))
            y, m = y + m // 12, m % 12 + 1
    if mode != "monthly":
        out += [(y, None) for y in range(d.year, now.year)]
    return [p for p in out if slug(*p) not in empty and not os.path.isfile(os.path.join(site, slug(*p), "index.html"))]


def backfill(env, site, mode, library, nd, seed=None):
    """Recaps for every finished month/year before now, from one pass over the whole history."""
    # first listen + months/years without listens; the past doesn't change (delete cache/ after big imports)
    path = os.path.join(CACHE, "backfill.json")
    seen = json.load(open(path)) if os.path.exists(path) else None
    if seen and not missing(site, seen["first"], mode, empty=set(seen["empty"])):
        return print("backfill: every past recap is already built")
    now = datetime.now()
    listens = history(env, 0, int(datetime(now.year, now.month, 1).timestamp()) - 1)
    if not listens:
        return print("backfill: no listens before this month")
    todo, empty = [], []
    for y, m in missing(site, listens[0]["ts"], mode):
        start, end = period_range(y, m)
        inside = [l for l in listens if start <= l["ts"] <= end]
        (todo if inside else empty).append((y, m, start, inside))
    os.makedirs(CACHE, exist_ok=True)
    json.dump({"first": listens[0]["ts"], "empty": [slug(y, m) for y, m, *_ in empty]}, open(path, "w"))
    print(f"backfill: building {len(todo)} past recaps" + (f", skipping {len(empty)} without listens" if empty else ""))
    for y, m, start, inside in todo:
        prior = {key(l["artist"])[0] for l in listens if l["ts"] < start}
        build(y, m, inside, prior, library, nd, os.path.join(site, slug(y, m)), seed)
        build_index(site)  # each one shows up on the overview as soon as it's done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=int(os.environ.get("YEAR") or datetime.now().year))
    ap.add_argument("--month", type=int, choices=range(1, 13), help="recap just this month instead of the whole year")
    ap.add_argument("--out", default="wrapped", help="output folder")
    ap.add_argument("--index", metavar="SITE", help="only rebuild SITE/index.html, the overview of the recaps in SITE/*/")
    ap.add_argument("--backfill", metavar="SITE", help="build every finished month/year (per REFRESH) missing from SITE/")
    ap.add_argument("--seed", type=int, default=os.environ.get("THEME_SEED") or None, help="reuse a previous design")
    a = ap.parse_args()
    if a.index:
        return build_index(a.index)
    env = os.environ.get
    if not (env("LB_USER") or (env("LASTFM_USER") and env("LASTFM_KEY"))):
        sys.exit("Set LB_USER and/or LASTFM_USER + LASTFM_KEY")
    # Navidrome first: a bad ND_URL should fail in seconds, not after minutes of history paging
    if env("ND_URL") and not (env("ND_USER") and env("ND_PASS")):
        sys.exit("ND_URL is set but ND_USER or ND_PASS is missing")
    nd = subsonic(env("ND_URL"), env("ND_USER"), env("ND_PASS")) if env("ND_URL") else None
    try:
        library = navidrome(nd) if nd else []
    except urllib.error.URLError as ex:
        sys.exit(f"Can't reach Navidrome at {env('ND_URL')}: {getattr(ex, 'reason', ex)}\n"
                 "In Docker, localhost is the container itself: use the server's LAN IP and Navidrome's host port.")
    if not nd:
        print("ND_URL not set: no slide audio, covers, durations or genres", file=sys.stderr)
    if a.backfill:
        return backfill(env, a.backfill, env("REFRESH") or "both", library, nd, a.seed)
    start, end = period_range(a.year, a.month)
    period = slug(a.year, a.month)
    prior = set()
    if env("LB_USER"):
        prior |= prior_artists(f"lb-{env('LB_USER')}-{period}", listenbrainz(env("LB_USER"), env("LB_TOKEN"), 0, start))
    if env("LASTFM_USER") and env("LASTFM_KEY"):
        prior |= prior_artists(f"lastfm-{env('LASTFM_USER')}-{period}", lastfm(env("LASTFM_USER"), env("LASTFM_KEY"), 1, start - 1))
    build(a.year, a.month, history(env, start, end), prior, library, nd, a.out, a.seed)


if __name__ == "__main__":
    main()
