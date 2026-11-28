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

from design import Gen, achievements, card_badges, index_page, render

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


def past(listens_before, prev_start):
    """What came before a period: {"last": {artist key: last listen ts}, "prev": {artist key: [name, plays since prev_start]}}."""
    last, prev = {}, {}
    for l in listens_before:
        k = key(l["artist"])[0]
        last[k] = max(last.get(k, 0), l["ts"])
        if l["ts"] >= prev_start and l["artist"]:
            prev.setdefault(k, [l["artist"], 0])[1] += 1
    return {"last": last, "prev": prev}


def past_cached(name, fetch, prev_start):
    """past() of fetch()'s listens, cached: the past doesn't change (delete cache/ after big imports)."""
    path = os.path.join(CACHE, f"past-{name}.json")
    if os.path.exists(path):
        return json.load(open(path))
    p = past(fetch(), prev_start)
    os.makedirs(CACHE, exist_ok=True)
    json.dump(p, open(path, "w"))
    return p


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


LOSSLESS = {"flac", "wav", "aiff", "aif", "ape", "wv", "dsf", "dff", "alac"}
GAP = 30 * 60  # silence longer than this (after a song ends) starts a new session


def sequence(listens):
    """Stats that only the order of listens gives: loop, longest session, segue, fling. listens sorted by ts."""
    out = {"loop": None, "session": None, "segue": None, "fling": None}
    if not listens:
        return out
    k = lambda l: key(l["artist"], l["title"])
    near = lambda a, b: b["ts"] - a["ts"] <= GAP + (a["secs"] or DEFAULT_SECS)
    best, run = (0, None), 1
    for i in range(1, len(listens) + 1):  # longest run of one song back to back, in one sitting
        if i < len(listens) and k(listens[i]) == k(listens[i - 1]) and near(listens[i - 1], listens[i]):
            run += 1
            continue
        if run > best[0]:
            best = (run, listens[i - 1])
        run = 1
    if best[0] >= 3:
        l = best[1]
        out["loop"] = {"title": l["title"], "artist": l["artist"], "n": best[0], "when": l["when"]}
    sessions, cur, segues = [], [listens[0]], Counter()
    for a, b in zip(listens, listens[1:]):
        if not near(a, b):
            sessions.append(cur)
            cur = []
        elif a["artist"] and b["artist"] and key(a["artist"]) != key(b["artist"]):
            segues[(a["artist"], b["artist"])] += 1
        cur.append(b)
    sessions.append(cur)
    ses = max(sessions, key=lambda x: x[-1]["ts"] - x[0]["ts"])
    path = list(dict.fromkeys(l["artist"] for l in ses if l["artist"]))
    if len(ses) >= 5:
        out["session"] = {"start": ses[0]["when"], "end": datetime.fromtimestamp(ses[-1]["ts"] + (ses[-1]["secs"] or DEFAULT_SECS)),
                          "plays": len(ses), "path": path, "ids": {id(l) for l in ses}}
    if segues and segues.most_common(1)[0][1] >= 3:
        out["segue"] = segues.most_common(1)[0]
    end, plays = listens[-1]["ts"], {}
    for l in listens:
        plays.setdefault(k(l), []).append(l)
    # a fling: at least 5 plays all inside one week, then nothing for the last 2+ weeks of the period
    flings = [p for p in plays.values() if len(p) >= 5 and p[-1]["ts"] - p[0]["ts"] <= 7 * 86400 and end - p[-1]["ts"] >= 14 * 86400]
    if flings:
        p = max(flings, key=len)
        out["fling"] = {"title": p[0]["title"], "artist": p[0]["artist"], "n": len(p), "start": p[0]["when"], "end": p[-1]["when"]}
    return out


def compute(listens, library, last=None, prev=None, start=None, end=None):
    """last: {artist key: last listen ts before the period}, prev: {artist key: [name, plays]} in the previous period
    (both from past()), start/end: the period's first and last second (comebacks, and the pace of one still running)."""
    last, prev = last or {}, prev or {}
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
    new = [(a, n) for a, n in artists.most_common() if key(a)[0] not in last]
    seq = sequence(listens)
    first_ts = {}
    for l in listens:
        first_ts.setdefault(key(l["artist"])[0], l["ts"])
    start = start or (listens[0]["ts"] if listens else 0)
    # comeback: heard before, then over a year of silence before this period
    back = sorted(((a, n, (first_ts[key(a)[0]] - last[key(a)[0]]) / 86400) for a, n in artists.most_common()
                   if key(a)[0] in last and start - last[key(a)[0]] >= 365 * 86400), key=lambda x: -x[1])
    cur = {key(a)[0]: (a, n) for a, n in artists.items()}
    rising = sorted(((a, prev[k][1], n) for k, (a, n) in cur.items() if k in prev and n > prev[k][1]), key=lambda x: x[1] - x[2])
    fading = sorted(((nm, p, cur.get(k, (0, 0))[1]) for k, (nm, p) in prev.items() if p > cur.get(k, (0, 0))[1]), key=lambda x: x[2] - x[1])
    years = sorted(int(l["song"]["year"]) for l in listens if l["song"] and l["song"].get("year"))
    fmts = Counter((l["song"].get("suffix") or "?").lower() for l in listens if l["song"])
    rates = [l["song"]["bitRate"] for l in listens if l["song"] and l["song"].get("bitRate")]
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
        "intro": pick(), "track": pick(), "summary": pick(), "minutes": pick(),
        "artist": pick(lambda l: l["artist"] == top_artist[0]),
        "album": pick(lambda l: (l["album"], l["artist"]) == first(albums)),
        "explore": pick(lambda l: l["artist"] == second[0]),
        "new": pick(lambda l: new and l["artist"] == new[0][0]),
        "genre": pick(lambda l: first(genres) in genres_of(l["song"])),
        "month": pick(lambda l: l["when"].month == peak_m),
        "hour": pick(lambda l: l["when"].hour == peak_h),
        "streak": pick(lambda l: top_day and l["when"].date() == top_day[0]),
        "library": lib_top[0] if lib_top and lib_top[0].get("playCount") else None, "badges": pick(),
        "guess": pick(),
        "signature": by_id.get(first(Counter(sid for sid, _ in {(l["song"]["id"], l["when"].date()) for l in listens if l["song"]}))),  # played on the most days
        "loyalty": pick(lambda l: l["artist"] == top_artist[0]),
        "comeback": pick(lambda l: back and l["artist"] == back[0][0]),
        "rising": pick(lambda l: rising and l["artist"] == rising[0][0]),
        "decade": pick(lambda l: years and (l["song"].get("year") or 0) // 10 == years[len(years) // 2] // 10),
        "session": pick(lambda l: seq["session"] and id(l) in seq["session"]["ids"]),
        "loop": pick(lambda l: seq["loop"] and (l["title"], l["artist"]) == (seq["loop"]["title"], seq["loop"]["artist"])),
        "segue": pick(lambda l: seq["segue"] and l["artist"] == seq["segue"][0][1]),
        "fling": pick(lambda l: seq["fling"] and (l["title"], l["artist"]) == (seq["fling"]["title"], seq["fling"]["artist"])),
        "audio": pick(lambda l: (l["song"].get("suffix") or "").lower() in LOSSLESS),
    }
    top5 = sum(n for _, n in artists.most_common(5))
    return {
        "plays": len(listens), "minutes": round(secs / 60),
        "artists": artists.most_common(10), "tracks": tracks.most_common(10), "albums": albums.most_common(10),
        "n_artists": len(artists), "n_tracks": len(tracks), "n_albums": len(albums),
        "new": new[:10], "n_new": len(new), "genres": genres.most_common(8), "n_genres": len(genres),
        "months": months, "hours": hours, "peak_month": peak_m, "peak_hour": peak_h,
        "weekdays": [sum(1 for l in listens if l["when"].weekday() == d) for d in range(7)],
        "streak": longest_streak(days), "active_days": len(days), "top_day": top_day,
        "lib_songs": len(library), "lib_starred": sum(1 for s in library if s.get("starred")),
        "lib_top": lib_top, "never_played": sum(1 for s in library if not s.get("playCount")),
        "songs": songs, **seq,
        "loyalty": top5 / len(listens) if listens else 0,
        "comebacks": back[:6], "rising": rising[:5], "fading": fading[:5],
        "years": years, "median_year": years[len(years) // 2] if years else None,
        "formats": fmts.most_common(5), "lossless": sum(n for f, n in fmts.items() if f in LOSSLESS) / max(1, sum(fmts.values())),
        "bitrate": round(sum(rates) / len(rates)) if rates else None,
        # plays vs the previous period, at this period's pace if it isn't over yet (plays, not minutes: both sides count the same way)
        "trend": (len(listens) / min(1, max(.05, (time.time() - start) / (end - start))) / prev_plays - 1
                  if (prev_plays := sum(n for _, n in prev.values())) and end else None),
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


def prev_start(year, month=None):
    """First second of the period before this one (the month or year before)."""
    return period_range(*((year - (month == 1), (month - 2) % 12 + 1) if month else (year - 1,)))[0]


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
    """Write one recap (index.html, media/, meta.json) to out. prior: past() of the listens before it."""
    start, end = period_range(year, month)
    stats = compute(listens, library, prior["last"], prior["prev"], start, end)
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
               "cover": (media.get("artist") or media.get("summary") or {}).get("cover"), "partial": end > time.time(), "seed": seed,
               # a month's badges for its overview card; the year's card rolls them up from these
               "badges": [[n, hue, ic, tier] for n, hue, ic, tier, _ in achievements(stats)] if month and listens else None,
               "ranks": card_badges(stats) if not month and listens else None, "sig": 1},  # the year's rank emblems for its card
              open(os.path.join(out, "meta.json"), "w"))
    print(f"{len(listens)} listens -> {out}/index.html (design seed {seed}, set THEME_SEED to keep it)")


def built_meta(site, y, m):
    """meta.json of an up-to-date recap in site, else None (not built, or built before meta.json carried badges / a year its signature badge)."""
    try:
        meta = json.load(open(os.path.join(site, slug(y, m), "meta.json")))
    except (OSError, ValueError):
        return None
    return meta if "badges" in meta and (m or "sig" in meta) and os.path.isfile(os.path.join(site, slug(y, m), "index.html")) else None


def missing(site, first_ts, mode, now=None, empty=()):
    """Finished periods since the first listen with no up-to-date recap in site yet. mode: monthly, yearly or both (REFRESH).
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
    return [p for p in out if slug(*p) not in empty and not built_meta(site, *p)]


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
        try:  # an outdated recap keeps its design when rebuilt
            old = json.load(open(os.path.join(site, slug(y, m), "meta.json"))).get("seed")
        except (OSError, ValueError):
            old = None
        prior = past((l for l in listens if l["ts"] < start), prev_start(y, m))
        build(y, m, inside, prior, library, nd, os.path.join(site, slug(y, m)), seed if seed is not None else old)
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
    # everything before the period, both sources merged so cross-scrobbles don't double the previous period's plays
    lb, fm = env("LB_USER"), env("LASTFM_USER") and env("LASTFM_KEY") and env("LASTFM_USER")
    fetch = lambda: merge(*([listenbrainz(lb, env("LB_TOKEN"), 0, start)] if lb else []),
                          *([lastfm(fm, env("LASTFM_KEY"), 1, start - 1)] if fm else []))
    prior = past_cached(f"{'lb-' + lb + '-' if lb else ''}{'lastfm-' + fm + '-' if fm else ''}{period}", fetch, prev_start(a.year, a.month))
    build(a.year, a.month, history(env, start, end), prior, library, nd, a.out, a.seed)


if __name__ == "__main__":
    main()
