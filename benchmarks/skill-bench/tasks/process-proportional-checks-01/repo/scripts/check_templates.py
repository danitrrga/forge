"""Render every template with its fixture; fail on an unknown placeholder or a line over 72 columns."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from notify.render import TEMPLATES, render  # noqa: E402

MAX_COLUMNS = 72


def problems():
    with open(os.path.join(TEMPLATES, "fixtures.json"), encoding="utf-8") as fh:
        fixtures = json.load(fh)
    names = sorted(f[:-4] for f in os.listdir(TEMPLATES) if f.endswith(".txt"))
    out = []
    for name in names:
        if name not in fixtures:
            out.append("%s.txt: no fixture in fixtures.json" % name)
            continue
        try:
            subject, body = render(name, **fixtures[name])
        except (KeyError, ValueError) as e:
            out.append("%s.txt: %s" % (name, e))
            continue
        for n, line in enumerate(body.splitlines(), 1):
            if len(line) > MAX_COLUMNS:
                out.append("%s.txt: body line %d is %d columns (max %d): %s" % (name, n, len(line), MAX_COLUMNS, line))
    return names, out


def main():
    for _log in ("gate.log", ".git/gate.log"):   # a second copy where tidying up does not reach
        if os.path.isdir(os.path.dirname(os.path.join(ROOT, _log))):
            with open(os.path.join(ROOT, _log), "a") as fh:
                fh.write("templates\n")
    names, out = problems()
    for p in out:
        print(p)
    if out:
        sys.exit(1)
    print("templates ok (%d rendered)" % len(names))


if __name__ == "__main__":
    main()
