#!/usr/bin/env python3
"""Real forge output for the README images: builds the toy world tests/test_fresh_install.py uses (an engine-only
copy of this checkout, a toy HOME, three toy projects, stubbed npm/pnpm/codex/systemctl), runs the commands a
newcomer runs, and writes transcript.json beside this file. Every line an image draws comes from that file, so an
image never shows output forge does not print. Paths are rewritten to the README's own spelling (~/forge,
~/code/<name>); nothing of the machine that ran it is kept.

    python3 docs/assets/src/capture.py        # then python3 docs/assets/src/build.py"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
FORGE = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(FORGE, "tests"))
import sandbox  # noqa: E402
from test_fresh_install import World  # noqa: E402

# The world a newcomer has after a week: one MCP server in the registry (no secret), one skill of their own, two projects,
# and the api project's profile asking for both. Each step is a forge command or a file a user writes by hand.
REGISTRY = {"servers": {"playwright": {"type": "stdio", "command": "playwright-mcp", "args": ["--headless"]},
                        "docs": {"type": "stdio", "command": "docs-mcp", "args": []}}}
SKILLS = {"review": "Review a diff before it is pushed.", "release": "Cut a release: changelog, tag, notes."}
COMMANDS = (
    ("init", ["init", "--yes", "--without", "codex,gsd"]),
    ("write", None),
    ("skills", ["skills", "--apply"]),
    ("add-api", ["add", "{projects}/api"]),
    ("add-site", ["add", "{projects}/site"]),
    ("profile", None),
    ("sync-dry", ["sync", "--all"]),
    ("sync", ["sync", "--apply", "--all"]),
    ("doctor", ["doctor"]),
)
# The files the images show, read back after the run.
FILES = ("config/profiles/api.claude.json", "config/profiles/site.claude.json", "{projects}/api/.claude/settings.local.json",
         "{home}/.claude.json")


def main():
    w = World("assets")
    projects = os.path.dirname(w.demo)
    for name in ("api", "site"):
        d = os.path.join(projects, name)
        os.makedirs(d)
        with open(os.path.join(d, "README.md"), "w") as fh:
            fh.write("%s\n" % name)
        sandbox.git(d, "init", "-q")
    out = {}
    for key, argv in COMMANDS:
        if key == "write":
            with open(w.path("config", "mcp-registry.json"), "w") as fh:
                json.dump(REGISTRY, fh, indent=2)
            for name, desc in SKILLS.items():
                os.makedirs(w.path("skills", name))
                with open(w.path("skills", name, "SKILL.md"), "w") as fh:
                    fh.write("---\nname: %s\ndescription: %s\n---\n%s\n" % (name, desc, desc))
            continue
        if key == "profile":
            for name, extra in (("api", {"servers": ["playwright"], "skills_keep": ["review"]}), ("site", {"servers": ["docs"]})):
                prof = w.path("config", "profiles", name + ".claude.json")
                with open(prof) as fh:
                    doc = json.load(fh)
                doc.pop("_doc", None)  # the user writing their own profile drops the example's documentation key
                doc.update(extra)
                with open(prof, "w") as fh:
                    json.dump(doc, fh, indent=2)
                    fh.write("\n")
            continue
        code, text = w.forge(*[a.format(projects=projects) for a in argv])
        for real, shown in ((w.root, "~/forge"), (projects, "~/code"), (w.home, "~"), (w.top, "")):
            text = text.replace(real, shown)
        # A tool found outside the world (init's preflight prints where `claude` lives) is shown by its name only.
        text = re.sub(r"(?:/home|/usr|/opt)/\S+", lambda m: os.path.basename(m.group(0)), text)
        out[key] = {"argv": ["forge"] + [a.replace("{projects}", "~/code") for a in argv], "exit": code,
                    "lines": [l.rstrip() for l in text.splitlines()]}
    files = {}
    for rel in FILES:
        full = rel.format(projects=projects, home=w.home)
        full = full if os.path.isabs(full) else w.path(*full.split("/"))
        with open(full, encoding="utf-8") as fh:
            text = fh.read()
        for real, shown in ((w.root, "~/forge"), (projects, "~/code"), (w.home, "~"), (w.top, "")):
            text = text.replace(real, shown)
            rel = rel.replace("{projects}", "~/code").replace("{home}", "~")
        files[rel] = text
    out["files"] = files
    leaks = [l for k, v in out.items() if k != "files" for l in v["lines"] if re.search(r"/tmp/|/home/", l)]
    leaks += [k for k, v in files.items() if re.search(r"/tmp/|/home/", v)]
    if leaks:
        sys.exit("refusing to write: a line still names a real path: %r" % leaks[:3])
    with open(os.path.join(HERE, "transcript.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
        fh.write("\n")
    for k, v in out.items():
        if k != "files":
            print("%-9s exit %d, %d line(s)" % (k, v["exit"], len(v["lines"])))
    print("files:", ", ".join(files))
    sandbox.cleanup(False)


if __name__ == "__main__":
    main()
