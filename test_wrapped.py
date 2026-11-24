from datetime import date, datetime
from design import Gen, contrast, render
from wrapped import compute, longest_streak, merge

ts = int(datetime(2026, 3, 1, 20).timestamp())
lb = [{"ts": ts, "artist": "A", "title": "Song", "album": "X", "secs": 200},
      {"ts": ts + 86400, "artist": "B", "title": "Other", "album": "Y", "secs": None}]
fm = [{"ts": ts + 30, "artist": "a", "title": "song ", "album": "X", "secs": None}]  # cross-scrobble dupe

listens = merge(lb, fm)
assert len(listens) == 2, listens
assert longest_streak([date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 4)]) == 2

lib = [{"id": "s1", "artist": "B", "title": "Other", "duration": 100, "genre": "Rock;Pop", "playCount": 3, "starred": "x"}]
s = compute(listens, lib, prior={"a"})
assert s["plays"] == 2 and s["minutes"] == 5  # 200s + 100s from navidrome
assert dict(s["genres"]) == {"Rock": 1, "Pop": 1}
assert s["streak"] == 2 and s["lib_starred"] == 1
assert s["new"] == [("B", 1)] and s["n_new"] == 1  # A was heard before the year
assert s["songs"]["new"]["id"] == "s1" and s["songs"]["artist"] is None  # A isn't in the library
page = render(s, 2026, {"new": {"title": "Other", "artist": "B", "audio": "media/s1.mp3", "cover": "media/s1.jpg"}})
assert 'data-n="5"' in page and 'data-audio="media/s1.mp3"' in page and "artists discovered" in page and "Top Artists" in page
# designs: reproducible by seed, different across seeds, always readable
assert render(s, 2026, seed=42) == render(s, 2026, seed=42)
assert len({render(s, 2026, seed=i) for i in range(30)}) == 30
for i in range(300):
    g = Gen(i)
    assert all(contrast(c, g.fg) >= 5 for pair in g.palette for c in pair), (i, g.palette)
    assert contrast(g.card["accent"], g.card["ink"]) >= 3, i
assert "design seed 7" in render(s, 2026, seed=7)
assert {Gen(i).card["layout"] for i in range(200)} >= {"polaroid", "type"}
for i in range(120):  # every roster entry gets drawn somewhere in here; they must all render
    render(s, 2026, seed=i)
nov = render(s, 2026, seed=1, month=11)
assert "Your November 2026 in music" in nov and "song of the month" in nov and "peak month" not in nov and "data-year=2026-11" in nov
print("ok")
# overview: year card first, months newest first, recaps without meta.json still listed
import json, os, tempfile
from wrapped import build_index
site = tempfile.mkdtemp()
for slug, meta in (("2026", {"minutes": 34011, "artist": "A&B", "partial": True}), ("2026-10", None), ("2026-11", {"minutes": 900})):
    os.makedirs(f"{site}/{slug}")
    open(f"{site}/{slug}/index.html", "w").write("x")
    if meta:
        json.dump(meta, open(f"{site}/{slug}/meta.json", "w"))
build_index(site)
idx = open(f"{site}/index.html").read()
assert idx.index('href="2026/"') < idx.index('href="2026-11/"') < idx.index('href="2026-10/"'), idx
assert "34,011" in idx and "A&amp;B" in idx and "in progress" in idx and "3 recaps" in idx
print("index ok")
# backfill: which finished periods are missing, per REFRESH mode
import wrapped
from wrapped import missing
first, now = datetime(2025, 11, 15).timestamp(), datetime(2026, 2, 10)
site = tempfile.mkdtemp()
assert missing(site, first, "both", now) == [(2025, 11), (2025, 12), (2026, 1), (2025, None)]
assert missing(site, first, "yearly", now) == [(2025, None)]
os.makedirs(f"{site}/2025-12"); open(f"{site}/2025-12/index.html", "w").write("x")
assert missing(site, first, "monthly", now) == [(2025, 11), (2026, 1)]  # already built: skipped
# whole flow on fake history: one recap per past month, artists from earlier months aren't "new"
hist = [{"ts": int(datetime(2025, 11, 3).timestamp()), "artist": "Old", "title": "a", "album": "x", "secs": 200},
        {"ts": int(datetime(2025, 12, 3).timestamp()), "artist": "Old", "title": "a", "album": "x", "secs": 200},
        {"ts": int(datetime(2025, 12, 4).timestamp()), "artist": "Fresh", "title": "b", "album": "y", "secs": 200}]
wrapped.history = lambda env, start, end: [dict(l) for l in hist if start <= l["ts"] <= end]
wrapped.CACHE = tempfile.mkdtemp()
site = tempfile.mkdtemp()
wrapped.backfill(lambda k: None, site, "monthly", [], None, seed=1)
built = sorted(x for x in os.listdir(site) if os.path.isdir(f"{site}/{x}"))
assert built == ["2025-11", "2025-12"], built  # months without listens get no recap
dec = open(f"{site}/2025-12/index.html").read()
assert "New to you in December 2025" in dec and "Your biggest find: <b>Fresh</b>" in dec, "Old was heard in November"
assert os.path.isfile(f"{site}/index.html")
calls = []
wrapped.history = lambda *a: calls.append(a) or []
wrapped.backfill(lambda k: None, site, "monthly", [], None)  # all built or known empty: no history fetch at all
assert not calls, calls
print("backfill ok")
