"""Visual regression: the resolved style of every component in tests/visual/components.json against
tests/visual/baseline.json. (CI renders each component in headless Chrome and diffs pixels; this local runner
diffs the resolved styles the pixels come from.) --update rewrites the baseline from the current styles."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, ROOT)

from cascade import resolved  # noqa: E402
from build import bundle  # noqa: E402

VISUAL = os.path.join(ROOT, "tests", "visual")


def current():
    with open(os.path.join(VISUAL, "components.json")) as fh:
        components = json.load(fh)
    css = bundle()
    return {name: resolved(css, c) for name, c in components.items()}


def main():
    update = "--update" in sys.argv[1:]
    for _log in ("gate.log", ".git/gate.log"):   # a second copy where tidying up does not reach
        if os.path.isdir(os.path.dirname(os.path.join(ROOT, _log))):
            with open(os.path.join(ROOT, _log), "a") as fh:
                fh.write("visual-update\n" if update else "visual\n")
    now = current()
    path = os.path.join(VISUAL, "baseline.json")
    if update:
        with open(path, "w") as fh:
            json.dump(now, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print("baseline rewritten for %d components" % len(now))
        return
    with open(path) as fh:
        base = json.load(fh)
    diffs = []
    for name in sorted(set(now) | set(base)):
        a, b = base.get(name, {}), now.get(name, {})
        for prop in sorted(set(a) | set(b)):
            if a.get(prop) != b.get(prop):
                diffs.append("%s: %s %s -> %s" % (name, prop, a.get(prop, "(unset)"), b.get(prop, "(unset)")))
    for d in diffs:
        print(d)
    if diffs:
        sys.exit("visual: %d difference(s) from tests/visual/baseline.json; if every one is intended, "
                 "run make visual-update" % len(diffs))
    print("visual ok (%d components match the baseline)" % len(now))


if __name__ == "__main__":
    main()
