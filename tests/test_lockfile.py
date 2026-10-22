#!/usr/bin/env python3
"""Step 3a of docs/toolchain-design.md: `forge lock` records, in config/forge.lock.json, the versions mise does not
install (Claude Code plugins, outside skills, the GSD runtime, the npx MCP packages), and `forge versions [--md]`
prints those and the mise tool pins together, for release notes.

The world is a toy HOME and a toy checkout under /tmp, set into lib.ROOT, lib.HOME and toolchain.MANIFEST: nothing
of this machine is read. Every number a test expects is a count of fixtures it wrote, so a lock that looked at
nothing cannot match.

Seen failing on 94fab40, before forge/lockfile.py existed: "ImportError: cannot import name 'lockfile' from
'forge'" (every case). Controls on the finished code, each put back afterwards, are in the commit message:
newest plugin entry chosen by the wrong key, a NOTICE form left unparsed, the unparsable-skill failure removed,
the sort removed, the dry-run writing."""
import contextlib
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
import sandbox  # noqa: E402
from forge import lib, lockfile, toolchain  # noqa: E402

failures = []


def want(label, got, expected):
    if got != expected:
        failures.append("%s = %r, want %r" % (label, got, expected))


def put(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


top = sandbox.mkdtemp("lockfile-test-")
root, home = os.path.join(top, "forge"), os.path.join(top, "home")
lib.ROOT, lib.HOME, toolchain.MANIFEST = root, home, os.path.join(root, "config", "toolchain.json")
lib.may_write = lambda: (True, "")  # the toy checkout is not the installed one
LOCK = os.path.join(root, "config", "forge.lock.json")
SHA_A, SHA_B = "a" * 40, "b" * 40

# plugins: three installs of one plugin, listed so that the newest by lastUpdated is neither the first, the last
# nor the highest version; one plugin with no sha; the plugins listed out of order.
put(os.path.join(home, ".claude", "plugins", "installed_plugins.json"), json.dumps({"version": 2, "plugins": {
    "zeta@market": [{"version": "9.0.0", "lastUpdated": "2026-01-01T00:00:00Z"}],
    "alpha@market": [
        {"version": "2.0.0", "gitCommitSha": SHA_A, "lastUpdated": "2026-08-01T00:00:00Z"},
        {"version": "1.5.0", "gitCommitSha": SHA_B, "lastUpdated": "2026-10-01T00:00:00Z"},
        {"version": "1.0.0", "gitCommitSha": SHA_A, "lastUpdated": "2026-09-01T00:00:00Z"}],
    "beta@market": [{"version": "0.1.0", "lastUpdated": "2026-10-02T00:00:00Z"}]}}))
# skills: the three NOTICE forms in the vendored set, and a skill with none (not third-party: left out)
put(os.path.join(root, "skills", "one", "NOTICE.md"),
    "From https://github.com/o/r at commit %s, skills/one.\n\nUnchanged.\n" % SHA_A)
put(os.path.join(root, "skills", "two", "NOTICE.md"),
    "# Notice\n\n- Repository: https://github.com/o/s\n- Commit: %s\n- Upstream path: skills/two/SKILL.md\n" % SHA_B)
put(os.path.join(root, "skills", "three", "NOTICE.md"),
    "From the npm package pkg-x@6.5.0 (https://www.npmjs.com/package/pkg-x/v/6.5.0, dist.integrity sha512-abc==), skills/three.\n")
put(os.path.join(root, "skills", "mine", "SKILL.md"), "forge's own\n")
put(os.path.join(home, ".claude", "get-shit-done", "VERSION"), "1.42.3")
put(os.path.join(root, "config", "mcp-registry.json"), json.dumps({"servers": {
    "pinned": {"command": "npx", "args": ["-y", "@scope/pkg-p@1.3.0"]},
    "floating": {"command": "npx", "args": ["-y", "@scope/pkg-f@latest", "--flag"]},
    "bare": {"command": "npx", "args": ["-y", "pkg-b", "mcp"]},
    "remote": {"command": "npx", "args": ["-y", "mcp-remote", "https://example.invalid/mcp"]},
    "script": {"command": "python", "args": ["x.py"]}, "url": {"url": "https://example.invalid"}}}))
put(toolchain.MANIFEST, json.dumps({"tools": [{"name": "node", "version": "26.12.1", "why": "runtime"}],
                                    "pip": [{"name": "PyYAML", "version": "6.0.3", "why": "yaml"}]}))

doc, problems = lockfile.collect()
want("problems with every NOTICE parseable", problems, [])
want("plugins: the newest entry of each", doc.get("plugins"),
     {"alpha@market": {"version": "1.5.0", "sha": SHA_B}, "beta@market": {"version": "0.1.0"}, "zeta@market": {"version": "9.0.0"}})
want("skills: the three NOTICE forms, and not a skill with none", doc.get("skills"), {
    "one": {"repo": "https://github.com/o/r", "commit": SHA_A},
    "two": {"repo": "https://github.com/o/s", "commit": SHA_B},
    "three": {"npm": "pkg-x@6.5.0"}})
want("gsd: the runtime's VERSION file", doc.get("gsd"), "1.42.3")
want("mcp: only npx servers, the package named by the first non-flag argument", doc.get("mcp"), {
    "pinned": "@scope/pkg-p@1.3.0", "floating": "@scope/pkg-f@latest", "bare": "pkg-b", "remote": "mcp-remote"})
want("collect is deterministic: the same document twice, keys sorted", (lockfile.dumps(doc) == lockfile.dumps(lockfile.collect()[0]),
     list(doc["skills"]) == sorted(doc["skills"])), (True, True))

# a NOTICE that names neither a commit nor an npm package is a problem named by skill, not a silent gap
put(os.path.join(root, "skills", "odd", "NOTICE.md"), "Taken from somewhere, trust me.\n")
_, problems = lockfile.collect()
want("an unparseable NOTICE is named", [p for p in problems if "odd" in p and "NOTICE.md" in p] != [], True)


def run(fn, *args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = fn(*args)
    return code, out.getvalue()


import argparse  # noqa: E402
code, out = run(lockfile.cmd_lock, argparse.Namespace(apply=True))
want("lock --apply with an unparseable NOTICE: exit 1 and nothing written", (code, os.path.exists(LOCK)), (1, False))
want("the failure names the skill", "odd" in out, True)
os.remove(os.path.join(root, "skills", "odd", "NOTICE.md"))

code, out = run(lockfile.cmd_lock, argparse.Namespace(apply=False))
want("lock (a dry-run): exit 0, writes nothing, says how much it saw",
     (code, os.path.exists(LOCK), "3 plugin(s), 3 skill(s), gsd 1.42.3, 4 mcp package(s)" in out, "would write" in out), (0, False, True, True))
code, out = run(lockfile.cmd_lock, argparse.Namespace(apply=True))
written = json.load(open(LOCK)) if os.path.exists(LOCK) else {}
want("lock --apply writes the document, plugins in sorted order on disk", (code, written, list(written.get("plugins", {}))),
     (0, doc, ["alpha@market", "beta@market", "zeta@market"]))
code, out = run(lockfile.cmd_lock, argparse.Namespace(apply=False))
want("lock again: up to date", (code, "up to date" in out), (0, True))
put(os.path.join(home, ".claude", "get-shit-done", "VERSION"), "1.43.0")
code, out = run(lockfile.cmd_lock, argparse.Namespace(apply=False))
want("lock after GSD moved: the dry-run names the change", (code, "gsd: 1.42.3 -> 1.43.0" in out), (0, True))

code, out = run(lockfile.cmd_versions, argparse.Namespace(md=False))
want("versions: tools, pip and the lock together",
     (code, "node 26.12.1" in out, "PyYAML 6.0.3" in out, "alpha@market 1.5.0" in out, "one " in out, "gsd 1.42.3" in out), (0, True, True, True, True, True))
code, out = run(lockfile.cmd_versions, argparse.Namespace(md=True))
want("versions --md: a markdown table", (code, "| node | 26.12.1 |" in out, "| alpha@market | 1.5.0 (bbbbbbb) |" in out), (0, True, True))
if os.path.exists(LOCK):
    os.remove(LOCK)
code, out = run(lockfile.cmd_versions, argparse.Namespace(md=False))
want("versions with no lock file: exit 1 naming forge lock", (code, "forge lock" in out), (1, True))

for msg in failures:
    print("FAIL", msg)
print("%d failure(s)" % len(failures))
sandbox.cleanup(bool(failures))
sys.exit(1 if failures else 0)
