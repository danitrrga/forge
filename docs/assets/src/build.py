#!/usr/bin/env python3
"""Render the README images from their sources, the same way on any machine.

    python3 docs/assets/src/capture.py      # only when forge's output changed: rewrites transcript.json
    python3 docs/assets/src/build.py        # every page in PAGES -> docs/assets/<name>.png
    python3 docs/assets/src/build.py --preview DIR   # the pages, fonts and data in DIR, to look at live

Each page is plain HTML and CSS at a fixed size. The fonts are the exact files pinned in fonts.json, fetched once into
~/.cache/forge/readme-fonts and refused when a byte differs from the pin. The data every page draws (data.js) is made
here from transcript.json, which capture.py wrote from a real forge run, so an image cannot show output forge does not
print. The render is headless Chromium in a temporary directory; the PNG is reduced to a 256-colour palette.
A changed PNG needs its new sha256 in PUBLIC_ASSETS (forge/publish.py) after someone has looked at it: build.py prints it."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request

HERE = os.path.dirname(os.path.realpath(__file__))
OUT = os.path.dirname(HERE)
CACHE = os.path.join(os.path.expanduser("~"), ".cache", "forge", "readme-fonts")
CHROMIUM = os.environ.get("CHROMIUM", "/usr/bin/chromium")
# name: (width, height). The file is <name>.html beside this script and the image docs/assets/<name>.png.
PAGES = {"banner": (1280, 640), "social-preview": (1200, 630), "fig-sync": (1280, 560), "fig-trim": (1280, 480), "fig-bench": (1280, 400)}
SHARED = ("carbon.css",)


def fonts():
    """[(pin, path)] with every file present in the cache and matching its sha256."""
    pins = json.load(open(os.path.join(HERE, "fonts.json")))["fonts"]
    os.makedirs(CACHE, exist_ok=True)
    out = []
    for p in pins:
        path = os.path.join(CACHE, p["file"])
        if not os.path.exists(path):
            url = "https://cdn.jsdelivr.net/npm/%s@%s/files/%s" % (p["package"], p["version"], p["file"])
            with urllib.request.urlopen(url, timeout=60) as r:
                data = r.read()
            with open(path + ".part", "wb") as fh:
                fh.write(data)
            os.replace(path + ".part", path)
        with open(path, "rb") as fh:
            got = hashlib.sha256(fh.read()).hexdigest()
        if got != p["sha256"]:
            sys.exit("! %s: sha256 %s, the pin says %s -- refusing to render with a different font" % (p["file"], got, p["sha256"]))
        out.append((p, path))
    return out


def stage(dst):
    """The pages, the shared CSS, the fonts, fonts.css and data.js in dst."""
    os.makedirs(os.path.join(dst, "fonts"), exist_ok=True)
    css = []
    for p, path in fonts():
        shutil.copy(path, os.path.join(dst, "fonts", p["file"]))
        css.append('@font-face{font-family:"%s";src:url("fonts/%s") format("woff2");font-weight:%d;font-style:normal;font-display:block}'
                   % (p["family"], p["file"], p["weight"]))
    with open(os.path.join(dst, "fonts.css"), "w") as fh:
        fh.write("\n".join(css) + "\n")
    t = json.load(open(os.path.join(HERE, "transcript.json")))
    with open(os.path.join(dst, "data.js"), "w") as fh:
        fh.write("window.FORGE = " + json.dumps(data(t), indent=1) + ";\n")
    for name in PAGES:
        shutil.copy(os.path.join(HERE, name + ".html"), dst)
    for s in SHARED:
        shutil.copy(os.path.join(HERE, s), dst)


def data(t):
    """What the pages draw, read off the transcript: the files forge wrote, and which project got which server and skill."""
    files = t["files"]
    api = json.loads(files["config/profiles/api.claude.json"])
    site = json.loads(files["config/profiles/site.claude.json"])
    claude = json.loads(files["~/.claude.json"])["projects"]
    overrides = json.loads(files["~/code/api/.claude/settings.local.json"]).get("skillOverrides", {})
    skills = ["review", "release"]
    servers = ["playwright", "docs"]
    rows = []
    for name, key in (("~/code/api", "~/code/api"), ("~/code/site", "~/code/site"), ("~/forge", "~/forge")):
        have = set(claude[key]["mcpServers"])
        off = overrides if name == "~/code/api" else {}
        rows.append([name, [int(s in have) for s in servers] + [int(off.get(k) != "off") for k in skills]])
    return {"files": files, "api": api, "site": site, "doctor": t["doctor"]["lines"], "sync": t["sync"]["lines"],
            "add": t["add-api"]["lines"],
            "matrix": {"cols": servers + skills, "kinds": ["server"] * len(servers) + ["skill"] * len(skills), "rows": rows}}


def render(dst):
    from PIL import Image
    for name, (w, h) in PAGES.items():
        png = os.path.join(dst, name + ".raw.png")
        r = subprocess.run([CHROMIUM, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                            "--window-size=%d,%d" % (w, h), "--virtual-time-budget=4000", "--screenshot=" + png,
                            "file://" + os.path.join(dst, name + ".html")], capture_output=True, text=True)
        if r.returncode or not os.path.exists(png):
            sys.exit("! chromium could not render %s: %s" % (name, r.stderr.strip()[-300:]))
        im = Image.open(png).convert("RGB")
        if im.size != (w, h):
            sys.exit("! %s rendered at %s, want %dx%d" % (name, im.size, w, h))
        target = os.path.join(OUT, name + ".png")
        im.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(target, optimize=True)
        with open(target, "rb") as fh:
            b = fh.read()
        print("%-16s %4dx%-4d %6.1f KB  sha256 %s" % (name, w, h, len(b) / 1024, hashlib.sha256(b).hexdigest()))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--preview", metavar="DIR", help="assemble the pages, fonts and data in DIR instead of rendering")
    a = ap.parse_args()
    if a.preview:
        stage(a.preview)
        print("staged %d page(s) in %s" % (len(PAGES), a.preview))
        return
    with tempfile.TemporaryDirectory(prefix="forge-assets-") as d:
        stage(d)
        render(d)


if __name__ == "__main__":
    main()
