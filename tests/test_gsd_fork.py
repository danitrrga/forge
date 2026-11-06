#!/usr/bin/env python3
"""Owned files: forge's own copy of an upstream GSD file is written in place of the package's text, and a lock says
which upstream text it was cut from, so a package update that changes the file is reported, not silently ignored.

A patch keeps upstream's whole text and shows the agent what forge wants on top of it. A fork replaces the file:
config/gsd/fork/<tree>/<rel> (tree = agents or gsd-core) is what lands at <dir>/<rel>, and config/gsd/fork/LOCK.json
holds the package version and the sha256 of each upstream file (normalised, so the staging path does not count) the
forge copy was cut from. `--relock` rewrites the lock from the staged package after the owner has reviewed the change.

sync_tree runs against a toy stage, runtime and fork dir, with HOME on a toy dir and apply on by assigning CTX (as in
scripts/sync/test_sync_gsd_runtime.py: lib.may_write() refuses in a linked worktree). Nothing outside the toy root is read
or written.

Seen failing on 972195a, before owned files existed (15 failures), among them:
  "1 owned: sync_tree raised: sync_tree() got an unexpected keyword argument 'tree'"
  "3 drift: no error naming agents/gsd-x.md: []"
  "9 relock: sync_gsd_runtime has no write_lock"
Negative controls, on the finished code, each in a backup copy of sync_gsd_runtime.py and restored from it:
  the lock comparison replaced by `False` makes "3 drift: no error naming agents/gsd-x.md: []" fail (1 failure);
  `rel in patch_map` replaced by `False` in the owned branch makes "5 patch on an owned file: no error: []" and
  "5 patch on an owned file: nothing written" fail (2 failures). Restored from the backup, 0 failures.
"""
import hashlib
import importlib.util
import io
import json
import os
import sys
from contextlib import redirect_stdout

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.realpath(__file__))
FORGE = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import sandbox  # noqa: E402

TOY = sandbox.mkdtemp("gsd-fork-test-")
os.environ["HOME"] = os.path.join(TOY, "home")
os.makedirs(os.environ["HOME"])
for var in ("CLAUDE_PROJECT_DIR", "FORGE_WRITE_LOG"):
    os.environ.pop(var, None)
sys.argv = [sys.argv[0]]
_spec = importlib.util.spec_from_file_location(
    "sync_gsd_runtime", os.path.join(FORGE, "scripts", "sync", "sync_gsd_runtime.py"))
gsd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gsd)

failures = []


def want(label, ok, detail=""):
    if not ok:
        failures.append("%s%s" % (label, (": " + detail) if detail else ""))


def write(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


def read(p):
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return f.read()


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def world(name, upstream, forge, lock_files, locked_text=None):
    """A toy stage with `upstream` ({rel: text}), a fork dir with `forge` ({'agents/rel': text}) and a lock whose entries
    are `lock_files` ({'agents/rel': text it was cut from}, hashed here). Returns (stage, runtime)."""
    d = os.path.join(TOY, name)
    stage, runtime = os.path.join(d, "stage"), os.path.join(d, "runtime")
    for rel, text in upstream.items():
        write(os.path.join(stage, rel), text)
    gsd.FORK = os.path.join(d, "fork")
    for key, text in forge.items():
        write(os.path.join(gsd.FORK, key), text)
    write(os.path.join(gsd.FORK, "LOCK.json"),
          json.dumps({"package": "9.9.9", "files": {k: sha(v) for k, v in lock_files.items()}}))
    return stage, runtime


def run(stage, runtime, patches=None, only=None, apply=True):
    gsd.CTX = gsd.lib.Ctx(apply, None, True)
    errors, buf = [], io.StringIO()
    with redirect_stdout(buf):
        try:
            n = gsd.sync_tree(stage, runtime, patches or {}, "toy", errors, only=only, tree="agents")
        except TypeError as e:
            return None, errors, buf.getvalue(), str(e)
    return n, errors, buf.getvalue(), None


UP = "upstream executor, 6000 words\n"
FORK_X = "forge executor, 900 words\n"

# 1 an owned file is written in place of upstream's text; a file that is not owned still is upstream's
stage, rt = world("c1", {"gsd-x.md": UP, "gsd-y.md": "plain\n"}, {"agents/gsd-x.md": FORK_X}, {"agents/gsd-x.md": UP})
n, errors, out, exc = run(stage, rt)
want("1 owned: sync_tree raised", exc is None, "%s" % exc)
want("1 owned: dst holds forge's text, not upstream's", read(os.path.join(rt, "gsd-x.md")) == FORK_X,
     "got %r" % read(os.path.join(rt, "gsd-x.md")))
want("1 owned: a file with no forge copy still gets upstream's text", read(os.path.join(rt, "gsd-y.md")) == "plain\n")
want("1 owned: no error", errors == [], "%s" % errors)
want("1 owned: both files counted", n == 2, "n=%s: %s" % (n, out))

# 2 a second run changes nothing
n2, errors2, out2, _ = run(stage, rt)
want("2 idempotent: 0 changes", n2 == 0 and errors2 == [], "n=%s errors=%s: %s" % (n2, errors2, out2))

# 3 upstream changed after the lock was cut: an error naming the file and the locked version; forge's copy is still written
stage, rt = world("c3", {"gsd-x.md": UP + "upstream added a section\n"}, {"agents/gsd-x.md": FORK_X}, {"agents/gsd-x.md": UP})
n, errors, out, exc = run(stage, rt)
want("3 drift: no error naming agents/gsd-x.md", any("agents/gsd-x.md" in e and "9.9.9" in e for e in errors), "%s" % errors)
want("3 drift: forge's copy is still written", read(os.path.join(rt, "gsd-x.md")) == FORK_X)

# 4 an owned file with no lock entry cannot be checked for drift: an error that says to relock
stage, rt = world("c4", {"gsd-x.md": UP}, {"agents/gsd-x.md": FORK_X}, {})
n, errors, out, exc = run(stage, rt)
want("4 unlocked: no error naming --relock", any("agents/gsd-x.md" in e and "--relock" in e for e in errors), "%s" % errors)

# 5 a patch and an owned file on the same path is ambiguous: an error, nothing written for it
stage, rt = world("c5", {"gsd-x.md": UP}, {"agents/gsd-x.md": FORK_X}, {"agents/gsd-x.md": UP})
n, errors, out, exc = run(stage, rt, patches={"gsd-x.md": [("p", "replace", "upstream", "forge")]})
want("5 patch on an owned file: no error", any("gsd-x.md" in e and "patch" in e for e in errors), "%s" % errors)
want("5 patch on an owned file: nothing written", read(os.path.join(rt, "gsd-x.md")) is None)

# 6 a forge-only file (no upstream, no lock entry) is written; an owned file the package dropped is an error
stage, rt = world("c6", {"gsd-y.md": "plain\n"},
                  {"agents/gsd-new.md": "forge-only\n", "agents/gsd-gone.md": "was forked\n"},
                  {"agents/gsd-gone.md": "old upstream\n"})
n, errors, out, exc = run(stage, rt)
want("6 forge-only: written", read(os.path.join(rt, "gsd-new.md")) == "forge-only\n")
want("6 dropped upstream: no error naming agents/gsd-gone.md",
     any("agents/gsd-gone.md" in e and "no longer ships" in e for e in errors), "%s" % errors)
want("6 forge-only: no error for it", not any("gsd-new.md" in e for e in errors), "%s" % errors)

# 7 dry-run writes nothing, but still reports the change
stage, rt = world("c7", {"gsd-x.md": UP}, {"agents/gsd-x.md": FORK_X}, {"agents/gsd-x.md": UP})
n, errors, out, exc = run(stage, rt, apply=False)
want("7 dry-run: nothing written", not os.path.exists(os.path.join(rt, "gsd-x.md")))
want("7 dry-run: one change reported", n == 1, "n=%s: %s" % (n, out))

# 8 the `only` filter applies to owned files too
stage, rt = world("c8", {"gsd-x.md": UP, "other.md": "o\n"}, {"agents/gsd-x.md": FORK_X, "agents/other.md": "forged other\n"},
                  {"agents/gsd-x.md": UP, "agents/other.md": "o\n"})
n, errors, out, exc = run(stage, rt, only=lambda rel: rel.startswith("gsd-"))
want("8 only: the filtered-out owned file is not written", read(os.path.join(rt, "other.md")) is None)
want("8 only: the kept one is", read(os.path.join(rt, "gsd-x.md")) == FORK_X)

# 9 relock: the lock is rewritten from the staged package, and the drift of case 3 is gone on the next run
stage, rt = world("c9", {"gsd-x.md": UP + "upstream added a section\n"}, {"agents/gsd-x.md": FORK_X}, {"agents/gsd-x.md": UP})
gsd.RELOCK = True
n, errors, out, exc = run(stage, rt)
want("9 relock: drift is not an error while relocking", errors == [], "%s" % errors)
gsd.CTX = gsd.lib.Ctx(True, None, True)
if hasattr(gsd, "write_lock"):
    with redirect_stdout(io.StringIO()):
        gsd.write_lock("1.2.3")
else:
    failures.append("9 relock: sync_gsd_runtime has no write_lock")
gsd.RELOCK = False
lock = json.loads(read(os.path.join(gsd.FORK, "LOCK.json")))  # still the old lock when write_lock is missing
want("9 relock: lock holds the new version and the staged text's hash",
     lock == {"package": "1.2.3", "files": {"agents/gsd-x.md": sha(UP + "upstream added a section\n")}}, "%s" % lock)
n, errors, out, exc = run(stage, rt)
want("9 relock: no drift on the next run", errors == [], "%s" % errors)

sandbox.cleanup(bool(failures))
for f in failures:
    print("FAIL", f)
print("%d failure(s)" % len(failures))
sys.exit(1 if failures else 0)
