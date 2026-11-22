from datetime import date, datetime
from wrapped import compute, longest_streak, merge, render

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
print("ok")
