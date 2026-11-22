#!/usr/bin/env python3
"""Music Wrapped from ListenBrainz + Last.fm + Navidrome. Stdlib only.

Config via env vars (each source optional, set at least one of LB/Last.fm):
  LB_USER, LB_TOKEN (optional)          ListenBrainz
  LASTFM_USER, LASTFM_KEY               Last.fm (key: https://www.last.fm/api/account/create)
  ND_URL, ND_USER, ND_PASS              Navidrome (durations, genres, library stats, slide audio)

Usage: python3 wrapped.py [--year 2026] [--out wrapped]
Output is a self-contained folder (index.html + media/) - zip it or put it on any static host to share.
"""
import argparse, base64, hashlib, html, json, os, secrets, sys, time, urllib.parse, urllib.request
from collections import Counter
from datetime import datetime, timedelta

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


# ---------- render ----------

e = lambda s: html.escape(str(s))
num = lambda n: f'<h1 data-n="{n}">{n:,}</h1>'


def bars(values, labels):
    mx = max(values) or 1
    return '<div class="bars">' + "".join(
        f'<div class="bar" title="{e(l)}: {v}" style="--i:{i}"><i style="height:{v / mx * 100:.0f}%"></i><span>{e(l)}</span></div>'
        for i, (v, l) in enumerate(zip(values, labels))) + "</div>"


def top_list(items, fmt):
    return "<ol>" + "".join(f'<li style="--i:{i}">{fmt(k)}<b>{n}</b></li>' for i, (k, n) in enumerate(items)) + "</ol>"


CSS = """
html{scroll-snap-type:y mandatory;scroll-behavior:smooth}body{margin:0;font:18px system-ui,sans-serif;color:#fff;background:#000}
section{position:relative;overflow:hidden;min-height:100vh;scroll-snap-align:start;display:grid;place-items:center;padding:24px 24px 110px;box-sizing:border-box;
  background:linear-gradient(135deg,var(--a),var(--b),var(--a));background-size:300% 300%;animation:drift 14s ease-in-out infinite alternate}
@keyframes drift{to{background-position:100% 100%}}
.bg{position:absolute;inset:-10%;width:120%;height:120%;object-fit:cover;filter:blur(40px) saturate(1.4);opacity:0;mix-blend-mode:soft-light;transition:opacity 1.5s}
.in .bg{opacity:.9;animation:ken 20s ease-in-out infinite alternate}@keyframes ken{to{transform:scale(1.15) rotate(3deg)}}
section>div{position:relative;max-width:640px;width:100%}
section>div>*{opacity:0;transform:translateY(40px);transition:opacity .7s,transform .9s cubic-bezier(.16,1,.3,1)}
.in>div>*{opacity:1;transform:none}
.in>div>:nth-child(2){transition-delay:.12s}.in>div>:nth-child(3){transition-delay:.24s}.in>div>:nth-child(4){transition-delay:.36s}.in>div>:nth-child(n+5){transition-delay:.48s}
h1{font-size:clamp(40px,10vw,88px);margin:.1em 0;line-height:1;overflow-wrap:anywhere;font-weight:900;letter-spacing:-.02em}
small{text-transform:uppercase;letter-spacing:.15em;opacity:.85}.sub{opacity:.85}em{opacity:.75;font-style:normal;margin-left:.4em}
ol{padding:0;list-style:none;counter-reset:n}
li{counter-increment:n;display:flex;gap:.6em;padding:.35em 0;border-bottom:1px solid #fff3;opacity:0;transform:translateX(-30px);
  transition:opacity .5s,transform .6s cubic-bezier(.16,1,.3,1);transition-delay:calc(.4s + var(--i)*70ms)}
.in li{opacity:1;transform:none}li::before{content:counter(n);opacity:.6;width:1.5em}li b{margin-left:auto;opacity:.8}
.bars{display:flex;gap:3px;height:140px;align-items:flex-end;margin:1em 0}.bar{flex:1;height:100%;display:flex;flex-direction:column;justify-content:flex-end;align-items:center}
.bar i{display:block;width:100%;background:#fffc;border-radius:3px 3px 0 0;min-height:2px;transform:scaleY(0);transform-origin:bottom;
  transition:transform .8s cubic-bezier(.34,1.56,.64,1);transition-delay:calc(.3s + var(--i)*35ms)}
.in .bar i{transform:none}.bar span{font-size:12px;height:1.2em;opacity:.8}
.np{position:absolute;left:24px;right:24px;bottom:24px;margin:0;display:flex;gap:12px;align-items:center;font-size:14px;opacity:0;transform:translateY(20px);transition:all .8s .8s}
.in .np{opacity:1;transform:none}.np img{width:52px;height:52px;border-radius:50%;box-shadow:0 4px 20px #0006;animation:spin 8s linear infinite paused}
.playing .np img{animation-play-state:running}@keyframes spin{to{transform:rotate(1turn)}}
button{font:inherit;color:#000;background:#fff;border:0;border-radius:99px;padding:.7em 1.6em;font-weight:700;cursor:pointer;transition:transform .2s}
button:hover{transform:scale(1.06)}button:focus-visible{outline:3px solid #fff;outline-offset:3px}
#mute{position:fixed;top:16px;right:16px;z-index:9;padding:.5em .9em;background:#fffd}
#dots{position:fixed;right:14px;top:50%;transform:translateY(-50%);display:grid;gap:8px;z-index:9}
#dots i{width:6px;height:6px;border-radius:9px;background:#fff6;transition:all .4s}#dots i.on{background:#fff;height:22px}
.card{width:min(400px,100%);margin:auto;background:#f1f0eb;color:#111;border-radius:22px;overflow:hidden;box-shadow:0 30px 80px #0006}
.summary>div>.card{transform:translateY(120px) rotate(-8deg) scale(.85);transition:opacity .6s,transform 1.2s cubic-bezier(.34,1.56,.64,1)}
.in.summary>div>.card{transform:none}
.art{position:relative;aspect-ratio:1/.85;background:repeating-conic-gradient(#111 0 25%,#fff 0 50%) 0 0/32px 32px;animation:checker 8s linear infinite}
@keyframes checker{to{background-position:64px 0}}
.art img,.art .ph{position:absolute;top:7%;left:20%;width:73%;height:86%;object-fit:cover;box-sizing:border-box}
.art .ph{display:grid;place-items:center;background:#111;color:#fff;font:900 32px system-ui;padding:12px;text-align:center}
.in .art img{animation:breathe 6s ease-in-out infinite alternate}@keyframes breathe{to{transform:scale(1.04)}}
.yr{position:absolute;left:0;top:0;bottom:0;width:20%;background:var(--c);writing-mode:vertical-rl;transform:rotate(180deg);
  display:flex;align-items:center;justify-content:center;font:900 clamp(44px,13vw,78px)/1 system-ui;letter-spacing:-.04em;color:transparent;-webkit-text-stroke:2px #111}
.info{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:18px 16px;padding:22px 22px 6px}
.info small{font-size:11px;letter-spacing:0;text-transform:none;opacity:.65}
.mini{margin:.4em 0 0;font-weight:700;font-size:15px}
.mini li{display:block;border:0;padding:.08em 0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.mini li::before{margin-right:.4em}
.info strong{display:block;font-size:30px;font-weight:900;margin-top:.15em;overflow-wrap:anywhere;line-height:1.05}
.card footer{display:flex;justify-content:space-between;align-items:center;padding:14px 22px 20px;font-weight:800;font-size:13px;letter-spacing:.06em}
.save{text-align:center;margin-top:24px}
.logo{width:32px;height:32px;border-radius:50%;background:#111;color:#fff;display:grid;place-items:center}
@media (prefers-reduced-motion:reduce){*,*::before{animation:none!important;transition:none!important}html{scroll-behavior:auto}}
"""

JS = """
const secs=[...document.querySelectorAll('section')],dots=document.getElementById('dots'),mute=document.getElementById('mute');
secs.forEach(()=>dots.append(document.createElement('i')));
const players={};let sound=false,cur=null;
function fade(a,to){const from=a.volume,t0=performance.now();cancelAnimationFrame(a._f);
  (function f(t){const k=Math.min(1,(t-t0)/700);a.volume=from+(to-from)*k;if(k<1)a._f=requestAnimationFrame(f);else if(!to)a.pause()})(t0)}
function play(sec){
  const src=sec&&sec.dataset.audio,next=src&&(players[src]||=Object.assign(new Audio(src),{loop:true,volume:0}));
  if(next&&!next._seeked)next.addEventListener('loadedmetadata',()=>{next.currentTime=next.duration*.35},{once:true}),next._seeked=1;
  if(cur&&cur!==next)fade(cur,0);
  if(next&&sound){next.play().catch(()=>{});fade(next,1)}
  cur=next||null;secs.forEach(s=>s.classList.toggle('playing',sound&&s===sec&&!!next));
}
function count(h){const n=+h.dataset.n,t0=performance.now();
  if(matchMedia('(prefers-reduced-motion:reduce)').matches)return;
  (function f(t){const k=Math.min(1,(t-t0)/1400);h.textContent=Math.round(n*(1-Math.pow(1-k,4))).toLocaleString();if(k<1)requestAnimationFrame(f)})(t0)}
let active=null;
const io=new IntersectionObserver(es=>es.forEach(en=>{
  en.target.classList.toggle('in',en.isIntersecting);
  if(!en.isIntersecting)return;
  active=en.target;
  [...dots.children].forEach((d,i)=>d.className=secs[i]===active?'on':'');
  active.querySelectorAll('[data-n]').forEach(count);play(active);
}),{threshold:.55});
secs.forEach(s=>io.observe(s));
function setSound(on){sound=on;mute.textContent=on?'🔊':'🔇';mute.setAttribute('aria-label',on?'Mute':'Unmute');play(active)}
mute.onclick=()=>setSound(!sound);
document.getElementById('start').onclick=()=>{setSound(true);secs[1]&&secs[1].scrollIntoView()};
// Save image: redraw the summary card on a canvas (no libs, works offline), share on mobile / download on desktop.
document.getElementById('save').onclick=async ev=>{
  const btn=ev.currentTarget,W=400,H=660,k=2.7,cv=document.createElement('canvas');btn.disabled=true;
  cv.width=W*k;cv.height=H*k;const c=cv.getContext('2d');c.scale(k,k);
  const fit=(t,w)=>{t=String(t);if(c.measureText(t).width<=w)return t;while(t&&c.measureText(t+'…').width>w)t=t.slice(0,-1);return t+'…'};
  c.beginPath();c.roundRect(0,0,W,H,22);c.clip();c.fillStyle='#f1f0eb';c.fillRect(0,0,W,H);
  for(let y=0;y<340;y+=16)for(let x=80;x<W;x+=16){c.fillStyle=(x+y)/16%2?'#fff':'#111';c.fillRect(x,y,16,16)}
  c.fillStyle=CARD.accent;c.fillRect(0,0,80,340);
  c.save();c.translate(40,170);c.rotate(-Math.PI/2);c.font='900 72px system-ui';c.textAlign='center';c.textBaseline='middle';
  c.lineWidth=2;c.strokeStyle='#111';c.strokeText(CARD.year,0,0);c.restore();
  const ix=80,iy=24,iw=292,ih=292;
  if(CARD.art){const img=new Image();img.src=CARD.art;await img.decode();
    const s=Math.max(iw/img.width,ih/img.height),sw=iw/s,sh=ih/s;c.drawImage(img,(img.width-sw)/2,(img.height-sh)/2,sw,sh,ix,iy,iw,ih)}
  else{c.fillStyle='#111';c.fillRect(ix,iy,iw,ih);c.fillStyle='#fff';c.font='900 30px system-ui';c.textAlign='center';c.fillText(fit(CARD.name,iw-24),ix+iw/2,iy+ih/2);c.textAlign='left'}
  const col=[22,208],cw=170,label=(t,x,y)=>{c.globalAlpha=.65;c.font='11px system-ui';c.fillText(t,x,y);c.globalAlpha=1};
  let y=372;c.fillStyle='#111';
  [['Top Artists',CARD.artists],['Top Songs',CARD.songs]].forEach(([t,xs],i)=>{label(t,col[i],y);
    xs.forEach((s,j)=>{const yy=y+26+j*21;c.font='700 15px system-ui';c.globalAlpha=.6;c.fillText(j+1,col[i],yy);c.globalAlpha=1;c.fillText(fit(s,cw-18),col[i]+16,yy)})});
  y+=160;label('Minutes Listened',col[0],y);label(CARD.label,col[1],y);
  c.font='900 30px system-ui';c.fillText(CARD.minutes.toLocaleString(),col[0],y+34);c.fillText(fit(CARD.value,cw),col[1],y+34);
  c.beginPath();c.arc(38,H-38,16,0,7);c.fill();c.fillStyle='#fff';c.font='16px system-ui';c.textAlign='center';c.textBaseline='middle';c.fillText('♪',38,H-37);
  c.fillStyle='#111';c.textAlign='right';c.font='800 13px system-ui';c.letterSpacing='1px';c.fillText(`MY ${CARD.year} WRAPPED`,W-22,H-37);
  const blob=await new Promise(r=>cv.toBlob(r,'image/png')),file=new File([blob],`wrapped-${CARD.year}.png`,{type:'image/png'});
  btn.disabled=false;
  if(navigator.canShare?.({files:[file]}))try{await navigator.share({files:[file]});return}catch(err){if(err.name==='AbortError')return}
  const a=Object.assign(document.createElement('a'),{href:URL.createObjectURL(blob),download:file.name});a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);
};
document.addEventListener('keydown',ev=>{const i=secs.indexOf(active);
  if(['ArrowDown','PageDown',' '].includes(ev.key)&&secs[i+1]){ev.preventDefault();secs[i+1].scrollIntoView()}
  if(['ArrowUp','PageUp'].includes(ev.key)&&secs[i-1]){ev.preventDefault();secs[i-1].scrollIntoView()}});
"""


def render(s, year, media=None):
    media = media or {}
    if not s["plays"]:
        return f"<h1>No listens found for {year}.</h1>"
    wd = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    a1, t1 = s["artists"][0], s["tracks"][0]
    cards = [
        ("intro", "#ff4e50,#f9d423", f"<small>Your {year} in music</small>{num(s['minutes'])}<p>minutes listened</p>"
                                     f"<p class=sub>{s['plays']:,} plays · {s['active_days']} active days · "
                                     f"{s['minutes'] / 60 / 24:.1f} days of audio</p><p><button id=start>▶ Play my Wrapped</button></p>"),
        ("artist", "#8e2de2,#4a00e0", f"<small>Your top artist</small><h1>{e(a1[0])}</h1><p>{a1[1]} plays</p>"
                                      + top_list(s["artists"][1:10], e)),
        ("track", "#11998e,#38ef7d", f"<small>Your song of the year</small><h1>{e(t1[0][0])}</h1><p>{e(t1[0][1])} · {t1[1]} plays</p>"
                                     + top_list(s["tracks"][1:10], lambda k: f"{e(k[0])} <em>{e(k[1])}</em>")),
        ("album", "#fc466b,#3f5efb", "<small>Top albums</small>" + top_list(s["albums"][:10], lambda k: f"{e(k[0])} <em>{e(k[1])}</em>")),
        ("explore", "#f7971e,#ffd200", f"<small>You explored</small>{num(s['n_artists'])}<p>artists</p>"
                                       f"<p class=sub>{s['n_tracks']:,} tracks · {s['n_albums']:,} albums</p>"),
    ]
    if s["new"]:
        cards.append(("new", "#00b09b,#96c93d", f"<small>New to you in {year}</small>{num(s['n_new'])}<p>artists discovered</p>"
                                                f"<p class=sub>Your biggest find: <b>{e(s['new'][0][0])}</b></p>" + top_list(s["new"][:8], e)))
    if s["genres"]:
        cards.append(("genre", "#00c6ff,#0072ff", f"<small>Your top genre</small><h1>{e(s['genres'][0][0])}</h1>"
                                                  + top_list(s["genres"][1:], e)))
    cards += [
        ("month", "#ee0979,#ff6a00", f"<small>Your peak month</small><h1>{datetime(year, s['peak_month'], 1):%B}</h1>"
                                     + bars(s["months"], "JFMAMJJASOND")),
        ("hour", "#1d2b64,#f8cdda", f"<small>Your listening hour</small><h1>{s['peak_hour']:02d}:00</h1>"
                                    + bars(s["hours"], [f"{h}" if h % 6 == 0 else "" for h in range(24)])
                                    + bars(s["weekdays"], wd)),
        ("streak", "#c94b4b,#4b134f", f"<small>Longest streak</small>{num(s['streak'])}<p>days in a row with music</p>"
                                      + (f"<p class=sub>Biggest day: {s['top_day'][0]:%d %B} with {s['top_day'][1]} plays</p>" if s["top_day"] else "")),
    ]
    if s["lib_songs"]:
        cards.append(("library", "#283c86,#45a247", f"<small>Your Navidrome library</small>{num(s['lib_songs'])}<p>songs</p>"
                      f"<p class=sub>{s['lib_starred']:,} starred · {s['never_played']:,} never played</p>"
                      "<p>All-time most played on your server:</p>"
                      + top_list([(x, x.get("playCount", 0)) for x in s["lib_top"]],
                                 lambda x: f"{e(x.get('title'))} <em>{e(x.get('artist'))}</em>")))
    art = media.get("card_art") or (media.get("artist") or {}).get("cover") or (media.get("summary") or {}).get("cover")
    mini = lambda xs: "<ol class=mini>" + "".join(f'<li style="--i:{i}">{e(x)}</li>' for i, x in enumerate(xs)) + "</ol>"
    last_label, last_value = ("Top Genre", s["genres"][0][0]) if s["genres"] else ("New Artists", f"{s['n_new']:,}")
    accent = ["#e8c21a", "#8f8cff", "#ff4b2b", "#7ed321"][year % 4]
    card = {"year": str(year), "accent": accent, "artists": [a for a, _ in s["artists"][:5]],
            "songs": [t for (t, _), _ in s["tracks"][:5]], "minutes": s["minutes"], "label": last_label,
            "value": last_value, "name": a1[0], "art": media.get("card_art")}
    last_value = e(last_value)
    cards.append(("summary", "#8f8cff,#b3a6ff", f"""<div class=card style="--c:{accent}">
      <div class=art><span class=yr>{year}</span>{f'<img src="{e(art)}" alt="">' if art else f'<div class=ph>{e(a1[0])}</div>'}</div>
      <div class=info>
        <div><small>Top Artists</small>{mini(a for a, _ in s["artists"][:5])}</div>
        <div><small>Top Songs</small>{mini(t for (t, _), _ in s["tracks"][:5])}</div>
        <div><small>Minutes Listened</small><strong data-n="{s['minutes']}">{s['minutes']:,}</strong></div>
        <div><small>{last_label}</small><strong>{last_value}</strong></div>
      </div>
      <footer><span class=logo aria-hidden=true>♪</span>MY {year} WRAPPED</footer></div>
      <p class=save><button id=save>⬇ Save image</button></p>
      <script>const CARD={json.dumps(card).replace("</", "<\\/")}</script>"""))
    body = ""
    for slide, grad, content in cards:
        m = media.get(slide, {})
        a, b = grad.split(",")
        attr = f' data-audio="{e(m["audio"])}"' if m.get("audio") else ""
        img = f'src="{e(m["cover"])}" alt=""' if m.get("cover") else ""
        bg = f"<img class=bg {img}>" if img else ""
        np = (f"<figure class=np>{f'<img {img}>' if img else ''}"
              f'<figcaption>♪ {e(m["title"])}<br><em>{e(m["artist"])}</em></figcaption></figure>') if m.get("audio") else ""
        body += f'<section class={slide} style="--a:{a};--b:{b}"{attr}>{bg}<div>{content}</div>{np}</section>'
    return (f'<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">'
            f'<title>Wrapped {year}</title><style>{CSS}</style><button id=mute aria-label=Unmute>🔇</button><nav id=dots aria-hidden=true></nav>'
            f'{body}<script>{JS}</script></html>')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=int(os.environ.get("YEAR") or datetime.now().year))
    ap.add_argument("--out", default="wrapped", help="output folder")
    a = ap.parse_args()
    start, end = int(datetime(a.year, 1, 1).timestamp()), int(datetime(a.year + 1, 1, 1).timestamp()) - 1
    env = os.environ.get
    sources, prior = [], set()
    if env("LB_USER"):
        sources.append(list(listenbrainz(env("LB_USER"), env("LB_TOKEN"), start, end)))
        prior |= prior_artists(f"lb-{env('LB_USER')}-{a.year}", listenbrainz(env("LB_USER"), env("LB_TOKEN"), 0, start))
    if env("LASTFM_USER") and env("LASTFM_KEY"):
        sources.append(list(lastfm(env("LASTFM_USER"), env("LASTFM_KEY"), start, end)))
        prior |= prior_artists(f"lastfm-{env('LASTFM_USER')}-{a.year}", lastfm(env("LASTFM_USER"), env("LASTFM_KEY"), 1, start - 1))
    if not sources:
        sys.exit("Set LB_USER and/or LASTFM_USER + LASTFM_KEY")
    nd = subsonic(env("ND_URL"), env("ND_USER"), env("ND_PASS")) if env("ND_URL") else None
    library = navidrome(nd) if nd else []
    listens = [l for l in merge(*sources) if start <= l["ts"] <= end]
    stats = compute(listens, library, prior)
    os.makedirs(a.out, exist_ok=True)
    media = fetch_media(nd, stats["songs"], a.out) if nd and listens else {}
    cover = (media.get("artist") or {}).get("cover") or (media.get("summary") or {}).get("cover")
    if cover:  # inline so the canvas export isn't blocked as cross-origin on file://
        media["card_art"] = "data:image/jpeg;base64," + base64.b64encode(open(os.path.join(a.out, cover), "rb").read()).decode()
    with open(os.path.join(a.out, "index.html"), "w") as f:
        f.write(render(stats, a.year, media))
    print(f"{len(listens)} listens -> {a.out}/index.html")


if __name__ == "__main__":
    main()
