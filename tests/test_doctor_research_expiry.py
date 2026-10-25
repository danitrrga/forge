#!/usr/bin/env python3
"""The `research expiry` row of forge doctor: a research markdown file under a project's .planning/research/ may
carry, in its first 20 lines, `expires: <date>` (bare, `Expires:`, or inside `---` front matter) and
`volatility: high|medium|low`; the date is the last day the research stands, so a file is expired the day after.
Until this row existed nothing noticed research going stale. A file with no header is counted, never flagged; a
malformed date is an `unreadable expiry`, a WARN too; zero files anywhere is a PASS that says so; a file over 1 MB
is skipped and said; the scan writes nothing.

Every date is built from a fixed base with timedelta, and `cli.today` is replaced, so no date is written in this
file and the run does not depend on the day it runs. Each case builds a toy forge (config/profiles) with toy
projects; the real profiles and projects are never read.
Red before the row, run on the code that did not have it (19 failures, exit 1; only "11 the row writes nothing" passed,
vacuously): "the row is registered = False, want
True"; "1 an expired file: WARN naming it = ('raised', \"AttributeError: module 'forge.cli' has no attribute
'research_expiry'\"), want ('WARN', ...)"; the same AttributeError for every other case, and "the row is in forge
doctor NAME = False, want True".
Negative control: with the comparison inverted (`expires < today` made `expires > today`) 11 cases fail, among them
 "1 an expired file: WARN naming it = ('PASS', '1 research file(s) in 1 project(s), 1 with an expiry, none
expired'), want ('WARN', ...)" and "2 a future date: PASS = ('WARN', ...), want ('PASS', ...)"."""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from forge import lib  # noqa: E402
import sandbox  # noqa: E402
from forge import cli  # noqa: E402

failures = []
BASE = datetime.date(1999, 6, 15)  # the day the row thinks it is
FIX = "re-check the research and move its expires date, or delete it"


def want(label, got, expected):
    if got != expected:
        failures.append("%s = %r, want %r" % (label, got, expected))


def day(offset):
    return (BASE + datetime.timedelta(days=offset)).isoformat()


def project(tmp, name, files, forge="forge"):
    """A toy project `name` holding `files` ({path under the project: text}), and its profile in the toy forge."""
    root = os.path.join(tmp, "proj-" + name)
    for rel, text in files.items():
        full = os.path.join(root, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(text)
    os.makedirs(root, exist_ok=True)
    profiles = os.path.join(tmp, forge, "config", "profiles")
    os.makedirs(profiles, exist_ok=True)
    with open(os.path.join(profiles, name + ".claude.json"), "w", encoding="utf-8") as fh:
        json.dump({"project": name, "project_path": root}, fh)
    return root


def row(tmp, only=None, forge="forge"):
    """The row over the toy forge at tmp/forge, as (level, detail); today is BASE."""
    saved = lib.PROFILES, getattr(cli, "today", None)
    lib.PROFILES = os.path.join(tmp, forge, "config", "profiles")
    cli.today = lambda: BASE
    try:
        res = cli.research_expiry(only) if only else cli.research_expiry()
        return (res.level, res.detail)
    except Exception as e:
        return ("raised", "%s: %s" % (type(e).__name__, e))
    finally:
        lib.PROFILES = saved[0]
        if saved[1] is None:
            del cli.today
        else:
            cli.today = saved[1]


def research(**files):
    return {".planning/research/%s.md" % k.replace("__", "/"): v for k, v in files.items()}


def main():
    tmp = sandbox.mkdtemp("doctor-research-expiry-")
    registered = {n: (c, f) for n, c, f in cli.CHECKS}.get("research expiry")
    want("the row is registered, with its fix", registered, (getattr(cli, "research_expiry", 0), FIX))

    # One toy forge per case: tmp/<case>/config/profiles, projects beside it.
    def world(case, projects):
        base = os.path.join(tmp, case)
        for name, files in projects.items():
            project(base, name, files)
        return base

    base = world("c1", {"p": research(old="---\ntitle: x\nexpires: %s\nvolatility: high\n---\nbody\n" % day(-1))})
    want("1 an expired file: WARN naming it", row(base), (
        "WARN", "1 research file(s) in 1 project(s), 1 with an expiry, 1 expired, 0 unreadable expiry; "
                "p/.planning/research/old.md (expired %s, volatility high)" % day(-1)))

    base = world("c2", {"p": research(fresh="expires: %s\n" % day(30), later="Expires: %s\nvolatility: low\n" % day(1))})
    want("2 a future date: PASS", row(base),
         ("PASS", "2 research file(s) in 1 project(s), 2 with an expiry, none expired"))

    base = world("c3", {"p": research(plain="# Findings\nno header here\n", more="x\n")})
    want("3 no header: PASS, counted, never flagged", row(base),
         ("PASS", "2 research file(s) in 1 project(s), 0 with an expiry, none expired"))

    base = world("c4", {"p": research(bad="expires: next tuesday\n", worse="expires: %s\n" % day(-1).replace("-", "/"),
                                      empty="expires:\n", ok="expires: %s\n" % day(5))})
    want("4 a malformed date: WARN, unreadable expiry", row(base), (
        "WARN", "4 research file(s) in 1 project(s), 1 with an expiry, 0 expired, 3 unreadable expiry; "
                "p/.planning/research/bad.md (unreadable expiry: 'next tuesday'); "
                "p/.planning/research/empty.md (unreadable expiry: ''); "
                "p/.planning/research/worse.md (unreadable expiry: '%s')" % day(-1).replace("-", "/")))

    # Two projects: the row reads both, and `only` scopes it to one (forge doctor NAME).
    base = world("c5", {"a": research(old="expires: %s\n" % day(-10)), "b": research(fine="expires: %s\n" % day(10))})
    want("5 two projects: the expired one is named", row(base)[0:1], ("WARN",))
    want("5 two projects, both counted", "2 research file(s) in 2 project(s)" in row(base)[1], True)
    want("5 scoped to b: PASS over b alone", row(base, only="b"),
         ("PASS", "1 research file(s) in 1 project(s), 1 with an expiry, none expired"))
    want("5 scoped to a: WARN naming a's file only", row(base, only="a"), (
        "WARN", "1 research file(s) in 1 project(s), 1 with an expiry, 1 expired, 0 unreadable expiry; "
                "a/.planning/research/old.md (expired %s)" % day(-10)))

    base = world("c6", {"p": {"README.md": "x\n"}, "q": {".planning/research/notes.txt": "expires: %s\n" % day(-1)}})
    want("6 no research directory, or no markdown in it: PASS with zero", row(base),
         ("PASS", "0 research file(s) in 0 project(s), no .planning/research/*.md to check"))
    base = os.path.join(tmp, "c6-none")
    os.makedirs(os.path.join(base, "forge", "config", "profiles"))
    want("6 no project at all: PASS with zero", row(base),
         ("PASS", "0 research file(s) in 0 project(s), no .planning/research/*.md to check"))

    big = "expires: %s\n" % day(-1) + "x" * (1024 * 1024 + 1)
    base = world("c7", {"p": research(huge=big, small="expires: %s\n" % day(3))})
    want("7 a file over 1 MB is skipped, and said", row(base),
         ("PASS", "1 research file(s) in 1 project(s), 1 with an expiry, none expired, 1 skipped (over 1 MB or a link)"))

    # The boundary: the date is the last day the research stands.
    base = world("c8", {"p": research(today="expires: %s\n" % day(0), yesterday="expires: %s\n" % day(-1))})
    want("8 expiring today is not expired, yesterday is", row(base)[1].split("; ", 1)[1:],
         ["p/.planning/research/yesterday.md (expired %s)" % day(-1)])

    # Header forms: front matter, bare, any case, a volatility in any case; line 20 counts, line 21 does not.
    pad = "filler\n" * 19
    base = world("c9", {"p": research(
        front="---\nExpires: %s\nVolatility: Medium\n---\n" % day(-2),
        bare="# Title\n\nEXPIRES:   %s  \n" % day(-3),
        line20=pad + "expires: %s\n" % day(-4),
        line21=pad + "\nexpires: %s\n" % day(-5),
        deep__nested__file="expires: %s\nvolatility: bogus\n" % day(-6))})
    level, detail = row(base)
    want("9 forms: level", level, "WARN")
    want("9 forms: the four in the first 20 lines are expired, line 21 is counted but not read",
         detail.split("; ", 1)[0], "5 research file(s) in 1 project(s), 4 with an expiry, 4 expired, 0 unreadable expiry")
    want("9 forms: each file named with its volatility only when valid", detail.split("; ")[1:], [
        "p/.planning/research/bare.md (expired %s)" % day(-3),
        "p/.planning/research/deep/nested/file.md (expired %s)" % day(-6),
        "p/.planning/research/front.md (expired %s, volatility medium)" % day(-2),
        "p/.planning/research/line20.md (expired %s)" % day(-4)])

    # At most 10 are named, then `and N more`.
    base = world("c10", {"p": research(**{"f%02d" % i: "expires: %s\n" % day(-1) for i in range(12)})})
    level, detail = row(base)
    parts = detail.split("; ")
    want("10 twelve expired: ten named, then 'and 2 more'", (len(parts), parts[-1:], parts[1:2], parts[10:11]),
         (12, ["and 2 more"], ["p/.planning/research/f00.md (expired %s)" % day(-1)],
          ["p/.planning/research/f09.md (expired %s)" % day(-1)]))

    # Read-only: nothing under the project or the toy forge changes.
    before = sandbox.manifest(base)
    row(base)
    want("11 the row writes nothing", sandbox.manifest(base) == before, True)

    # Wired into forge doctor NAME, and the date defaults to the real today.
    rows = [n for n, _, _ in cli.project_checks("p", {"project_path": "x"}, None)]
    want("12 the row is in forge doctor NAME", "research expiry" in rows, True)
    want("13 today() is the real date", getattr(cli, "today", lambda: None)(), datetime.date.today())

    for msg in failures:
        print("FAIL", msg)
    print("%d failure(s)" % len(failures))
    sandbox.cleanup(failures)
    sys.exit(1 if failures else 0)


main()
