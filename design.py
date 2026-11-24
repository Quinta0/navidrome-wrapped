"""Procedural design for navidrome-wrapped.

Every render grows its own design from a seed: palette, typography, a motion vocabulary
(generated @keyframes), generated SVG decorations, and for every slide which component
variant shows each piece of data and how it's laid out. Same seed -> same design.
"""
import base64, colorsys, html, json, math, os, random
from datetime import datetime

e = lambda s: html.escape(str(s))


# ---------- colour ----------

def hexc(h, l, s):
    return "#%02x%02x%02x" % tuple(round(c * 255) for c in colorsys.hls_to_rgb(h % 1, l, s))


def lum(hx):
    c = [int(hx[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = [x / 12.92 if x <= .03928 else ((x + .055) / 1.055) ** 2.4 for x in c]
    return .2126 * r + .7152 * g + .0722 * b


def contrast(x, y):
    a, b = sorted((lum(x), lum(y)))
    return (b + .05) / (a + .05)


def readable(h, l, s, fg, ratio=5.0):
    """Nudge lightness away from fg until the colour reaches the contrast ratio (5 > WCAG AA 4.5, headroom for decor)."""
    step = -.02 if lum(fg) > .5 else .02
    while contrast(hexc(h, l, s), fg) < ratio and 0 < l < 1:
        l += step
    return hexc(h, max(0, min(1, l)), s)


FONTS = {  # system font stacks (modernfontstacks.com): distinct looks, no downloads, works offline
    "grotesk": "Inter, Roboto, 'Helvetica Neue', 'Arial Nova', 'Nimbus Sans', Arial, sans-serif",
    "geometric": "Avenir, Montserrat, Corbel, 'URW Gothic', source-sans-pro, sans-serif",
    "humanist": "Seravek, 'Gill Sans Nova', Ubuntu, Calibri, 'DejaVu Sans', source-sans-pro, sans-serif",
    "rounded": "ui-rounded, 'Hiragino Maru Gothic ProN', Quicksand, Comfortaa, Manjari, 'Arial Rounded MT', Calibri, sans-serif",
    "system": "system-ui, sans-serif",
    "transitional": "Charter, 'Bitstream Charter', 'Sitka Text', Cambria, serif",
    "oldstyle": "'Iowan Old Style', 'Palatino Linotype', 'URW Palladio L', P052, serif",
    "industrial": "Bahnschrift, 'DIN Alternate', 'Franklin Gothic Medium', 'Nimbus Sans Narrow', sans-serif-condensed, sans-serif",
    "didone": "Didot, 'Bodoni MT', 'Noto Serif Display', 'URW Palladio L', P052, Sylfaen, serif",
    "slab": "Rockwell, 'Rockwell Nova', 'Roboto Slab', 'DejaVu Serif', 'Sitka Small', serif",
    "mono": "ui-monospace, 'Cascadia Code', 'Source Code Pro', Menlo, Consolas, 'DejaVu Sans Mono', monospace",
    "hand": "'Segoe Print', 'Bradley Hand', Chilanka, TSCu_Comic, casual, cursive",
}
BODY_FONTS = ["grotesk", "geometric", "humanist", "rounded", "system", "transitional", "oldstyle"]
BACKGROUNDS = [  # per-section background from its own --a/--b, and the size the drift animation moves within
    ("linear-gradient({ang}deg,var(--a),var(--b),var(--a))", "300% 300%"),
    ("radial-gradient(circle at 30% 30%,var(--b),var(--a) 65%)", "200% 200%"),
    ("radial-gradient(at 15% 20%,var(--b) 0,transparent 50%),radial-gradient(at 85% 75%,var(--b) 0,transparent 45%),var(--a)", "160% 160%"),
    ("conic-gradient(from {ang}deg at 50% 50%,var(--a),var(--b),var(--a))", "220% 220%"),
    ("linear-gradient({ang}deg,var(--a) 50%,var(--b) 50%)", "250% 250%"),
    ("repeating-linear-gradient({ang}deg,var(--a) 0 40px,var(--b) 40px 80px)", "200% 200%"),
    ("repeating-radial-gradient(circle at 20% 80%,var(--a) 0 30px,var(--b) 30px 60px)", "180% 180%"),
    ("linear-gradient({ang}deg,var(--b) 0 33%,var(--a) 33% 66%,var(--b) 66%)", "250% 250%"),
    ("radial-gradient(ellipse at 50% 120%,var(--b),transparent 60%),linear-gradient(var(--a),var(--a))", "140% 140%"),
    ("repeating-conic-gradient(from {ang}deg at 50% 50%,var(--a) 0 15deg,var(--b) 15deg 30deg)", "200% 200%"),
]
FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
try:  # bundled OFL variable fonts (scripts/fetch_fonts.py); without them we fall back to system stacks
    MANIFEST = json.load(open(os.path.join(FONT_DIR, "manifest.json")))
except FileNotFoundError:
    MANIFEST = {}
FALLBACK = {"Serif": "transitional", "Sans Serif": "grotesk", "Display": "grotesk", "Monospace": "mono", "Handwriting": "hand"}
PARAMETRIC = {"XOPQ", "YOPQ", "YTAS", "YTDE", "YTFI", "YTLC", "YTUC", "GRAD", "XTRA"}  # Roboto Flex internals: stay near default
BINARY = {"WONK", "CRSV"}
TEXTURED = {"Doto", "Sixtyfour", "Bitcount Grid Double", "Handjet", "Monoton", "Kablammo", "Danfo"}  # great big, unreadable at card size
LIMIT = {"BLED": (0, 20), "SCAN": (-15, 30), "XROT": (-25, 25), "YROT": (-25, 25)}  # beyond these glyphs stop reading as text
CARD_PATTERNS = ["checker", "stripes", "dots", "grid", "waves", "zigzag", "plus", "rings", "triangles", "diamonds", "crosses", "bricks", "scales"]
GLYPHS = "♪♫✦✺❋◐✱✳❂☀✶◎⬡♬✿❖✸☾◆"


def in_range(c, rng):
    """c in a CSS unicode-range like 'U+0100-02BA, U+1E00-1EFF'"""
    for part in rng.replace("U+", "").split(","):
        lo, _, hi = part.strip().partition("-")
        if int(lo, 16) <= c <= int(hi or lo, 16):
            return True
    return False


def font_face(name, text=""):
    """Inlined @font-face for a bundled font. Subsets no character of text falls in are left out
    (most pages never need latin-ext)."""
    used, out, ax = {ord(c) for c in text}, "", MANIFEST[name]["axes"]
    w = f"{ax['wght'][0]:g} {ax['wght'][1]:g}" if "wght" in ax else "400"
    st = f"font-stretch:{ax['wdth'][0]:g}% {ax['wdth'][1]:g}%;" if "wdth" in ax else ""
    for fl in MANIFEST[name]["files"]:
        if fl["subset"] != "latin" and not any(in_range(c, fl["range"]) for c in used):
            continue
        data = base64.b64encode(open(os.path.join(FONT_DIR, fl["file"]), "rb").read()).decode()
        out += (f"@font-face{{font-family:'{name}';src:url(data:font/woff2;base64,{data}) format('woff2');"
                f"font-weight:{w};{st}font-display:block;unicode-range:{fl['range']}}}")
    return out


class Gen:
    """Holds the seeded RNG, the generated CSS, and the theme-level choices every component draws from."""

    def __init__(self, seed):
        self.seed, self.r, self.css, self.n = seed, random.Random(seed), [], 0
        r = self.r
        self.palette = self._palette()
        self._type()
        self.eases = [self.ease() for _ in range(2)]
        self.vocab = [self.enter() for _ in range(r.randint(3, 5))]  # entrance moves this design "speaks"
        self.letter_kf, self.card_kf = self.enter(.4), self.enter(1.6)
        self.grow, self.pop = self._from_only("grow"), self._from_only("pop")
        self.dur, self.stg = round(r.uniform(.5, 1.3), 2), round(r.uniform(.06, .2), 2)
        self.number_v = r.sample(["count", "odo", "ring", "echo", "ticker"], 3)
        self.head_v = r.sample(["plain", "letters", "mark", "marquee"], r.randint(2, 3))
        self.list_v = r.sample(["list", "podium", "tiles", "cloud", "ticker"], 3)
        self.chart_v = r.sample(["bars", "dots", "line", "radial", "heat"], 3)
        self.decor_v = r.sample(["blob", "rings", "scatter", "waves", "halftone", "glyph", "lines", "grid", "arcs", "confetti", "stars", "spiral", "contours"], r.randint(2, 3))
        self.aligns = r.sample(["left", "left", "center", "right"], r.randint(1, 2))
        self.valigns = r.sample(["center", "center", "start", "end"], r.randint(1, 2))
        self.label_v = r.choice(["none", "index", "fraction", "line", "bullet", "slash", "bracket", "dash", "hash"])
        self._card()

    # ---- primitives ----
    def uid(self, p):
        self.n += 1
        return f"{p}{self.n}"

    def f(self, a, b, nd=2):
        return round(self.r.uniform(a, b), nd)

    def sign(self):
        return self.r.choice([-1, 1])

    def ease(self):
        k = self.r.choice(["out", "back", "inout", "snap"])
        if k == "out":
            return f"cubic-bezier({self.f(.05, .3)},{self.f(.7, 1)},{self.f(.1, .4)},1)"
        if k == "back":
            return f"cubic-bezier({self.f(.2, .45)},{self.f(1.2, 1.9)},{self.f(.3, .7)},1)"
        if k == "inout":
            return f"cubic-bezier({self.f(.5, .8)},0,{self.f(.2, .5)},1)"
        return f"cubic-bezier({self.f(.7, .95)},{self.f(-.3, 0)},{self.f(.05, .25)},{self.f(1, 1.4)})"

    def enter(self, amp=1.0):
        """A generated entrance: 1-3 random transform/filter/clip ingredients with random amounts, maybe an overshoot."""
        r, name = self.r, self.uid("k")
        props = r.sample(["move", "rotate", "scale", "skew", "blur", "clip", "flip"], r.choice([1, 2, 2, 3]))
        tf = []
        if "flip" in props:
            tf.append(f"perspective(600px) rotate{r.choice('XY')}({self.sign() * r.randint(50, 90)}deg)")
        if "move" in props:
            a, d = r.uniform(0, 2 * math.pi), r.uniform(30, 120) * amp
            tf.append(f"translate({math.cos(a) * d:.0f}px,{math.sin(a) * d:.0f}px)")
        if "rotate" in props:
            tf.append(f"rotate({self.sign() * r.randint(4, 25) * amp:.0f}deg)")
        if "scale" in props:
            tf.append(f"scale({r.choice([self.f(.2, .8), self.f(1.2, 1.8)])})")
        if "skew" in props:
            tf.append(f"skew({self.sign() * r.randint(5, 20)}deg,{r.randint(-8, 8)}deg)")
        start = f"opacity:0;transform:{' '.join(tf) or 'none'}"
        end = "opacity:1;transform:none"
        if "blur" in props:
            px = r.randint(6, 20)
            if amp >= 1:  # per-letter blur is one blur pass per letter per frame: too heavy for phones
                start, end = start + f";filter:blur({px}px)", end + ";filter:none"
        if "clip" in props:
            c0, c1 = r.choice([("inset(0 100% 0 0)", "inset(-30%)"), ("inset(0 0 0 100%)", "inset(-30%)"),
                               ("inset(100% 0 0 0)", "inset(-30%)"), ("inset(0 0 100% 0)", "inset(-30%)"),
                               ("circle(0% at 50% 50%)", "circle(150% at 50% 50%)")])
            start, end = start + f";clip-path:{c0}", end + f";clip-path:{c1}"
        mid = ""
        if tf and r.random() < .45:
            over = r.choice(["scale(1.05)", "translateY(-6px)", "rotate(-2deg)", "scale(.97)", "skew(-3deg)"])
            mid = f"{r.randint(55, 80)}%{{opacity:1;transform:{over}}}"
        self.css.append(f"@keyframes {name}{{0%{{{start}}}{mid}100%{{{end}}}}}")
        return name

    def _from_only(self, kind):
        """'From' keyframes only, so the element ends at its own styles (bar heights, heat opacity)."""
        name = self.uid(kind[0])
        opts = {"grow": ["transform:scaleY(0)", "transform:translateY(60px);opacity:0", "transform:scale(0)",
                         "transform:scaleY(0) skewY(25deg)", "transform:scaleX(0)"],
                "pop": ["transform:scale(0)", "transform:scale(0) rotate(180deg)", "transform:translateY(-30px);opacity:0",
                        "opacity:0;filter:blur(6px)", "transform:scale(2.5);opacity:0"]}[kind]
        self.css.append(f"@keyframes {name}{{from{{{self.r.choice(opts)}}}}}")
        return name

    def ambient(self, amp=1.0):
        r, name = self.r, self.uid("f")
        if r.random() < .25:
            self.css.append(f"@keyframes {name}{{to{{transform:rotate({self.sign() * 360}deg)}}}}")
            return f"{name} {r.randint(30, 90)}s linear infinite"
        parts = [f"translate({r.randint(-40, 40) * amp:.0f}px,{r.randint(-40, 40) * amp:.0f}px)",
                 f"rotate({r.randint(-20, 20)}deg)", f"scale({self.f(.85, 1.2)})"]
        self.css.append(f"@keyframes {name}{{to{{transform:{' '.join(r.sample(parts, r.randint(1, 3)))}}}}}")
        return f"{name} {r.randint(6, 20)}s ease-in-out infinite alternate"

    def order(self, n):
        """Stagger order for a row of items: left-right, right-left, from the centre, from the edges, or shuffled."""
        k, mid = self.r.choice(["lr", "rl", "center", "edges", "random"]), (n - 1) / 2
        if k == "random":
            idx = list(range(n))
            self.r.shuffle(idx)
            return idx
        return [{"lr": i, "rl": n - 1 - i, "center": abs(i - mid), "edges": mid - abs(i - mid)}[k] for i in range(n)]

    def anim(self, inner, delay, tag="div", cls="", style=""):
        m = self.r.choice(self.vocab)
        return (f'<{tag} class="a {cls}" style="--m:{m};--d:{self.dur}s;--t:{delay:.2f}s;'
                f'--e:{self.r.choice(self.eases)};{style}">{inner}</{tag}>')

    # ---- theme ----
    def _palette(self, n=16):
        r = self.r
        self.light = r.random() < .3  # pastel slides with dark text, otherwise deep slides with white text
        self.fg, self.inv = ("#111111", "#ffffff") if self.light else ("#ffffff", "#111111")
        self.h0, sat = r.random(), r.choice([(.25, .45), (.55, .75), (.7, .95), (.3, .9)])
        scheme, d = r.choice(["analogous", "rainbow", "golden", "duo", "mono", "triad", "split", "tetrad", "square", "pentad", "wave", "warm", "cool"]), r.uniform(.02, .12)
        shift = r.uniform(.04, .25) * self.sign()
        base_l = (.82, .92) if self.light else (.22, .42)
        out = []
        for i in range(n):
            h = self.h0 + {"analogous": i * d / 2, "rainbow": i * d, "golden": i * .382,
                           "duo": (i % 2) * .5, "mono": 0, "triad": (i % 3) / 3, "split": (0, .42, .58)[i % 3],
                           "tetrad": (0, .17, .5, .67)[i % 4], "square": (i % 4) / 4, "pentad": i * .2,
                           "wave": .12 * math.sin(i * 1.3), "warm": .97 - self.h0 + i * .03 % .14, "cool": .5 - self.h0 + i * .04 % .2}[scheme] + r.uniform(-.02, .02)
            out.append(tuple(readable(hh, r.uniform(*base_l), r.uniform(*sat), self.fg) for hh in (h, h + shift)))
        return out

    def _instance(self, axes, heavy):
        """A random point in the font's design space (kept legible)."""
        r, v = self.r, {}
        for t, (lo, hi, df) in axes.items():
            lo, hi = LIMIT.get(t, (lo, hi))
            if t == "opsz":
                continue  # browsers pick optical size automatically
            if t in PARAMETRIC:
                x = df + r.uniform(-.25, .25) * (hi - lo)
            elif t in BINARY:
                x = r.choice([lo, hi])
            elif t == "wdth":
                x = r.uniform(max(lo, 62), hi)
            elif t == "wght" and heavy:
                x = r.uniform(min(max(lo, 500), hi), hi)
            else:
                x = r.uniform(lo, hi)
            v[t] = round(min(hi, max(lo, x)), 2)
        return v

    @staticmethod
    def _fvs(v):
        return ",".join(f'"{t}" {x:g}' for t, x in v.items()) or "normal"

    def _type(self):
        r = self.r
        effect = r.choice(["none", "none", "outline", "extrude", "echo", "offset", "glow", "shadow", "duotone"])
        if MANIFEST:
            disp = r.choice([n for n, f in MANIFEST.items() if "display" in f["roles"]])
            body = r.choice([n for n, f in MANIFEST.items() if "body" in f["roles"] and n != disp])
            self.fonts, axes = [disp, body], MANIFEST[disp]["axes"]
            stack = lambda n: f"'{n}', {FONTS[FALLBACK[MANIFEST[n]['category']]]}"
            self.head_ff, self.body_ff = stack(disp), stack(body)
        else:
            self.fonts, axes = [], {}
            self.head_ff, self.body_ff = FONTS[r.choice(list(FONTS))], FONTS[r.choice(BODY_FONTS)]
        inst = self._instance(axes, effect == "outline")
        self.head_fvs = self._fvs(inst)
        self.hw = round(inst["wght"]) if "wght" in inst else (400 if axes or MANIFEST else r.choice(range(300, 1000, 100)))
        # font motion: animate 1-2 of the font's own axes on entrance, maybe keep one breathing afterwards
        moving = [t for t in axes if t != "opsz" and t not in BINARY | PARAMETRIC]
        motion = ""
        if moving:
            pick = r.sample(moving, min(len(moving), r.randint(1, 2)))

            def elsewhere():
                w = dict(inst)
                for t in pick:
                    lo, hi = LIMIT.get(t, axes[t][:2])
                    w[t] = round(r.uniform(max(lo, 62) if t == "wdth" else lo, hi), 2)
                return self._fvs(w)
            ent = self.uid("v")
            self.css.append(f"@keyframes {ent}{{from{{font-variation-settings:{elsewhere()}}}}}")
            anims = [f"{ent} {self.f(1, 2.2)}s {self.ease()} var(--t,0s) both"]
            motion = f".in .disp{{animation:{','.join(anims)}}}"
        # small text (labels, tile/podium numbers) never in a font that only reads big
        self.small_ff = self.body_ff if self.fonts and self.fonts[0] in TEXTURED else self.head_ff
        dx, dy = r.choice([(1, 1), (-1, 1), (1, -1), (0, 1), (1, 0)])
        o = r.randint(3, 9)
        fx = {"none": "",
              "outline": "color:transparent;-webkit-text-stroke:max(2px,.025em) var(--fg);",
              "extrude": "text-shadow:" + ",".join(f"{dx * i * .012:.3f}em {dy * i * .012:.3f}em 0 color-mix(in srgb,var(--fg) 35%,var(--a))"
                                                    for i in range(1, r.randint(4, 12))) + ";",
              "echo": "text-shadow:" + ",".join(f"{dx * i * o * .004:.3f}em {dy * i * o * .004:.3f}em 0 color-mix(in srgb,var(--fg) {60 - i * 15}%,transparent)"
                                                 for i in range(1, 4)) + ";",
              "offset": f"text-shadow:{dx * o * .012:.3f}em {dy * o * .012:.3f}em 0 color-mix(in srgb,var(--fg) 30%,var(--b));",
              "glow": f"text-shadow:0 0 {r.randint(12, 40)}px color-mix(in srgb,var(--fg) 60%,transparent);",
              "shadow": f"text-shadow:{dx * .04:.2f}em {abs(dy) * .06 + .02:.2f}em {r.randint(8, 24)}px #0008;",
              "duotone": f"text-shadow:{dx * o * .008:.3f}em {dy * o * .008:.3f}em 0 var(--b),{-dx * o * .008:.3f}em {-dy * o * .008:.3f}em 0 color-mix(in srgb,var(--fg) 40%,var(--a));"}[effect]
        self.css.append(
            f".disp{{font-family:{self.head_ff};font-weight:{self.hw};font-variation-settings:{self.head_fvs};"
            f"letter-spacing:{self.f(-.05, .08)}em;text-transform:{r.choice(['none', 'none', 'uppercase', 'lowercase'])};"
            f"line-height:{self.f(.9, 1.1)};transform:skewX({r.choice([0, 0, 0, -8, -4, 6])}deg);{fx}}}{motion}"
            f".lbl{{font-family:{r.choice([self.small_ff, self.body_ff])};text-transform:{r.choice(['uppercase', 'uppercase', 'none'])};"
            f"letter-spacing:{self.f(0, .3)}em;font-weight:{r.choice([400, 600, 800])};font-size:{r.randint(12, 16)}px}}")

    def font_css(self, text=""):
        """@font-face for this design's two fonts, inlined so the page (and the PNG export) work offline."""
        return "".join(font_face(n, text) for n in self.fonts)

    def _card(self):
        r = self.r
        ink, bg = r.choice([("#111111", "#f1f0eb"), ("#f1f0eb", "#141414"),
                            ("#111111", hexc(self.h0, .93, .4)), ("#ffffff", hexc(self.h0, .12, .45))])
        accent = readable(r.random(), .55, r.uniform(.65, .95), ink, 3)
        p1, p2 = r.choice([(ink, bg), (ink, accent), (bg, ink), (accent, bg)])
        self.card = {"bg": bg, "ink": ink, "accent": accent, "p1": p1, "p2": p2,
                     "layout": r.choice(["band", "banner", "poster", "vinyl", "polaroid", "type"]), "pattern": r.choice(CARD_PATTERNS),
                     "tile": r.choice([12, 16, 20, 24]), "radius": r.choice([0, 8, 16, 24, 32]), "outline": r.random() < .5,
                     "sticker": r.random() < .55, "divider": r.choice(["none", "line", "dots"]), "glyph": r.choice(GLYPHS),
                     "art_r": r.choice([0, 0, 10, 24]), "tilt": r.choice([0, 0, -3, 3, -6]),
                     "footer": r.choice(["MY {y} WRAPPED", "{y} · ON REPEAT", "{y} IN SOUND", "WRAPPED {y}", "{y} · HEARD IT ALL",
                                         "{y} · TURNED UP", "SOUNDTRACK OF {y}", "{y} · NO SKIPS", "{y} ON LOOP"])}

    # ---- summary card: one generated SVG, shown on the page and rasterized as-is for "Save image" ----
    def _t(self, x, y, txt, size, head=True, w=None, anchor="start", fill=None, maxw=None, extra=""):
        c = self.card
        a = (f'x="{x:.1f}" y="{y:.1f}" font-size="{size}" font-family="{e(self.head_ff if head else self.body_ff)}" '
             f'font-weight="{w or (self.hw if head else 400)}" fill="{fill or c["ink"]}" text-anchor="{anchor}"')
        if maxw:
            a += f' data-w="{maxw}"'
        if head and self.head_fvs != "normal":
            a += f" style='font-variation-settings:{e(self.head_fvs)}'"
        return f"<text {a} {extra}>{e(txt)}</text>"

    def _pattern(self):
        c, r = self.card, self.r
        S, p1, p2, k = c["tile"], c["p1"], c["p2"], c["pattern"]
        base = f'<rect width="{S}" height="{S}" fill="{p2}"/>'
        body = {"checker": f'<rect width="{S / 2}" height="{S / 2}" fill="{p1}"/><rect x="{S / 2}" y="{S / 2}" width="{S / 2}" height="{S / 2}" fill="{p1}"/>',
                "stripes": f'<rect width="{S / 2}" height="{S}" fill="{p1}"/>',
                "dots": f'<circle cx="{S / 2}" cy="{S / 2}" r="{S * .22:.1f}" fill="{p1}"/>',
                "grid": f'<rect width="{S}" height="2" fill="{p1}"/><rect width="2" height="{S}" fill="{p1}"/>',
                "waves": f'<path d="M0,{S / 2} Q{S / 4},{S * .15} {S / 2},{S / 2} T{S},{S / 2}" fill="none" stroke="{p1}" stroke-width="2"/>',
                "zigzag": f'<path d="M0,{S * .7} L{S / 2},{S * .3} L{S},{S * .7}" fill="none" stroke="{p1}" stroke-width="2"/>',
                "plus": f'<path d="M{S / 2},{S * .25}V{S * .75}M{S * .25},{S / 2}H{S * .75}" stroke="{p1}" stroke-width="2"/>',
                "rings": f'<circle cx="{S / 2}" cy="{S / 2}" r="{S * .32:.1f}" fill="none" stroke="{p1}" stroke-width="1.5"/>',
                "triangles": f'<path d="M0,{S} L{S / 2},0 L{S},{S}Z" fill="{p1}"/>',
                "diamonds": f'<path d="M{S / 2},0 L{S},{S / 2} L{S / 2},{S} L0,{S / 2}Z" fill="{p1}"/>',
                "crosses": f'<path d="M{S * .3},{S * .3}L{S * .7},{S * .7}M{S * .7},{S * .3}L{S * .3},{S * .7}" stroke="{p1}" stroke-width="2"/>',
                "bricks": f'<path d="M0,1H{S}M0,{S / 2 + 1}H{S}M{S / 2},1V{S / 2 + 1}M1,{S / 2 + 1}V{S}" stroke="{p1}" stroke-width="2" fill="none"/>',
                "scales": f'<path d="M0,{S / 2} A{S / 2},{S / 2} 0 0,0 {S},{S / 2} M{-S / 2},{S} A{S / 2},{S / 2} 0 0,0 {S / 2},{S} M{S / 2},{S} A{S / 2},{S / 2} 0 0,0 {S * 1.5},{S}" fill="none" stroke="{p1}" stroke-width="1.5"/>'}[k]
        rot = ' patternTransform="rotate(45)"' if k == "stripes" else ""
        period = S * 2 ** .5 if k == "stripes" else S
        self.css.append(f"@keyframes cpat{{to{{transform:translateX({period * 2:.2f}px)}}}}"
                        f".in .card .patmove{{animation:cpat {r.randint(4, 14)}s linear infinite {r.choice(['normal', 'reverse'])}}}")
        return f'<pattern id=cpat patternUnits=userSpaceOnUse width="{S}" height="{S}"{rot}>{base}{body}</pattern>', period

    def _patfill(self, x, y, w, h, period):
        return (f'<clipPath id=creg><rect x="{x}" y="{y}" width="{w}" height="{h}"/></clipPath>'
                f'<g clip-path="url(#creg)"><rect class=patmove x="{x - 2 * period:.1f}" y="{y}" width="{w + 4 * period:.1f}" height="{h}" fill="url(#cpat)"/></g>')

    def _art(self, d, x, y, w, h, rad=0, circle=False):
        c = self.card
        clip = (f'<clipPath id=cart><circle cx="{x + w / 2}" cy="{y + h / 2}" r="{w / 2}"/></clipPath>' if circle else
                f'<clipPath id=cart><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rad}"/></clipPath>')
        if d["art"]:
            inner = f'<image class=cart href="{e(d["art"])}" x="{x}" y="{y}" width="{w}" height="{h}" preserveAspectRatio="xMidYMid slice"/>'
        elif circle:  # record label: two lines around the spindle hole, shrinking (not truncating) to fit
            words = d["name"].split()
            cut = min(range(1, len(words)), key=lambda i: abs(len(" ".join(words[:i])) - len(" ".join(words[i:]))), default=len(words))
            lines = [ln for ln in (" ".join(words[:cut]), " ".join(words[cut:])) if ln]
            dys = [-19, 21] if len(lines) == 2 else [-19]
            inner = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{c["ink"]}"/>' + "".join(
                self._t(x + w / 2, y + h / 2 + dy, ln, 22, head=False, w=700, anchor="middle", fill=c["bg"], maxw=w - 36,
                        extra=f'dominant-baseline="central" data-fs="{w - 36}" data-min="9"') for ln, dy in zip(lines, dys))
        else:
            inner = (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{c["ink"]}"/>'
                     + self._t(x + w / 2, y + h / 2, d["name"], 28, head=not (self.fonts and self.fonts[0] in TEXTURED), w=700, anchor="middle", fill=c["bg"], maxw=w - 24,
                               extra=f'dominant-baseline="central" data-fs="{w - 24}"'))
        return f'{clip}<g clip-path="url(#cart)">{inner}</g>'

    def _year(self, x, y, size, anchor="middle", rotate=None, fill=None, fit=360):
        c = self.card
        paint = (f'fill="none" stroke="{c["ink"]}" stroke-width="1.6"' if c["outline"] else "")
        t = self._t(x, y, str(self.year), size, anchor=anchor, fill=fill or c["ink"],
                    extra=f'dominant-baseline="central" letter-spacing="-2" data-fs="{fit}" {paint}' + (f' transform="rotate({rotate} {x} {y})"' if rotate else ""))
        return t.replace(f'fill="{fill or c["ink"]}"', "", 1) if c["outline"] else t

    def _sticker(self, cx, cy, text):
        c, r = self.card, self.r
        n, r1, r2 = r.randint(10, 18), 40, r.uniform(30, 35)
        pts = " ".join(f"{cx + (r1 if i % 2 == 0 else r2) * math.cos(math.pi * i / n):.1f},{cy + (r1 if i % 2 == 0 else r2) * math.sin(math.pi * i / n):.1f}"
                       for i in range(2 * n))
        return (f'<g transform="rotate({r.randint(-25, 25)} {cx} {cy})"><g class=sticker><polygon points="{pts}" fill="{c["accent"]}" stroke="{c["ink"]}" stroke-width="1.5"/>'
                + self._t(cx, cy - 6, "TOP", 9, head=False, w=800, anchor="middle", extra='letter-spacing="1.5"')
                + self._t(cx, cy + 9, text, 12, w=None, anchor="middle", maxw=52) + "</g></g>")

    def card_svg(self, d):
        c, r, W, H = self.card, self.r, 400, 660
        self.year = d["year"]
        pat, period = self._pattern()
        L, top, info_y = c["layout"], "", 372
        if L == "band":
            top = (self._patfill(0, 0, W, 340, period) + f'<rect width="80" height="340" fill="{c["accent"]}"/>'
                   + self._year(40, 170, 66, rotate=-90, fit=310) + self._art(d, 80, 24, 292, 292, c["art_r"]))
            spots = [(340, 290), (330, 52)]
        elif L == "banner":
            top = (f'<rect width="{W}" height="96" fill="{c["accent"]}"/>' + self._year(W / 2, 50, 80, fit=360)
                   + self._patfill(0, 96, W, 268, period)
                   + f'<g transform="rotate({c["tilt"]} 200 230)">{self._art(d, 86, 116, 228, 228, c["art_r"])}</g>')
            spots, info_y = [(338, 304), (62, 304)], 392
        elif L == "poster":
            top = (self._art(d, 0, 0, W, 330)
                   + f'<linearGradient id=cfade x1=0 y1=0 x2=0 y2=1><stop offset=".55" stop-color="{c["bg"]}" stop-opacity="0"/><stop offset="1" stop-color="{c["bg"]}"/></linearGradient>'
                   + f'<rect width="{W}" height="330" fill="url(#cfade)"/>' + self._year(20, 290, 112, anchor="start", fill=c["accent"], fit=360)
                   + self._patfill(0, 330, W, 18, period))
            spots, info_y = [(340, 60)], 384
        elif L == "polaroid":  # a tilted instant photo on the pattern, the period written in its margin
            tilt = c["tilt"] or r.choice([-4, 4])
            top = (self._patfill(0, 0, W, 350, period)
                   + f'<g transform="rotate({tilt} 200 175)"><rect x="70" y="16" width="260" height="316" fill="{c["bg"]}" stroke="{c["ink"]}" stroke-width="1.5"/>'
                   + self._art(d, 86, 32, 228, 228) + self._year(200, 296, 40, fit=228) + "</g>")
            spots, info_y = [(342, 300), (58, 52)], 384
        elif L == "type":  # the period set huge on an accent block, a round cover tucked under it
            top = (f'<rect width="{W}" height="340" fill="{c["accent"]}"/>' + self._year(W / 2, 112, 140, fit=360)
                   + self._art(d, 130, 186, 140, 140, circle=True) + self._patfill(0, 340, W, 14, period))
            spots, info_y = [(338, 290), (62, 290)], 386
        else:  # vinyl
            rec = "#111111" if lum(c["ink"]) < .5 else "#0d0d0d"
            grooves = "".join(f'<circle cx="200" cy="175" r="{rr}" fill="none" stroke="#fff" stroke-opacity=".09" stroke-width=".7"/>'
                              for rr in range(76, 148, r.randint(5, 9)))
            unit = f"{self.year} · {c['footer'].format(y=self.year)} · "
            ring_txt = unit * max(1, int(804 / (len(unit) * 8)))  # estimate; JS re-measures with the real font
            top = (self._patfill(0, 0, W, 350, period)
                   + f'<g class=vinyl><circle cx="200" cy="175" r="150" fill="{rec}"/>{grooves}'
                   + f'<path id=cring d="M200,175 m-128,0 a128,128 0 1,1 256,0 a128,128 0 1,1 -256,0" fill="none"/>'
                   + f'<text font-size="11" font-family="{e(self.body_ff)}" font-weight="700" fill="#f1f0eb" fill-opacity=".85" letter-spacing="2">'
                   + f'<textPath href="#cring" textLength="804" lengthAdjust="spacing" data-unit="{e(unit)}">{e(ring_txt)}</textPath></text>'
                   + self._art(d, 132, 107, 136, 136, circle=True) + f'<circle cx="200" cy="175" r="5" fill="{c["bg"]}"/></g>')
            spots = [(352, 292), (48, 292)]
        sticker = self._sticker(*r.choice(spots), d["value"]) if c["sticker"] else ""
        # info block
        y, col, cw = info_y, [22, 208], 170
        info = ""
        for i, (lab, items) in enumerate([("Top Artists", d["artists"]), ("Top Songs", d["songs"])]):
            info += self._t(col[i], y, lab, 11, head=False, extra='opacity=".65"')
            for j, item in enumerate(items):
                yy = y + 26 + j * 21
                info += self._t(col[i], yy, j + 1, 15, head=False, w=700, extra='opacity=".55"')
                info += self._t(col[i] + 16, yy, item, 15, head=False, w=700, maxw=cw - 18)
        if c["divider"] != "none":
            dash = ' stroke-dasharray="0.1 6" stroke-linecap="round" stroke-width="2.5"' if c["divider"] == "dots" else ' stroke-width="1"'
            info += f'<line x1="22" x2="{W - 22}" y1="{y + 132}" y2="{y + 132}" stroke="{c["ink"]}" stroke-opacity=".3"{dash}/>'
        info += self._t(col[0], y + 158, "Minutes Listened", 11, head=False, extra='opacity=".65"')
        info += self._t(col[1], y + 158, d["label"], 11, head=False, extra='opacity=".65"')
        big = not (self.fonts and self.fonts[0] in TEXTURED)
        info += self._t(col[0], y + 192, f"{d['minutes']:,}", 30, head=big, w=None if big else 700, extra=f'data-n="{d["minutes"]}"')
        info += self._t(col[1], y + 192, d["value"], 30, head=big, w=None if big else 700, maxw=cw)
        foot = (f'<circle cx="38" cy="{H - 38}" r="16" fill="{c["ink"]}"/>'
                + self._t(38, H - 38, c["glyph"], 16, head=False, anchor="middle", fill=c["bg"], extra='dominant-baseline="central"')
                + self._t(W - 22, H - 33, c["footer"].format(y=self.year), 13, head=False, w=800, anchor="end", extra='letter-spacing="1"'))
        label = f"{self.year} summary: top artist {d['artists'][0]}, top song {d['songs'][0]}, {d['minutes']:,} minutes"
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" style="border-radius:{c['radius']}px" role="img" aria-label="{e(label)}">'
                f'<defs>{pat}<clipPath id=cclip><rect width="{W}" height="{H}" rx="{c["radius"]}"/></clipPath></defs>'
                f'<g clip-path="url(#cclip)"><rect width="{W}" height="{H}" fill="{c["bg"]}"/>{top}{sticker}{info}{foot}</g></svg>')

    def root_css(self):
        r = self.r
        bg, size = r.choice(BACKGROUNDS)
        return (f":root{{--fg:{self.fg};--inv:{self.inv};--body:{self.body_ff};--head:{self.head_ff};--small:{self.small_ff};"
                f"--lm:{self.letter_kf};--lstg:{r.randint(20, 70)}ms;--grow:{self.grow};--pop:{self.pop};"
                f"--rad:{r.choice([0, 4, 10, 20])}px;--dotr:{r.choice(['50%', '2px', '0'])};--cap:{r.choice(['round', 'butt'])};"
                f"--cols:{r.choice([2, 3])};--tr:{r.randint(-8, 8)}deg;--tks:{r.randint(15, 40)}s;"
                f"--tkd:{r.choice(['normal', 'reverse'])};--ex:{r.randint(-6, 6) / 100}em;--ey:{r.randint(-6, 6) / 100}em;"
                f"--np-r:{r.choice(['50%', '50%', '10px'])};--np-anim:{r.choice(['spin', 'bob'])};"
                f"--hw:{self.hw}}}"
                f"section::before{{background:{bg.format(ang=r.randrange(0, 360, 15))};background-size:{size};"
                f"animation:{r.choice(['drift', 'drift', 'none'])} {r.randint(8, 25)}s ease-in-out infinite alternate}}"
                f".echo{{animation:{self.ambient(.3)}}}")

    # ---- components ----
    def label(self, text, idx, total, t):
        pre, post = {"none": ("", ""), "index": (f"<b>{idx:02d}</b>&ensp;", ""), "fraction": (f"<b>{idx:02d}/{total:02d}</b>&ensp;", ""),
                     "line": ("<i class=ln></i>", ""), "bullet": ("●&ensp;", ""), "slash": ("//&ensp;", ""),
                     "bracket": ("[&ensp;", "&ensp;]"), "dash": ("—&ensp;", ""), "hash": (f"#{idx}&ensp;", "")}[self.label_v]
        return self.anim(f"<small class=lbl>{pre}{e(text)}{post}</small>", t)

    def text(self, html_, t, cls=""):
        return self.anim(f"<p class='{cls}'>{html_}</p>", t)

    def number(self, n, t, frac=None):
        v, s = self.r.choice(self.number_v), f"{n:,}"
        count = f'<h1 class="disp big" data-n="{n}">{s}</h1>'
        if v == "odo":
            digits = "".join(f'<span class=odo style="--d:{c};--i:{i}"><span>{"<br>".join("0123456789")}</span></span>'
                             if c.isdigit() else f"<span>{c}</span>" for i, c in enumerate(s))
            inner = f'<h1 class="disp big" aria-label="{s}"><span aria-hidden=true>{digits}</span></h1>'
        elif v == "ring":
            f = frac if frac is not None else self.r.uniform(.55, .95)
            inner = (f'<div class=ringwrap><svg class=ring viewBox="0 0 100 100" aria-hidden=true><circle class=track cx=50 cy=50 r=45 pathLength=100 />'
                     f'<circle class="arc" cx=50 cy=50 r=45 pathLength=100 style="--f:{max(.02, min(1, f)) * 100:.1f}"/></svg>'
                     f'<h1 class="disp" data-n="{n}">{s}</h1></div>')
        elif v == "echo":
            copies = "".join(f'<span class="disp big echo" aria-hidden=true style="--k:{k}">{s}</span>' for k in (3, 2, 1))
            inner = f"<div class=echowrap>{copies}{count}</div>"
        elif v == "ticker":
            band = f"{s} {self.r.choice('·✦/—●')} " * 8
            inner = f'<div class=tkwrap><div class="tk disp" aria-hidden=true><span>{band}</span><span>{band}</span></div>{count}</div>'
        else:
            inner = count
        return self.anim(inner, t)

    def headline(self, text, t):
        v = self.r.choice(self.head_v)
        k = f' style="--hk:{min(1, (16 / max(1, len(text))) ** .5):.2f}"'  # long titles shrink instead of eating the slide
        if v == "letters" and len(text) <= 36:
            n, i, words = len(text.replace(" ", "")), 0, []
            order = self.order(n)
            for w in text.split(" "):
                ls = ""
                for ch in w:
                    ls += f'<span class=l style="--o:{order[i]}">{e(ch)}</span>'
                    i += 1
                words.append(f"<span class=w>{ls}</span>")
            return self.anim(f'<h1 class="disp big"{k} aria-label="{e(text)}"><span aria-hidden=true>{" ".join(words)}</span></h1>', t)
        if v == "mark":
            origin = self.r.choice(["0 100%", "100% 100%"])
            return self.anim(f'<h1 class="disp big"{k}><span class=mark style="background-position:{origin}">{e(text)}</span></h1>', t)
        if v == "marquee":
            band = f"{e(text)} {self.r.choice('·✦/—●')} " * 6
            return self.anim(f'<div class=tkwrap><div class="tk disp" aria-hidden=true><span>{band}</span><span>{band}</span></div>'
                             f'<h1 class="disp big"{k}>{e(text)}</h1></div>', t)
        return self.anim(f'<h1 class="disp big"{k}>{e(text)}</h1>', t)

    def ranks(self, items, t):
        """items: [(label_html, count)]"""
        if not items:
            return ""
        v, mx = self.r.choice(self.list_v), max(c for _, c in items) or 1
        st = lambda i: t + self.stg + i * self.r.uniform(.04, .1)
        if v == "podium" and len(items) >= 3:
            cols = ""
            for rank in (1, 0, 2):
                lab, c = items[rank]
                cols += self.anim(f'<span>{lab}</span><i style="height:{(100, 74, 56)[rank]}%">{rank + 1}<small>{c}</small></i>',
                                  st(rank), cls="pod")
            rest = "".join(self.anim(f"<span>{lab}</span><b>{c}</b>", st(i + 3), tag="li") for i, (lab, c) in enumerate(items[3:]))
            return f'<div class=podium>{cols}</div><ol class=rl start=4 style="counter-reset:n 3">{rest}</ol>'
        if v == "tiles":
            return "<div class=tiles>" + "".join(self.anim(f"<b>{i + 1}</b><span>{lab}</span><small>{c} plays</small>", st(i), cls="tile")
                                                  for i, (lab, c) in enumerate(items[:9])) + "</div>"
        if v == "cloud":
            return "<p class=cloud>" + "".join(self.anim(lab, st(i), tag="span", style=f"font-size:{14 + 14 * c / mx:.0f}px")
                                                for i, (lab, c) in enumerate(items)) + "</p>"
        if v == "ticker" and len(items) >= 3:
            row = "".join(f"<span><b>{i + 1}</b> {lab}</span>" for i, (lab, _) in enumerate(items))
            return self.anim(f'<div class=tl><div>{row}</div><div aria-hidden=true>{row}</div></div>', st(0))
        return "<ol class=rl>" + "".join(self.anim(f"<span>{lab}</span><b>{c}</b>", st(i), tag="li") for i, (lab, c) in enumerate(items)) + "</ol>"

    def chart(self, values, labels, t):
        v, mx, n = self.r.choice(self.chart_v), max(values) or 1, len(values)
        o = self.order(n)
        if v == "line" and n > 2:
            pts = [(i / (n - 1) * 100, 95 - x / mx * 85) for i, x in enumerate(values)]
            d = f"M{pts[0][0]:.1f},{pts[0][1]:.1f}" + "".join(
                f"C{(pts[i - 1][0] + p[0]) / 2:.1f},{pts[i - 1][1]:.1f} {(pts[i - 1][0] + p[0]) / 2:.1f},{p[1]:.1f} {p[0]:.1f},{p[1]:.1f}"
                for i, p in enumerate(pts) if i)
            inner = (f'<svg class=lc viewBox="0 0 100 100" preserveAspectRatio=none aria-hidden=true><path class=area d="{d} L100,100 L0,100Z"/>'
                     f'<path class=draw d="{d}" pathLength=100 /></svg><div class=labels>{"".join(f"<span>{e(l)}</span>" for l in labels)}</div>')
        elif v == "radial":
            r0, lines = 38, ""
            sw = min(7, max(2, 2 * math.pi * r0 / n * .55))
            for i, x in enumerate(values):
                a = 2 * math.pi * i / n - math.pi / 2
                r1 = r0 + 3 + x / mx * 55
                lines += (f'<line class=draw pathLength=100 x1="{100 + r0 * math.cos(a):.1f}" y1="{100 + r0 * math.sin(a):.1f}" '
                          f'x2="{100 + r1 * math.cos(a):.1f}" y2="{100 + r1 * math.sin(a):.1f}" stroke-width="{sw:.1f}" style="--o:{o[i]}"/>')
                if labels[i]:
                    lines += f'<text x="{100 + (r0 - 9) * math.cos(a):.1f}" y="{100 + (r0 - 9) * math.sin(a):.1f}">{e(labels[i])}</text>'
            inner = f'<svg class=radial viewBox="0 0 200 200" aria-hidden=true>{lines}</svg>'
        elif v == "dots":
            inner = "<div class=dots>" + "".join(
                f'<div class=dcol><span>{e(l)}</span>' + "".join(f'<i style="--o:{o[i] + j * .5}"></i>' for j in range(round(x / mx * 8)))
                + "</div>" for i, (x, l) in enumerate(zip(values, labels))) + "</div>"
        elif v == "heat":
            inner = "<div class=heat>" + "".join(f'<div><i style="opacity:{.12 + .88 * x / mx:.2f};--o:{o[i]}"></i><span>{e(l)}</span></div>'
                                                 for i, (x, l) in enumerate(zip(values, labels))) + "</div>"
        else:
            inner = "<div class=bars>" + "".join(f'<div class=bar title="{e(l)}: {x}"><i style="height:{x / mx * 100:.0f}%;--o:{o[i]}"></i><span>{e(l)}</span></div>'
                                                 for i, (x, l) in enumerate(zip(values, labels))) + "</div>"
        return self.anim(f'<div role=img aria-label="{e(", ".join(f"{l}: {x}" for x, l in zip(values, labels) if l))}">{inner}</div>', t)

    def decor(self):
        r, k = self.r, self.r.choice(self.decor_v)
        op = lambda: self.f(.06, .12)
        if k == "blob":
            cx, cy, R = r.uniform(15, 85), r.uniform(15, 85), r.uniform(18, 40)
            harm = [(kk, r.uniform(0, .15), r.uniform(0, 6.3)) for kk in (2, 3, 4, 5)]
            pts = []
            for i in range(64):
                th = i / 64 * 2 * math.pi
                rr = R * (1 + sum(a * math.sin(kk * th + ph) for kk, a, ph in harm))
                pts.append(f"{cx + rr * math.cos(th):.1f},{cy + rr * math.sin(th):.1f}")
            body = f'<path d="M{" L".join(pts)}Z" fill="var(--fg)" opacity="{op()}"/>'
        elif k == "rings":
            cx, cy, step = r.uniform(0, 100), r.uniform(0, 100), r.uniform(4, 12)
            dash = r.choice(["", f' stroke-dasharray="{r.uniform(.5, 3):.1f} {r.uniform(1, 4):.1f}"'])
            body = "".join(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{step * i:.1f}" fill=none stroke="var(--fg)" stroke-width="{self.f(.2, .6)}" opacity="{self.f(.12, .22)}"{dash}/>'
                           for i in range(1, r.randint(4, 10)))
        elif k == "scatter":
            shapes = r.sample(["c", "s", "t", "p", "x"], r.randint(1, 3))
            fill = r.random() < .5
            body = ""
            for _ in range(r.randint(8, 24)):
                x, y, sz, sh = r.uniform(0, 100), r.uniform(0, 100), r.uniform(1, 5), r.choice(shapes)
                paint = f'fill="var(--fg)"' if fill else f'fill=none stroke="var(--fg)" stroke-width=".4"'
                body += {"c": f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{sz / 2:.1f}" {paint} opacity="{self.f(.1, .22)}"/>',
                         "s": f'<rect x="{x:.1f}" y="{y:.1f}" width="{sz:.1f}" height="{sz:.1f}" transform="rotate({r.randint(0, 90)} {x:.1f} {y:.1f})" {paint} opacity="{self.f(.1, .22)}"/>',
                         "t": f'<path d="M{x:.1f},{y - sz:.1f} L{x + sz:.1f},{y + sz:.1f} L{x - sz:.1f},{y + sz:.1f}Z" {paint} opacity="{self.f(.1, .22)}"/>',
                         "p": f'<path d="M{x - sz:.1f},{y:.1f}H{x + sz:.1f}M{x:.1f},{y - sz:.1f}V{y + sz:.1f}" stroke="var(--fg)" stroke-width=".5" opacity="{self.f(.15, .25)}"/>',
                         "x": f'<path d="M{x - sz:.1f},{y - sz:.1f}L{x + sz:.1f},{y + sz:.1f}M{x + sz:.1f},{y - sz:.1f}L{x - sz:.1f},{y + sz:.1f}" stroke="var(--fg)" stroke-width=".5" opacity="{self.f(.15, .25)}"/>'}[sh]
        elif k == "waves":
            amp, freq, body = r.uniform(2, 8), r.uniform(1, 4), ""
            for j in range(r.randint(3, 8)):
                y0, ph = 10 + j * r.uniform(8, 14), r.uniform(0, 6.3)
                pts = " L".join(f"{x:.0f},{y0 + amp * math.sin(2 * math.pi * freq * x / 100 + ph):.1f}" for x in range(0, 101, 2))
                body += f'<path d="M{pts}" fill=none stroke="var(--fg)" stroke-width="{self.f(.2, .6)}" opacity="{self.f(.12, .22)}"/>'
        elif k == "halftone":
            sp, fx, fy, ph, body = r.choice([5, 6, 8]), r.uniform(.03, .1), r.uniform(.03, .1), r.uniform(0, 6.3), ""
            for y in range(0, 101, sp):
                for x in range(0, 101, sp):
                    rad = (math.sin(x * fx + ph) + math.cos(y * fy) + 2) / 4 * sp * .45
                    if rad > .3:
                        body += f'<circle cx="{x}" cy="{y}" r="{rad:.1f}"/>'
            body = f'<g fill="var(--fg)" opacity="{op()}">{body}</g>'
        elif k == "glyph":
            body = (f'<text x="{r.uniform(20, 80):.0f}" y="{r.uniform(40, 90):.0f}" font-size="{r.randint(50, 110)}" style="font-family:var(--head)" text-anchor=middle '
                    f'fill="var(--fg)" opacity="{self.f(.05, .1)}" transform="rotate({r.randint(-30, 30)} 50 50)">{r.choice(GLYPHS)}</text>')
        elif k == "grid":
            gap, dot = r.choice([6, 8, 10]), r.random() < .5
            cells = [(x, y) for y in range(gap // 2, 101, gap) for x in range(gap // 2, 101, gap)]
            body = (f'<g fill="var(--fg)" opacity="{self.f(.1, .18)}">' + "".join(
                f'<circle cx="{x}" cy="{y}" r=".6"/>' if dot else f'<rect x="{x - .5}" y="{y - .5}" width="1" height="1"/>' for x, y in cells) + "</g>")
        elif k == "arcs":
            cx, cy, body = r.choice([0, 100]), r.choice([0, 100]), ""
            for i in range(1, r.randint(5, 12)):
                rr = i * r.uniform(7, 11)
                body += (f'<circle cx="{cx}" cy="{cy}" r="{rr:.1f}" fill=none stroke="var(--fg)" stroke-width="{self.f(.6, 2)}" '
                         f'pathLength=100 stroke-dasharray="{r.randint(10, 40)} {r.randint(5, 20)}" opacity="{self.f(.08, .18)}"/>')
        elif k == "confetti":
            body = "".join(f'<rect x="{r.uniform(0, 100):.1f}" y="{r.uniform(0, 100):.1f}" width="{r.uniform(1, 3):.1f}" height="{r.uniform(.4, 1):.1f}" '
                           f'transform="rotate({r.randint(0, 180)} 50 50)" fill="var(--{r.choice(["fg", "fg", "b"])})" opacity="{self.f(.15, .3)}"/>' for _ in range(r.randint(20, 45)))
        elif k == "stars":  # four-point sparkles
            body = ""
            for _ in range(r.randint(5, 14)):
                x, y, sz = r.uniform(0, 100), r.uniform(0, 100), r.uniform(1.5, 6)
                q = sz * .18
                body += (f'<path d="M{x:.1f},{y - sz:.1f}Q{x + q:.1f},{y - q:.1f} {x + sz:.1f},{y:.1f}Q{x + q:.1f},{y + q:.1f} {x:.1f},{y + sz:.1f}'
                         f'Q{x - q:.1f},{y + q:.1f} {x - sz:.1f},{y:.1f}Q{x - q:.1f},{y - q:.1f} {x:.1f},{y - sz:.1f}Z" fill="var(--fg)" opacity="{self.f(.12, .25)}"/>')
        elif k == "spiral":
            cx, cy, turns, grow = r.uniform(20, 80), r.uniform(20, 80), r.uniform(3, 7), r.uniform(1.5, 3)
            pts = " L".join(f"{cx + grow * th * math.cos(th):.1f},{cy + grow * th * math.sin(th):.1f}"
                            for th in (i * .15 for i in range(int(turns * 2 * math.pi / .15))))
            body = f'<path d="M{pts}" fill=none stroke="var(--fg)" stroke-width="{self.f(.3, .8)}" opacity="{self.f(.1, .2)}"/>'
        elif k == "contours":  # topographic map: one wobbly ring, nested
            cx, cy = r.uniform(10, 90), r.uniform(10, 90)
            harm = [(kk, r.uniform(0, .12), r.uniform(0, 6.3)) for kk in (2, 3, 5)]
            body = ""
            for j in range(1, r.randint(6, 12)):
                R = j * r.uniform(5, 8)
                pts = [f"{cx + R * (1 + sum(a * math.sin(kk * th + ph + j * .3) for kk, a, ph in harm)) * math.cos(th):.1f},"
                       f"{cy + R * (1 + sum(a * math.sin(kk * th + ph + j * .3) for kk, a, ph in harm)) * math.sin(th):.1f}"
                       for th in (i / 48 * 2 * math.pi for i in range(48))]
                body += f'<path d="M{" L".join(pts)}Z" fill=none stroke="var(--fg)" stroke-width=".35" opacity="{self.f(.12, .22)}"/>'
        else:  # lines
            ang, gap = r.randint(0, 180), r.uniform(3, 8)
            body = (f'<g transform="rotate({ang} 50 50)" stroke="var(--fg)" stroke-width="{self.f(.15, .4)}" opacity="{self.f(.1, .2)}">'
                    + "".join(f'<path d="M-50,{y:.1f}H150"/>' for y in [i * gap - 50 for i in range(int(200 / gap))]) + "</g>")
        return (f'<svg class=decor viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice" aria-hidden=true '
                f'style="animation:{self.ambient()}">{body}</svg>')

    def layout(self):
        return f"--al:{self.r.choice(self.aligns)};--va:{self.r.choice(self.valigns)}"


CSS = """
html{-webkit-tap-highlight-color:transparent;scroll-snap-type:y mandatory;scroll-behavior:smooth}body{margin:0;font:18px/1.4 var(--body);color:var(--fg);background:#000}
section{position:relative;overflow:hidden;min-height:100vh;min-height:100svh;scroll-snap-align:start;display:grid;grid-template-columns:minmax(0,1fr);justify-items:center;align-items:var(--va);
  padding:calc(64px + env(safe-area-inset-top)) calc(40px + env(safe-area-inset-right)) calc(110px + env(safe-area-inset-bottom)) calc(24px + env(safe-area-inset-left));box-sizing:border-box}
section{background:var(--a)}section::before{content:"";position:absolute;inset:-15%}
@keyframes drift{from{transform:translate(-5%,-5%)}to{transform:translate(5%,5%)}}
.bg{position:absolute;left:-10%;top:-10%;width:30%;height:30%;transform:scale(4);transform-origin:0 0;object-fit:cover;filter:blur(10px) saturate(1.4);opacity:0;mix-blend-mode:soft-light;transition:opacity 1.5s}
.in .bg{opacity:.9}
section:not(.in),section:not(.in) *,section:not(.in)::before{animation-play-state:paused!important}
.decor{position:absolute;inset:0;width:100%;height:100%;pointer-events:none;overflow:visible}
section>div{position:relative;max-width:640px;width:100%;text-align:var(--al)}
.a{opacity:0}.in .a{animation:var(--m) var(--d) var(--e) var(--t) both}
h1,.big{font-size:max(24px,calc(clamp(40px,10vw,88px) * var(--hk,1)));margin:.1em 0}.fit *{animation:none!important}
small{opacity:.85}.lbl{display:block;opacity:.9}.lbl b{font-weight:inherit;opacity:.7}
.ln{display:inline-block;width:2em;height:2px;background:currentColor;vertical-align:middle;margin-right:.6em}
.sub{opacity:.85}em{opacity:.75;font-style:normal;margin-left:.4em}p{margin:.5em 0}
/* number variants */
.odo{display:inline-block;height:1em;line-height:1;overflow:hidden;vertical-align:top;font-variant-numeric:tabular-nums}
.odo>span{display:block;transform:translateY(calc(var(--d) * -1em))}
.in .odo>span{animation:odo calc(var(--d) * .12s + .8s) var(--e) calc(var(--t) + var(--i) * 90ms) both}@keyframes odo{from{transform:translateY(0)}}
.ringwrap{position:relative;width:min(78vw,340px,45svh);aspect-ratio:1;display:inline-grid;place-items:center}
.ring{position:absolute;inset:0;transform:rotate(-90deg)}.ring circle{fill:none;stroke-width:6;stroke-linecap:var(--cap)}
.ring .track{stroke:color-mix(in srgb,var(--fg) 18%,transparent)}.ring .arc{stroke:var(--fg);stroke-dasharray:100;stroke-dashoffset:calc(100 - var(--f))}
.in .ring .arc{animation:ring 1.8s var(--e) var(--t) both}@keyframes ring{from{stroke-dashoffset:100}}
.ringwrap h1{font-size:clamp(32px,12vw,68px);position:relative}
.echowrap{position:relative;display:inline-block}.echo{position:absolute;left:0;top:0;margin:.1em 0;color:transparent;
  -webkit-text-stroke:1px color-mix(in srgb,var(--fg) 45%,transparent);text-shadow:none;translate:calc(var(--k) * var(--ex)) calc(var(--k) * var(--ey))}
.echowrap h1{position:relative}
.tkwrap{position:relative}.tk{position:absolute;left:-40vw;right:-40vw;top:50%;translate:0 -50%;rotate:var(--tr);white-space:nowrap;overflow:hidden;
  opacity:.13;font-size:clamp(48px,14vw,120px);pointer-events:none;text-shadow:none}
.tk>span{display:inline-block;animation:tick var(--tks) linear infinite var(--tkd)}@keyframes tick{to{transform:translateX(-100%)}}
.tkwrap h1{position:relative}
/* headline variants */
.w{display:inline-block;white-space:nowrap}.l{display:inline-block}
.in .l{animation:var(--lm) var(--d) var(--e) calc(var(--t) + var(--o) * var(--lstg)) both}
.mark{background:linear-gradient(var(--fg),var(--fg)) no-repeat;background-size:100% 100%;color:var(--a);-webkit-text-stroke:0;text-shadow:none;
  padding:0 .12em;-webkit-box-decoration-break:clone;box-decoration-break:clone}
.in .mark{animation:mark .9s var(--e) calc(var(--t) + .25s) both}@keyframes mark{from{background-size:0% 100%;color:var(--fg)}}
/* list variants */
.rl{padding:0;list-style:none;counter-reset:n;text-align:left}
.rl li{counter-increment:n;display:flex;gap:.6em;padding:.35em 0;border-bottom:1px solid color-mix(in srgb,var(--fg) 20%,transparent)}
.rl li::before{content:counter(n);opacity:.6;width:1.5em;flex:none}.rl li>span{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.rl li b{opacity:.8}
.podium{display:flex;align-items:flex-end;gap:8px;height:220px;margin:1em 0}
.pod{flex:1;min-width:0;height:100%;display:flex;flex-direction:column;justify-content:flex-end;text-align:center}
.pod>span{font-weight:700;font-size:15px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding-bottom:4px}.pod>span em{display:none}
.pod i{display:flex;flex-direction:column;align-items:center;justify-content:flex-start;padding-top:8px;background:var(--fg);color:var(--a);
  border-radius:var(--rad) var(--rad) 0 0;font:normal 900 30px/1 var(--small)}.pod i small{font:600 12px var(--body);opacity:.8;margin-top:4px}
.tiles{display:grid;grid-template-columns:repeat(var(--cols),minmax(0,1fr));gap:8px;margin:1em 0;text-align:left}
.tile{border:1px solid color-mix(in srgb,var(--fg) 30%,transparent);background:color-mix(in srgb,var(--fg) 6%,transparent);border-radius:var(--rad);padding:10px;min-width:0}
.tile b{display:block;font:var(--hw,800) 26px var(--small)}.tile span{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:600}.tile small{font-size:12px}
.cloud{line-height:1.3;margin:1em 0}.cloud em{display:none}.cloud>.a{display:inline-block;margin:0 .45em .15em 0;font-weight:700}
.tl{overflow:hidden;white-space:nowrap;margin:1em -40px 1em -24px;font-size:22px;mask-image:linear-gradient(90deg,transparent,#000 12%,#000 88%,transparent)}
.tl>div{display:inline-block;animation:tick var(--tks) linear infinite var(--tkd)}.tl span{margin-right:1.4em}.tl b{opacity:.6;margin-right:.3em}
/* chart variants */
.bars{display:flex;gap:3px;height:140px;align-items:flex-end;margin:1em 0}.bar{flex:1;height:100%;display:flex;flex-direction:column;justify-content:flex-end;align-items:center}
.bar i{display:block;width:100%;background:color-mix(in srgb,var(--fg) 85%,transparent);border-radius:var(--rad) var(--rad) 0 0;min-height:2px;transform-origin:bottom}
.bar span,.dcol span,.heat span,.labels span{font-size:12px;height:1.2em;opacity:.8}
.in .bar i,.in .dcol i,.in .heat i{animation:var(--grow) .9s var(--e) calc(var(--t) + var(--o) * 35ms) both}.in .dcol i,.in .heat i{animation-name:var(--pop)}
.dots{display:flex;gap:3px;height:150px;margin:1em 0}.dcol{flex:1;display:flex;flex-direction:column-reverse;align-items:center;gap:3px}
.dcol i{width:min(12px,90%);aspect-ratio:1;border-radius:var(--dotr);background:var(--fg)}
.heat{display:flex;gap:3px;margin:1em 0}.heat>div{flex:1;text-align:center}.heat i{display:block;height:52px;background:var(--fg);border-radius:var(--rad)}
.lc{width:100%;height:140px;margin-top:1em;overflow:visible}.lc .area{fill:color-mix(in srgb,var(--fg) 18%,transparent)}
.lc .draw{fill:none;stroke:var(--fg);stroke-width:3;vector-effect:non-scaling-stroke;stroke-linecap:var(--cap)}
.in .lc .area{animation:fade 1.4s var(--t) both}@keyframes fade{from{opacity:0}}
.labels{display:flex;justify-content:space-between}
.radial{width:min(100%,340px,32svh);display:block;margin:1em auto}.radial line{stroke:var(--fg);stroke-linecap:var(--cap)}
.radial text{fill:var(--fg);font-size:9px;text-anchor:middle;dominant-baseline:middle;opacity:.8}
.draw{stroke-dasharray:100;stroke-dashoffset:0}.in .draw{animation:draw 1.4s var(--e) calc(var(--t) + var(--o,0) * 40ms) both}@keyframes draw{from{stroke-dashoffset:100}}
/* chrome */
.np{position:absolute;left:calc(24px + env(safe-area-inset-left));right:calc(24px + env(safe-area-inset-right));bottom:calc(24px + env(safe-area-inset-bottom));margin:0;display:flex;gap:12px;align-items:center;font-size:14px;opacity:0;transform:translateY(20px);transition:all .8s .8s}
.in .np{opacity:1;transform:none}.np img{width:52px;height:52px;border-radius:var(--np-r);box-shadow:0 4px 20px #0006;animation:var(--np-anim) 8s linear infinite paused}
.playing .np img{animation-play-state:running}@keyframes spin{to{transform:rotate(1turn)}}
@keyframes bob{25%{transform:translateY(-6px) rotate(-5deg)}75%{transform:translateY(3px) rotate(5deg)}}
button{font:inherit;color:var(--inv);background:var(--fg);border:0;border-radius:99px;padding:.7em 1.6em;font-weight:700;cursor:pointer;transition:transform .2s}
button:hover{transform:scale(1.06)}button:focus-visible{outline:3px solid var(--fg);outline-offset:3px}
#mute{position:fixed;top:calc(14px + env(safe-area-inset-top));right:calc(12px + env(safe-area-inset-right));z-index:9;width:44px;height:44px;padding:0;font-size:16px;line-height:44px;background:color-mix(in srgb,var(--inv) 30%,transparent);border:1px solid color-mix(in srgb,var(--fg) 35%,transparent)}
#dots{position:fixed;right:calc(14px + env(safe-area-inset-right));top:50%;transform:translateY(-50%);display:grid;gap:8px;z-index:9}
#dots i{width:6px;height:6px;border-radius:9px;background:color-mix(in srgb,var(--fg) 40%,transparent);transition:all .4s}#dots i.on{background:var(--fg);height:22px}
@media (max-width:640px){
  section{padding-right:calc(24px + env(safe-area-inset-right))}
  #dots{top:calc(8px + env(safe-area-inset-top));left:calc(12px + env(safe-area-inset-left));right:calc(12px + env(safe-area-inset-right));transform:none;grid-auto-flow:column;grid-auto-columns:1fr;gap:4px}
  #dots i,#dots i.on{width:auto;height:3px}#dots i.past{background:color-mix(in srgb,var(--fg) 75%,transparent)}
  #mute{top:calc(20px + env(safe-area-inset-top))}}
/* summary card (SVG) */
.card{width:min(400px,100%);margin:auto}.card svg{display:block;width:100%;height:auto;box-shadow:0 24px 40px #0007}
.card .patmove,.card .sticker,.card .vinyl,.card .cart{transform-box:fill-box;transform-origin:center}
.in .card .sticker{animation:spin 30s linear infinite}.playing .card .vinyl{animation:spin 9s linear infinite}
.in .card .cart{animation:breathe 7s ease-in-out infinite alternate}@keyframes breathe{to{transform:scale(1.05)}}
.save{text-align:center;margin-top:24px}
#seed{position:fixed;right:calc(12px + env(safe-area-inset-right));bottom:calc(8px + env(safe-area-inset-bottom));z-index:9;font-size:11px;opacity:.55;font-variant-numeric:tabular-nums;user-select:all}
/* loading screen: a record spins while fonts, covers and the first song get ready; tapping it starts the soundtrack */
html.loading{overflow:hidden}
#load{position:fixed;inset:0;z-index:20;display:grid;place-content:center;justify-items:center;gap:20px;padding:24px;text-align:center;cursor:pointer;
  background:radial-gradient(circle at 50% 38%,var(--b),var(--a) 70%);color:var(--fg);transition:opacity .7s,visibility .7s}
#load.done{opacity:0;visibility:hidden}
.deck{position:relative;width:min(64vw,300px);aspect-ratio:1;transition:transform .7s cubic-bezier(.5,0,.2,1)}#load.done .deck{transform:scale(1.5)}
.disc{position:absolute;inset:0;border-radius:50%;display:grid;place-items:center;box-shadow:0 24px 60px #0009;animation:spin 2.4s linear infinite;
  background:radial-gradient(circle,var(--a) 0 2.4%,transparent 2.6%),radial-gradient(circle,var(--b) 0 31%,#0000 31.4%),
  radial-gradient(circle,#0000 0 95%,#2a2a2a 96%),repeating-radial-gradient(circle,#141414 0 2px,#1d1d1d 2px 4px)}
.disc b{font:var(--hw) clamp(18px,6vw,30px)/1 var(--small);translate:0 -.85em;color:var(--fg)}
.deck::after{content:"";position:absolute;inset:0;border-radius:50%;pointer-events:none;  /* the shine stays put while the record turns */
  background:conic-gradient(from 20deg,#0000,#fff2 8%,#0000 16%,#0000 50%,#fff2 58%,#0000 66%);mask:radial-gradient(circle,#0000 31%,#000 31.5% 96%,#0000 96.5%)}
#load.ready .disc{animation-duration:1.6s}
#load p{margin:0;font-weight:600;letter-spacing:.02em}#load small{opacity:.75}
.prog{width:min(56vw,220px);height:4px;border-radius:9px;background:color-mix(in srgb,var(--fg) 25%,transparent);overflow:hidden}
.prog i{display:block;height:100%;width:0;background:var(--fg);transition:width .4s}
#start{visibility:hidden;opacity:0;transition:opacity .4s}#load.ready #start{visibility:visible;opacity:1}#load.ready .prog{display:none}
@media (prefers-reduced-motion:reduce){*,*::before{animation:none!important;transition:none!important}.a{opacity:1}html{scroll-behavior:auto}}
"""

JS = """
const secs=[...document.querySelectorAll('section')],dots=document.getElementById('dots'),mute=document.getElementById('mute');
secs.forEach(()=>dots.append(document.createElement('i')));
const players={};let sound=false,cur=null;
function fade(a,to){const from=a.volume,t0=performance.now();cancelAnimationFrame(a._f);
  (function f(t){const k=Math.max(0,Math.min(1,(t-t0)/700));a.volume=from+(to-from)*k;if(k<1)a._f=requestAnimationFrame(f);else if(!to)a.pause()})(t0)}
function player(src){  // one looping player per song, parked at 35% (usually past the intro) once its length is known
  if(!players[src]){const a=players[src]=Object.assign(new Audio(),{loop:true,volume:0,preload:'metadata'});
    a._ready=new Promise(r=>{a.addEventListener('loadedmetadata',()=>{a.currentTime=a.duration*.35;r()},{once:true});a.addEventListener('error',r,{once:true})});a.src=src}
  return players[src]}
function play(sec){
  const src=sec&&sec.dataset.audio,next=src&&player(src);
  // fade out every other player, not just the last one: fast scrolling could leave a half-faded song running
  Object.values(players).forEach(a=>{if(a!==next||!sound)a.paused?cancelAnimationFrame(a._f):fade(a,0)});
  if(next&&sound){next.play().catch(()=>{});fade(next,1)}
  cur=next||null;secs.forEach(s=>s.classList.toggle('playing',sound&&s===sec&&!!next));
  // lock screen / headphone controls show the slide's song
  if(next&&'mediaSession'in navigator){const d=sec.dataset;navigator.mediaSession.metadata=new MediaMetadata({title:d.title,artist:d.artist,
    album:document.title,artwork:d.cover?[{src:new URL(d.cover,location).href}]:[]});navigator.mediaSession.playbackState=sound?'playing':'paused'}
}
if('mediaSession'in navigator)[['play',()=>setSound(true)],['pause',()=>setSound(false)],['nexttrack',()=>go(1)],['previoustrack',()=>go(-1)]]
  .forEach(([k,f])=>{try{navigator.mediaSession.setActionHandler(k,f)}catch{}});
// keep the screen on while the soundtrack plays (the lock is dropped by the browser when the tab hides)
let lock=null;async function wake(){try{lock=sound&&!document.hidden?await navigator.wakeLock?.request('screen'):(lock?.release(),null)}catch{}}
const theme=document.querySelector('meta[name=theme-color]');
function count(h){const n=+h.dataset.n,t0=performance.now();
  if(matchMedia('(prefers-reduced-motion:reduce)').matches)return;
  (function f(t){const k=Math.min(1,(t-t0)/1400),s=Math.round(n*(1-Math.pow(1-k,4))).toLocaleString('en-US');
    if(h.textContent!==s)h.textContent=s;if(k<1)requestAnimationFrame(f)})(t0)}
let active=null,settled=false,st;  // settled turns true when the loading screen is dismissed
// a slide animates in only once scrolling has stopped, so the swipe itself never competes with text animation
function enter(sec){if(sec.classList.contains('in'))return;sec.classList.add('in');
  const idx=secs.indexOf(sec);[...dots.children].forEach((d,i)=>d.className=i===idx?'on':i<idx?'past':'');
  theme.content=getComputedStyle(sec).getPropertyValue('--a').trim();  // browser bar matches the slide
  sec.querySelectorAll('[data-n]').forEach(count);play(sec)}
const settle=()=>{clearTimeout(st);settled=true;active&&enter(active)};
addEventListener('scrollend',settle);  // the timeout covers browsers without scrollend
addEventListener('scroll',()=>{settled=false;clearTimeout(st);st=setTimeout(settle,'onscrollend'in window?800:150)},{passive:true});
const io=new IntersectionObserver(es=>es.forEach(en=>{
  if(!en.isIntersecting)return en.target.classList.remove('in');
  active=en.target;if(settled)enter(active);
}),{threshold:.55});
secs.forEach(s=>io.observe(s));
function setSound(on){sound=on;mute.textContent=on?'🔊':'🔇';mute.setAttribute('aria-label',on?'Mute':'Unmute');play(active);wake()}
mute.onclick=()=>setSound(!sound);
// loading screen: everything a slide needs is ready before the first one shows, so nothing pops in or hitches mid-animation
const load=document.getElementById('load'),wait=ms=>new Promise(r=>setTimeout(r,ms));
document.documentElement.classList.add('loading');
{const jobs=[document.fonts.ready.then(fit),
    ...[...document.images].map(i=>i.decode().catch(()=>{})),  // decoded now, not on the frame the slide arrives
    ...secs.filter(s=>s.dataset.audio).map((s,i)=>i?(player(s.dataset.audio),0):player(s.dataset.audio)._ready)];  // first song buffered, the rest just metadata
  let n=0;jobs.forEach(j=>Promise.resolve(j).finally(()=>load.querySelector('.prog i').style.width=++n/jobs.length*100+'%'));
  // at least long enough to see the record, never more than 8s even on a slow connection
  Promise.all([Promise.race([Promise.all(jobs),wait(8000)]),wait(1200)]).then(()=>{load.classList.add('ready');
    load.querySelector('p').textContent='Ready when you are'})}
function begin(){if(!load.classList.contains('ready')||load.classList.contains('done'))return;
  load.classList.add('done');document.documentElement.classList.remove('loading');setSound(true);settle()}
load.onclick=begin;
// Save image: the card is an SVG, so serialize it with the embedded fonts and rasterize it: exactly what's on screen.
document.getElementById('save').onclick=async ev=>{
  const btn=ev.currentTarget;btn.disabled=true;
  try{
    const svg=document.querySelector('.card svg'),vb=svg.viewBox.baseVal,W=1080,H=Math.round(W*vb.height/vb.width),clone=svg.cloneNode(true);
    clone.setAttribute('width',W);clone.setAttribute('height',H);
    clone.querySelectorAll('[data-n]').forEach(n=>n.textContent=(+n.dataset.n).toLocaleString('en-US'));
    const st=document.createElementNS('http://www.w3.org/2000/svg','style');st.textContent=document.getElementById('fonts').textContent;clone.prepend(st);
    const img=new Image();img.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(new XMLSerializer().serializeToString(clone));await img.decode();
    const cv=Object.assign(document.createElement('canvas'),{width:W,height:H});cv.getContext('2d').drawImage(img,0,0,W,H);
    const blob=await new Promise(r=>cv.toBlob(r,'image/png')),file=new File([blob],`wrapped-${btn.dataset.year}.png`,{type:'image/png'});
    if(navigator.canShare?.({files:[file]}))try{await navigator.share({files:[file]});return}catch(err){if(err.name==='AbortError')return}
    const a=Object.assign(document.createElement('a'),{href:URL.createObjectURL(blob),download:file.name});a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);
  }finally{btn.disabled=false}
};
// Share the page link: share sheet where supported, otherwise copy it. Pointless on file://, so hidden there.
const share=document.getElementById('share');share.hidden=location.protocol==='file:';
share.onclick=async()=>{const url=location.href.split('#')[0];
  if(navigator.share)try{await navigator.share({title:document.title,url});return}catch(err){if(err.name==='AbortError')return}
  try{await navigator.clipboard.writeText(url);share.textContent='✓ Link copied'}catch{prompt('Copy this link',url)}
  setTimeout(()=>share.textContent='↗ Share',2000)};
// SVG text can't wrap or ellipsize: once fonts are in, shrink data-fs text to fit, then trim data-w text with an ellipsis.
function fit(){
  document.querySelectorAll('textPath[data-unit]').forEach(tp=>{const u=tp.dataset.unit;tp.textContent=u;
    const w=tp.parentNode.getComputedTextLength();if(w)tp.textContent=u.repeat(Math.max(1,Math.floor(804/w)))});
  // headlines: shrink until the longest word fits (wide fonts would otherwise overflow or split words)
  document.querySelectorAll('section h1').forEach(h=>{h.classList.add('fit');let f=parseFloat(getComputedStyle(h).fontSize);
    const w=h.closest('section>div').clientWidth;
    while(f>20&&h.scrollWidth>w+1){f*=.93;h.style.fontSize=f.toFixed(1)+'px'}h.classList.remove('fit')});
  document.querySelectorAll('text[data-fs]').forEach(t=>{const w=+t.dataset.fs;let f=+t.getAttribute('font-size');
    while(f>(+t.dataset.min||14)&&t.getComputedTextLength()>w){f*=.94;t.setAttribute('font-size',f.toFixed(1))}});
  document.querySelectorAll('text[data-w]').forEach(t=>{const w=+t.dataset.w;let s=t.textContent;
    while(s&&t.getComputedTextLength()>w){s=s.slice(0,-1);t.textContent=s.trimEnd()+'…'}})}
let tgt=null;  // pending target while a smooth scroll runs, so quick taps queue up instead of being lost
function go(d){
  const i=tgt??secs.reduce((b,s,j)=>Math.abs(s.getBoundingClientRect().top)<Math.abs(secs[b].getBoundingClientRect().top)?j:b,0),t=secs[i+d];
  if(!t)return;tgt=i+d;t.scrollIntoView();clearTimeout(go.t);go.t=setTimeout(()=>tgt=null,900);return true}
document.addEventListener('keydown',ev=>{
  if(document.documentElement.classList.contains('loading')){if(['Enter',' '].includes(ev.key))begin(),ev.preventDefault();return}
  if(['ArrowDown','PageDown',' '].includes(ev.key)&&go(1))ev.preventDefault();
  if(['ArrowUp','PageUp'].includes(ev.key)&&go(-1))ev.preventDefault()});
// tap/click to advance (left edge goes back), like stories; scrolling still works
document.addEventListener('click',ev=>{
  if(ev.target.closest('button,a,input,#load')||String(getSelection()).length)return;
  go(ev.clientX<innerWidth*.25?-1:1)});
// background tab or screen off: rAF fades stall, so pause hard and resume on return
document.addEventListener('visibilitychange',()=>{
  if(document.hidden)Object.values(players).forEach(a=>{cancelAnimationFrame(a._f);a.pause()});else play(active),wake()});
"""


def render(s, year, media=None, seed=None, month=None):
    """month=None: the year's recap; month=1..12: just that month."""
    media = media or {}
    period = f"{datetime(year, month, 1):%B %Y}" if month else str(year)
    unit, short = ("month", f"{datetime(year, month, 1):%b %Y}") if month else ("year", str(year))
    slug = f"{year}-{month:02d}" if month else str(year)
    if not s["plays"]:
        return f"<h1>No listens found for {period}.</h1>"
    g = Gen(seed if seed is not None else random.getrandbits(64))
    wd = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    a1, t1 = s["artists"][0], s["tracks"][0]
    artist_item = lambda k: f"{e(k[0])} <em>{e(k[1])}</em>"
    lib_frac = 1 - s["never_played"] / s["lib_songs"] if s["lib_songs"] else None

    slides = [  # (key, label, [block(t) ...])
        ("intro", f"Your {period} in music", [
            lambda t: g.number(s["minutes"], t),
            lambda t: g.text("minutes listened", t),
            lambda t: g.text(f"{s['plays']:,} plays · {s['active_days']} active days · {s['minutes'] / 60 / 24:.1f} days of audio", t, "sub")]),
        ("artist", "Your top artist", [
            lambda t: g.headline(a1[0], t), lambda t: g.text(f"{a1[1]} plays", t),
            lambda t: g.ranks([(e(a), n) for a, n in s["artists"][1:10]], t)]),
        ("track", f"Your song of the {unit}", [
            lambda t: g.headline(t1[0][0], t), lambda t: g.text(f"{e(t1[0][1])} · {t1[1]} plays", t),
            lambda t: g.ranks([(artist_item(k), n) for k, n in s["tracks"][1:10]], t)]),
    ]
    if s["albums"]:
        top_album = s["albums"][0]
        slides.append(("album", f"Your album of the {unit}", [
            lambda t: g.headline(top_album[0][0], t), lambda t: g.text(f"{e(top_album[0][1])} · {top_album[1]} plays", t),
            lambda t: g.ranks([(artist_item(k), n) for k, n in s["albums"][1:10]], t)]))
    slides.append(("explore", "You explored", [
        lambda t: g.number(s["n_artists"], t), lambda t: g.text("artists", t),
        lambda t: g.text(f"{s['n_tracks']:,} tracks · {s['n_albums']:,} albums", t, "sub")]))
    if s["new"]:
        slides.append(("new", f"New to you in {period}", [
            lambda t: g.number(s["n_new"], t, s["n_new"] / max(1, s["n_artists"])), lambda t: g.text("artists discovered", t),
            lambda t: g.text(f"Your biggest find: <b>{e(s['new'][0][0])}</b>", t, "sub"),
            lambda t: g.ranks([(e(a), n) for a, n in s["new"][:8]], t)]))
    if s["genres"]:
        slides.append(("genre", "Your top genre", [
            lambda t: g.headline(s["genres"][0][0], t), lambda t: g.ranks([(e(x), n) for x, n in s["genres"][1:]], t)]))
    if not month:
        slides.append(("month", "Your peak month", [
            lambda t: g.headline(f"{datetime(year, s['peak_month'], 1):%B}", t), lambda t: g.chart(s["months"], "JFMAMJJASOND", t)]))
    slides += [
        ("hour", "Your listening hour", [
            lambda t: g.headline(f"{s['peak_hour']:02d}:00", t),
            lambda t: g.chart(s["hours"], [f"{h}" if h % 6 == 0 else "" for h in range(24)], t),
            lambda t: g.chart(s["weekdays"], wd, t)]),
        ("streak", "Longest streak", [
            lambda t: g.number(s["streak"], t, s["streak"] / (31 if month else 365)), lambda t: g.text("days in a row with music", t)]
         + ([lambda t: g.text(f"Biggest day: {s['top_day'][0]:%d %B} with {s['top_day'][1]} plays", t, "sub")] if s["top_day"] else [])),
    ]
    if s["lib_songs"]:
        slides.append(("library", "Your Navidrome library", [
            lambda t: g.number(s["lib_songs"], t, lib_frac), lambda t: g.text("songs", t),
            lambda t: g.text(f"{s['lib_starred']:,} starred · {s['never_played']:,} never played", t, "sub"),
            lambda t: g.text("All-time most played on your server:", t),
            lambda t: g.ranks([(artist_item((x.get("title"), x.get("artist"))), x.get("playCount", 0)) for x in s["lib_top"]], t)]))

    total = len(slides) + 1
    body = ""
    for i, (key, label, blocks) in enumerate(slides):
        content = g.label(label, i + 1, total, 0) + "".join(b((j + 1) * g.stg) for j, b in enumerate(blocks))
        body += section(g, i, key, content, media)

    # summary card
    art = media.get("card_art") or (media.get("artist") or {}).get("cover") or (media.get("summary") or {}).get("cover")
    last_label, last_value = ("Top Genre", s["genres"][0][0]) if s["genres"] else ("New Artists", f"{s['n_new']:,}")
    d = {"year": short, "artists": [a for a, _ in s["artists"][:5]], "songs": [t for (t, _), _ in s["tracks"][:5]],
         "minutes": s["minutes"], "label": last_label, "value": last_value, "name": a1[0], "art": art}
    content = (f'<div class=a style="--m:{g.card_kf};--d:1.2s;--t:0s;--e:{g.eases[0]}"><div class=card>{g.card_svg(d)}</div></div>'
               + g.anim(f"<p class=save><button id=save data-year={slug}>⬇ Save image</button> <button id=share hidden>↗ Share</button></p>", .6))
    body += section(g, len(slides), "summary", content, media, decor=False)

    root = g.root_css()  # after components, so all generated keyframes exist
    return (f'<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name=theme-color content="{g.palette[0][0]}">'
            f'<meta name=generator content="navidrome-wrapped, design seed {g.seed}"><title>Wrapped {short}</title>'
            f'<style id=fonts>{g.font_css(body)}</style><style>{CSS}{root}{"".join(g.css)}</style><button id=mute aria-label=Unmute>🔇</button><nav id=dots aria-hidden=true></nav><small id=seed>seed {g.seed}</small>'
            f'<div id=load style="--a:{g.palette[0][0]};--b:{g.palette[0][1]}" role=dialog aria-label="Wrapped {short}"><div class=deck><div class=disc><b>{e(short)}</b></div></div>'
            f'<p>Warming up your {unit}</p><div class=prog><i></i></div><button id=start>▶ Tap to play</button><small>sound on</small></div>'
            f'<noscript><style>#load{{display:none}}</style></noscript>{body}<script>{JS}</script></html>')


def section(g, i, key, content, media, decor=True):
    m = media.get(key, {})
    a, b = g.palette[i % len(g.palette)]
    attr = (f' data-audio="{e(m["audio"])}" data-title="{e(m["title"])}" data-artist="{e(m["artist"])}"'
            + (f' data-cover="{e(m["cover"])}"' if m.get("cover") else "")) if m.get("audio") else ""
    img = f'src="{e(m["cover"])}" alt=""' if m.get("cover") else ""
    bg = f"<img class=bg {img}>" if img else ""
    deco = "".join(g.decor() for _ in range(g.r.choice([1, 1, 2]))) if decor else ""
    np = (f"<figure class=np>{f'<img {img}>' if img else ''}"
          f'<figcaption>♪ {e(m["title"])}<br><em>{e(m["artist"])}</em></figcaption></figure>') if m.get("audio") else ""
    return f'<section class={key} style="--a:{a};--b:{b};{g.layout()}"{attr}>{bg}{deco}<div>{content}</div>{np}</section>'


INDEX_CSS = """
body{margin:0;min-height:100svh;background:#0d0d0f;color:#f3f1ec;font:16px/1.4 system-ui,sans-serif;-webkit-tap-highlight-color:transparent}
main{max-width:960px;margin:0 auto;padding:calc(48px + env(safe-area-inset-top)) 20px calc(40px + env(safe-area-inset-bottom))}
h1,.rc h2{font-family:var(--disp);font-weight:800;letter-spacing:-.03em;line-height:.9;margin:0}
h1{font-size:clamp(56px,16vw,128px)}
header p{opacity:.6;margin:.8em 0 2.4em}
.yr{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,150px),1fr));gap:12px;margin-bottom:28px}
.rc{position:relative;overflow:hidden;container-type:inline-size;display:flex;flex-direction:column;justify-content:flex-end;gap:4px;padding:92px 16px 16px;
  border-radius:20px;color:var(--fg);text-decoration:none;background:linear-gradient(150deg,var(--a),var(--b));
  animation:up .6s cubic-bezier(.2,.9,.3,1) calc(var(--i) * 60ms) both;transition:transform .2s}
.rc:hover{transform:translateY(-3px)}.rc:active{transform:scale(.97)}.rc:focus-visible{outline:3px solid #f3f1ec;outline-offset:3px}
.rc h2{font-size:min(34px,18cqi);position:relative}.rc small{opacity:.75;position:relative}.rc p{margin:0;position:relative}.rc b{font-size:1.15em}
.rc img{position:absolute;top:14px;right:14px;width:64px;height:64px;border-radius:50%;object-fit:cover;box-shadow:0 6px 20px #0006}
.rc i{position:absolute;top:14px;left:14px;font:600 11px system-ui;text-transform:uppercase;letter-spacing:.1em;padding:4px 8px;border-radius:99px;
  background:color-mix(in srgb,var(--fg) 18%,transparent)}
.rc.big{grid-column:1/-1;min-height:260px;padding:24px}.rc.big h2{font-size:clamp(64px,17vw,150px)}
.rc.big img{width:min(30%,200px);height:auto;aspect-ratio:1;top:24px;right:24px;border-radius:16px;rotate:4deg}
.empty{opacity:.7;font-size:18px}
@keyframes up{from{opacity:0;transform:translateY(24px)}}
@media (prefers-reduced-motion:reduce){.rc{animation:none;transition:none}}
"""


def index_page(recaps):
    """The overview at /: one card per recap, in that recap's own colours. recaps: [(slug, meta)], slug '2026' or '2026-11'."""
    years, n = {}, 0
    for slug, m in recaps:
        years.setdefault(slug[:4], []).append((slug, m))
    body = ""
    for y in sorted(years, reverse=True):
        cards = ""
        for slug, m in sorted(years[y], key=lambda x: (len(x[0]) == 4, x[0]), reverse=True):  # year first, then newest month
            big, n = len(slug) == 4, n + 1
            title = y if big else f"{datetime.strptime(slug, '%Y-%m'):%B}"
            sub = "the whole year" if big else y
            if m.get("partial"):
                sub += " so far"
            stats = (f"<p><b>{m['minutes']:,}</b> minutes</p>" if m.get("minutes") is not None else "")
            stats += f"<p><small>Top artist</small> {e(m['artist'])}</p>" if m.get("artist") else ""
            img = f'<img src="{e(slug)}/{e(m["cover"])}" alt="" loading=lazy>' if m.get("cover") else ""
            badge = "<i>in progress</i>" if m.get("partial") else ""
            cards += (f'<a class="rc{" big" if big else ""}" href="{e(slug)}/" style="--a:{m.get("a", "#2a2a33")};--b:{m.get("b", "#46465a")};'
                      f'--fg:{m.get("fg", "#ffffff")};--i:{n}">{img}{badge}<h2>{e(title)}</h2><small>{e(sub)}</small>{stats}</a>')
        body += f'<section class=yr aria-label="{y}">{cards}</section>'
    if not recaps:
        body = "<p class=empty>Your first recap is being built. This page refreshes on its own and lists it when it's ready.</p>"
    count = f"{len(recaps)} recap{'s' if len(recaps) != 1 else ''}" if recaps else "Nothing here yet"
    disp = "Funnel Display" if "Funnel Display" in MANIFEST else None  # 17KB, the lightest good display face
    fonts = font_face(disp, body) if disp else ""
    return (f'<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">'
            f'<meta name=theme-color content="#0d0d0f"><title>Wrapped</title>' + ("" if recaps else '<meta http-equiv=refresh content=60>')
            + f"<style>{fonts}:root{{--disp:{repr(disp) if disp else ''}, system-ui, sans-serif}}{INDEX_CSS}</style>"
            f"<main><header><h1>Wrapped</h1><p>Your music, recapped · {count}</p></header>{body}</main></html>")
