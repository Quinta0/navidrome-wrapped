#!/usr/bin/env python3
"""Download the bundled variable fonts (SIL Open Font License) from Google Fonts into fonts/.

Run once by maintainers; the results are committed so the app never needs the network for fonts.
Writes fonts/<slug>-<subset>.woff2, fonts/LICENSES/<slug>.txt and fonts/manifest.json (axes + unicode ranges).
"""
import json, os, re, urllib.parse, urllib.request

DISPLAY = ["Fraunces", "Recursive", "Roboto Flex", "Anybody", "Bricolage Grotesque", "Big Shoulders", "Unbounded", "Syne",
           "Playfair Display", "Shantell Sans", "Climate Crisis", "Bodoni Moda", "Archivo", "Martian Mono", "Sixtyfour",
           "Kablammo", "Tilt Warp", "Danfo", "Grandstander", "Bitcount Grid Double", "Handjet", "Doto", "Science Gothic",
           "Funnel Display", "Sour Gummy", "Caveat", "Instrument Serif", "Bungee", "Monoton", "Silkscreen", "Kode Mono",
           "Space Grotesk"]
BODY = ["Inter", "DM Sans", "Literata", "Manrope", "Outfit", "Figtree", "Newsreader", "Rubik", "Recursive",
        "Bricolage Grotesque", "Archivo", "Space Grotesk"]
SUBSETS = ("latin", "latin-ext")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"  # -> woff2
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fonts")


def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60) as r:
        return r.read()


def main():
    meta = json.loads(fetch("https://fonts.google.com/metadata/fonts"))
    fams = {f["family"]: f for f in meta["familyMetadataList"]}
    os.makedirs(os.path.join(OUT, "LICENSES"), exist_ok=True)
    manifest = {}
    for name in dict.fromkeys(DISPLAY + BODY):
        axes = {a["tag"]: [a["min"], a["max"], a["defaultValue"]] for a in fams[name].get("axes", [])}
        tags = sorted(axes, key=lambda t: (t.isupper(), t))  # API wants lowercase axes first, each group alphabetical
        spec = name + (":" + ",".join(tags) + "@" + ",".join(f"{axes[t][0]:g}..{axes[t][1]:g}" for t in tags) if tags else "")
        css = fetch("https://fonts.googleapis.com/css2?" + urllib.parse.urlencode({"family": spec, "display": "swap"})).decode()
        slug = re.sub(r"[^a-z0-9]", "", name.lower())
        files = []
        for subset, url, rng in re.findall(r"/\* ([\w-]+) \*/.*?src: url\((\S+?)\).*?unicode-range: ([^;]+);", css, re.S):
            if subset in SUBSETS and not any(f["subset"] == subset for f in files):
                fn = f"{slug}-{subset}.woff2"
                open(os.path.join(OUT, fn), "wb").write(fetch(url))
                files.append({"file": fn, "subset": subset, "range": rng})
        lic = fetch(f"https://raw.githubusercontent.com/google/fonts/main/ofl/{slug}/OFL.txt")
        open(os.path.join(OUT, "LICENSES", f"{slug}.txt"), "wb").write(lic)
        manifest[name] = {"category": fams[name]["category"], "axes": axes, "files": files,
                          "roles": [r for r, lst in (("display", DISPLAY), ("body", BODY)) if name in lst]}
        print(f"{name}: {len(files)} files, axes {' '.join(tags) or '-'}")
    json.dump(manifest, open(os.path.join(OUT, "manifest.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
