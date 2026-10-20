#!/usr/bin/env python3
"""memory.write_hindsight_config records the rendered ~/.hindsight/coding-agent.json in the ownership record
(step 10, increment I3, task T4; forge/owned.py), so a coming `forge uninstall` can remove it without
reading it: C11, kind `file`, at [], owner "hindsight", the SHA-256 of the document forge rendered (a
`${VAR}` in the canonical config is resolved into it, so it can hold a secret: the registry never keeps the
value), no part (the file is forge's alone). Removable means the file still parses to what forge wrote.

A toy HOME and a toy canonical config whose apiToken is `${FAKE_TOKEN}`, run in-process; lib.may_write()
is stubbed to allow, because this checkout may be a linked worktree, which never writes. The file is
claimed whether forge just wrote it or found it already current (the registry may have been lost); a
dry-run records nothing; a secret that does not resolve writes nothing and claims nothing; a second
apply that changes nothing does not rewrite the record.

Seen failing on the parent commit (write_hindsight_config claims nothing): 7 of 14 checks red, the other 7 are controls
and the cases that must record nothing, which pass there. The first:
  FAIL C11: the rendered config is claimed as a file, owner hindsight -- []
Negative controls on the finished code, each mutation of forge/memory.py put back from a copy, checks red: the
already-current path not recording (1); recording there in a dry-run (1); the loose-mode path not recording (1);
the final write not recording (4); the claim made of the canonical config and not the rendered one (3); owner
core (1); recording before the secret check, so an unresolved secret claims a file never written (1)."""
import contextlib
import io
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

TOY = sandbox.mkdtemp("owned-hindsight-test-")
HOME = os.path.join(TOY, "home")
os.makedirs(HOME)
os.environ["HOME"] = HOME  # before the import: lib.STATE is computed there
for var in ("CLAUDE_PROJECT_DIR", "FORGE_WRITE_LOG", "XDG_CONFIG_HOME"):
    os.environ.pop(var, None)
os.environ.update(sandbox.GIT_ENV)
sys.path.insert(0, sandbox.FORGE)
from forge import lib, memory, owned  # noqa: E402

assert lib.HOME == HOME, "forge/lib.py saw the real HOME"
lib.may_write = lambda: (True, "")

ROOT = os.path.join(TOY, "forge")
os.makedirs(os.path.join(ROOT, "config"))
memory.ROOT = ROOT
CANON = os.path.join(ROOT, "config", "hindsight-coding-agents.json")
TARGET = os.path.join(HOME, ".hindsight", "coding-agent.json")
FAKE_TOKEN = "fake-hindsight-token-52fa-NOT-REAL"
SECRETS = {"FAKE_TOKEN": FAKE_TOKEN}
with open(CANON, "w", encoding="utf-8") as fh:
    json.dump({"_doc": "toy", "apiUrl": "http://127.0.0.1:9", "apiToken": "${FAKE_TOKEN}", "bankId": "toy"}, fh)

APPLY, DRY = lib.Ctx(True, None, False), lib.Ctx(False, None, False)
failures, n_checks = [], [0]


def check(label, ok, detail=""):
    n_checks[0] += 1
    if not ok:
        failures.append(label)
        print("FAIL", label, "--", str(detail)[:500])


def run(ctx, secrets=None):
    errors = []
    with contextlib.redirect_stdout(io.StringIO()):
        line = memory.write_hindsight_config(ctx, SECRETS if secrets is None else secrets, errors)
    return line


def raw():
    return open(owned.path(), encoding="utf-8").read() if os.path.exists(owned.path()) else ""


def mtime():
    return os.stat(owned.path()).st_mtime_ns if os.path.exists(owned.path()) else None


def claims():
    return owned.previous(TARGET)[0]


def drop_registry():
    if os.path.exists(owned.path()):
        os.remove(owned.path())


def doc():
    with open(TARGET, encoding="utf-8") as fh:
        return json.load(fh)


drop_registry()
line = run(APPLY)
check("control: the config was rendered with the token in it", os.path.exists(TARGET) and doc().get("apiToken") == FAKE_TOKEN, line)
got = claims()
check("C11: the rendered config is claimed as a file, owner hindsight",
      [(c["kind"], c["at"], c["owner"], c.get("part")) for c in got] == [("file", [], "hindsight", None)], got)
check("C11: the claim's sum is the hash of the document as written", got and got[0]["sum"] == owned.digest(doc()), got)
check("C11: the file is removable by that claim while it is unedited", got and owned.removable(got[0], doc()), got)
check("C11: the record never holds the token", FAKE_TOKEN not in raw() and "52fa" not in raw(), "token in owned.json")

before, stamp = raw(), mtime()
time.sleep(0.05)  # the file system's clock is coarse: a rewrite within a tick would keep the mtime
line = run(APPLY)
check("control: a second run is already current", "already current" in line, line)
check("C11: a second apply that changes nothing keeps the claim and leaves the record's bytes and mtime",
      raw() != "" and raw() == before and mtime() == stamp, "rewritten")

# the record was lost: the file is current, and the next apply claims it again
drop_registry()
line = run(DRY)
check("C11: a dry-run over a file that is already current records nothing", "already current" in line and not os.path.exists(owned.path()),
      (line, raw()))
line = run(APPLY)
check("C11: an apply over a file that is already current claims it", "already current" in line and len(claims()) == 1, (line, claims()))

# a drifted file is rewritten, and the claim follows
d = doc()
d["bankId"] = "edited"
lib.write_json(TARGET, d)
line = run(APPLY)
check("C11: a rewrite re-claims the new document", "drift" in line and claims() and claims()[0]["sum"] == owned.digest(doc()), (line, claims()))

# a file whose mode is loose is corrected, and still claimed
drop_registry()
os.chmod(TARGET, 0o644)
line = run(APPLY)
check("C11: a content-current file with a loose mode is corrected and claimed",
      "mode corrected" in line and len(claims()) == 1 and (os.stat(TARGET).st_mode & 0o777) == 0o600, (line, claims()))

# a dry-run over a changed file: nothing claimed
drop_registry()
d = doc()
d["bankId"] = "edited-again"
lib.write_json(TARGET, d)
line = run(DRY)
check("C11: a dry-run that would write records nothing", "would write" in line and not os.path.exists(owned.path()), (line, raw()))

# a secret that does not resolve: nothing written, nothing claimed
drop_registry()
os.remove(TARGET)
line = run(APPLY, secrets={})
check("C11: a secret that does not resolve writes no file and claims nothing",
      "NOT written" in line and not os.path.exists(TARGET) and not os.path.exists(owned.path()), (line, raw()))

check("the record never held the token anywhere in this run", FAKE_TOKEN not in raw(), "token in owned.json")
print("%d checks, %d failed" % (n_checks[0], len(failures)))
sandbox.cleanup(bool(failures))
sys.exit(1 if failures else 0)
