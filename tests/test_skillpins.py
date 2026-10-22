#!/usr/bin/env python3
"""Step 3b of docs/toolchain-design.md: online skills are `skills` entries in config/toolchain.json, each naming an
`http:` tool (the archive of a repository at a commit, with a checksum) and a path inside it. `forge skills`
copies that path out of the mise install into skills/<name> and writes NOTICE.md from the entry, so a copy is
byte-identical to the archive plus one generated file, and a newcomer's `forge init` rebuilds it from the manifest.

The world is a toy checkout and a toy mise under /tmp: `mise` on PATH is a script that answers `mise where
<tool>@<version>` with a directory of the test's and fails for any other tool, so nothing of this machine is
read and no archive is fetched. Every expectation is a file the test wrote.

Seen failing on b1097b1, before forge/skillpins.py existed: "ImportError: cannot import name 'skillpins' from
'forge'" (every case). Controls on the finished code, each put back afterwards, are in the commit message: the
byte compare weakened, the extra-file removal removed, the checksum requirement removed, the path-escape check
removed, the NOT RUN line replaced by a pass, the dry-run writing."""
import contextlib
import io
import json
import os
import stat
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
import sandbox  # noqa: E402
from forge import lib, lockfile, skillpins, toolchain  # noqa: E402

failures = []


def want(label, got, expected):
    if got != expected:
        failures.append("%s = %r, want %r" % (label, got, expected))


def put(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb" if isinstance(data, bytes) else "w") as fh:
        fh.write(data)


def get(path):
    with open(path, "rb") as fh:
        return fh.read()


top = sandbox.mkdtemp("skillpins-test-")
root, home, src, bindir = (os.path.join(top, d) for d in ("forge", "home", "archive", "bin"))
lib.ROOT, lib.HOME, toolchain.MANIFEST = root, home, os.path.join(root, "config", "toolchain.json")
lib.may_write = lambda: (True, "")
SHA = "c0ffee" + "0" * 34
TOOL = "http:toy-skills"
# the archive as mise unpacks it: one skill with a binary file in it, a second skill, and the licence
put(os.path.join(src, "skills", "eng", "alpha", "SKILL.md"), "---\nname: alpha\n---\nbody\r\nCRLF kept\n")
put(os.path.join(src, "skills", "eng", "alpha", "ref", "x.bin"), bytes(range(256)))
put(os.path.join(src, "skills", "eng", "beta", "SKILL.md"), "beta\n")
put(os.path.join(src, "LICENSE"), "Toy licence\nline two\n")
# a mise that knows one install; its path is the archive's top
put(os.path.join(bindir, "mise"), "#!/bin/sh\n[ \"$1 $2\" = \"where %s@%s\" ] && echo %s && exit 0\necho \"mise ERROR not installed\" >&2\nexit 1\n" % (TOOL, SHA, src))
os.chmod(os.path.join(bindir, "mise"), os.stat(os.path.join(bindir, "mise")).st_mode | stat.S_IEXEC)
os.environ["PATH"] = bindir + os.pathsep + os.environ["PATH"]

TOOLS = [{"name": TOOL, "version": SHA, "why": "toy skills",
          "options": {"url": "https://example.invalid/{{ version }}.tar.gz", "checksum": "sha256:" + "0" * 64}}]
ALPHA = {"name": "alpha", "source": TOOL, "path": "skills/eng/alpha", "repo": "https://github.com/o/toy-skills",
         "license_file": "LICENSE", "why": "toy"}


def manifest(skills, tools=TOOLS):
    put(toolchain.MANIFEST, json.dumps({"tools": tools, "pip": [], "skills": skills}))


def run(apply=False):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = skillpins.main(["--apply"] if apply else [])
    return code, out.getvalue()


def tree(base):
    return {os.path.relpath(os.path.join(d, f), base): get(os.path.join(d, f)) for d, _, fs in os.walk(base) for f in fs}


DEST = os.path.join(root, "skills", "alpha")

# no manifest at all (a checkout whose user pins nothing) is no skills either, not an error. Red when entries() read
# the file unconditionally: "no manifest file: exit 1 ... ! config/toolchain.json cannot be read".
code, out = run()
want("no config/toolchain.json: exit 0 and NOT RUN, NOT ARMED", (code, "NOT RUN, NOT ARMED" in out), (0, True))

# no skills entry: nothing to do, said so, and not a pass
manifest([])
code, out = run()
want("no skills entry: exit 0 and NOT RUN, NOT ARMED", (code, "NOT RUN, NOT ARMED" in out), (0, True))

# a dry-run names what it would create and writes nothing
manifest([ALPHA])
code, out = run()
want("dry-run, copy absent: exit 0, names the skill, writes nothing", (code, "alpha" in out and "would create" in out, os.path.exists(DEST)), (0, True, False))

# apply: byte-identical copy (a binary file, CRLF) plus a generated NOTICE.md that forge lock reads back
code, out = run(apply=True)
want("apply: exit 0", code, 0)
got, base = tree(DEST), tree(os.path.join(src, "skills", "eng", "alpha"))
notice = got.pop("NOTICE.md", b"").decode()
want("apply: every file of the archive path byte-identical, nothing else but NOTICE.md", got, base)
want("apply: NOTICE.md says repo, commit and path, then the licence",
     (notice.startswith("From https://github.com/o/toy-skills at commit %s, skills/eng/alpha.\n" % SHA), "Toy licence\nline two\n" in notice), (True, True))
want("the NOTICE.md is what forge lock reads: repo and commit", lockfile.notice(notice), {"repo": "https://github.com/o/toy-skills", "commit": SHA})

# in sync: nothing to do, and nothing written
before = os.stat(os.path.join(DEST, "SKILL.md")).st_mtime_ns
code, out = run(apply=True)
want("second apply: in sync, files untouched", (code, "in sync" in out, os.stat(os.path.join(DEST, "SKILL.md")).st_mtime_ns == before), (0, True, True))

# drift: an edited file, a deleted one and an extra one are each named, and apply restores the copy
put(os.path.join(DEST, "SKILL.md"), "edited\n")
os.remove(os.path.join(DEST, "ref", "x.bin"))
put(os.path.join(DEST, "junk.md"), "not upstream\n")
code, out = run()
want("dry-run on a drifted copy: names the changed, the missing and the extra file, writes nothing",
     (code, "SKILL.md" in out, "ref/x.bin" in out, "junk.md" in out, get(os.path.join(DEST, "SKILL.md"))), (0, True, True, True, b"edited\n"))
code, out = run(apply=True)
want("apply restores the copy and removes the extra file", tree(DEST).keys() - {"NOTICE.md"} == base.keys() and get(os.path.join(DEST, "SKILL.md")) == base["SKILL.md"], True)

# a `license` line instead of a `license_file`: the NOTICE says it and does not copy a licence the skill already ships
# (learnharness: AGPL, 661 lines, in the LICENSE beside its SKILL.md). Red before: "needs a name, a source, a repo, a
# license_file and a why" for an entry with a `license` and no `license_file`.
BETA = {"name": "beta", "source": TOOL, "path": "skills/eng/beta", "repo": "https://github.com/o/toy-skills",
        "license": "AGPL-3.0-only. Its full text is the LICENSE file beside this one.", "why": "toy"}
manifest([ALPHA, BETA])
code, out = run(apply=True)
beta = get(os.path.join(root, "skills", "beta", "NOTICE.md")).decode() if os.path.exists(os.path.join(root, "skills", "beta", "NOTICE.md")) else ""
want("a license line: exit 0, the NOTICE ends with it and holds no licence text", (code, beta.endswith("addition.\n\nLicence: AGPL-3.0-only. Its full text is the LICENSE file beside this one.\n"), "Toy licence" in beta), (0, True, False))
manifest([dict(ALPHA, license="x")])
_, why = skillpins.entries()
want("a license and a license_file together are refused", "license" in (why or ""), True)
manifest([{k: v for k, v in ALPHA.items() if k != "license_file"}])
_, why = skillpins.entries()
want("neither a license nor a license_file is refused", "license" in (why or ""), True)
manifest([ALPHA])

# the source is not installed: a failure that names the fix, and nothing is written
import shutil  # noqa: E402
shutil.rmtree(DEST)
manifest([ALPHA], [dict(TOOLS[0], version="deadbeef" + "0" * 32)])
code, out = run(apply=True)
want("source not installed: exit 1, names forge toolchain --fix, writes nothing", (code, "forge toolchain --fix" in out, os.path.exists(DEST)), (1, True, False))

# the manifest refuses what would let a wrong copy pass
manifest([ALPHA], [dict(TOOLS[0], options={"url": TOOLS[0]["options"]["url"]})])
_, why = skillpins.entries()
want("a source with no checksum is refused", "checksum" in (why or ""), True)
manifest([dict(ALPHA, path="../outside")])
_, why = skillpins.entries()
want("a path that leaves the archive is refused", "path" in (why or ""), True)
manifest([dict(ALPHA, source="http:unknown")])
_, why = skillpins.entries()
want("a source that is no tool of the manifest is refused", "http:unknown" in (why or ""), True)
manifest([ALPHA, ALPHA])
_, why = skillpins.entries()
want("a skill listed twice is refused", "twice" in (why or ""), True)
manifest([ALPHA])
want("toolchain.entries still reads a manifest with a skills list", toolchain.entries()[1], None)

for msg in failures:
    print("FAIL", msg)
print("%d failure(s)" % len(failures))
sandbox.cleanup(bool(failures))
sys.exit(1 if failures else 0)
