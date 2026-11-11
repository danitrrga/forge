"""The live test: `fwx linear` and the Linear client against the real Linear, in one project. The only test with a network.

Armed by two variables: LINEAR_API_KEY (forge puts it in the environment of a project with the framework) and
FWX_LINEAR_TEST_PROJECT (the name of the Linear project the test may write in). Without either it prints
`NOT RUN, NOT ARMED: <reason>` as its last line and exits 77, which `forge test` counts as not run (exit 0 would count as a
PASS that never ran). The key is never printed, and no failure message carries it.

The five points, with a fixed `[test]` issue the test makes or finds again by its fixed id (the client derives a create's
id from project, title and body, so a rerun gets the same issue), never with the label `factory` and never deleting:
  1. create the issue from the `general` template, and create it again: the same identifier, "already there";
  2. comment twice with the same body: one comment in Linear, and the mark `<!-- fwx:` still in the body read back (when
     Linear drops it, the FAIL says the mark has to move to a visible line);
  3. `label +mini-plan` on it, and `list --label mini-plan` finds it (the label is taken off again at the end);
  4. `label` on an issue of another project of the same team is refused (exit 2) and that issue's labels are unchanged;
     when the team has no other project with issues the point is NOT RUN and says how many projects it looked at;
  5. `fwx linear` with the key removed from that subprocess's environment exits 2 and says `LINEAR_API_KEY is not set`.
The run exits 0 only when all five ran and passed; a point that could not run makes it exit 77.

The checks of point 2 and the exit code without a key have controls that run with no network, every time, before the live
part. Each control is the same check run against a fake whose bad version it must catch. Seen red (the first FAIL):
  - `comment` that makes a new id on every call (the client without its hashed id), two comments:
      control comment-newid: caught: FAIL: the repeated comment says it was already there: stdout 'commented TOY-1 ...'
        and FAIL: comment twice: comments carrying the body: got 2, want 1
  - `comment` that stores the body without the mark:
      control comment-nomark: caught: FAIL: the mark is still in the body read back: Linear's body does not keep ...
  - without the key, a copy of this file whose exit code is 0 instead of 77 (`NOT_RUN_EXIT = 0`):
      control exit0-no-key: caught: FAIL: no key: exit: got 0, want 77
      control exit0-no-project: caught: FAIL: no project: exit: got 0, want 77
Point 4 can write when the client is wrong (the label `mini-plan` on a real issue of another project); the test says so
in the FAIL and names the issue.
"""
import hashlib
import json
import os
import subprocess
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

sys.path.insert(0, os.path.join(helpers.ROOT, "lib"))
from fwx import config, linear  # noqa: E402

NOT_RUN_EXIT = 77
NOT_RUN = "NOT RUN, NOT ARMED"
KEY, PROJECT = "LINEAR_API_KEY", "FWX_LINEAR_TEST_PROJECT"
NO_CONTROLS = "FWX_LIVE_NO_CONTROLS"  # set in the copies this test runs of itself, so they do not run the controls again
LABEL = "mini-plan"  # a label the client may add and remove, and not `factory`
KIND = "live-test"
TITLE = "[test] fwx live test: a fixed issue, safe to ignore"
BODY = "Written by tests/test_linear_live.py, to check that a repeated comment is made once."
ISSUE = {"title": TITLE,
         "context": "The fixed issue of fwx's live test against Linear (tests/test_linear_live.py). It is found again on "
                    "every run by its id; nothing here needs doing.",
         "expected": "Comments and labels of the test appear once and the test takes its label off again."}


def run_script(script, env, cwd):
    return subprocess.run([sys.executable, script], cwd=cwd, env=env, capture_output=True, text=True, timeout=120)


# --- point 2, written once and run against the real thing and against fakes ------------------------------------------
def check_comment(s, cli, read, ident):
    """`cli(*args, stdin=)` returns (rc, stdout, stderr); `read(ident)` the issue with its comments."""
    last = None
    for n in (1, 2):
        last = cli("comment", ident, "--kind", KIND, stdin=BODY)
        s.eq("comment call %d: exit" % n, last[0], 0)
    s.ok("the repeated comment says it was already there", "already commented" in last[1], "stdout %r" % last[1])
    ours = [c for c in read(ident)["comments"] if BODY in c["body"]]
    s.eq("comment twice: comments carrying the body", len(ours), 1)
    if ours:
        s.ok("the mark is still in the body read back", all(c["own"] for c in ours),
             "Linear's body does not keep `%s`: the mark has to move to a visible line" % linear.MARK)


class FakeComments:
    """`fwx linear comment` over an in-memory issue. mode: good (the id is derived, a repeat is `already commented`),
    newid (a new id on every call: the bad version of the client) or nomark (the stored body has lost the mark)."""

    def __init__(self, mode):
        self.mode, self.ids, self.bodies = mode, set(), []

    def cli(self, *args, stdin=None):
        ident, kind = args[1], args[args.index("--kind") + 1]
        cid = str(uuid.uuid4()) if self.mode == "newid" else linear.comment_id(
            ident, kind, hashlib.sha256(stdin.encode("utf-8")).hexdigest())
        if cid in self.ids:
            return 0, "already commented %s %s\n" % (ident, cid), ""
        self.ids.add(cid)
        self.bodies.append(stdin if self.mode == "nomark" else "%s%s -->\n%s" % (linear.MARK, kind, stdin))
        return 0, "commented %s %s\n" % (ident, cid), ""

    def read(self, ident):
        return {"comments": [{"body": b, "own": b.lstrip().startswith(linear.MARK)} for b in self.bodies]}


def unarmed_failures(script, cwd):
    """What is wrong with `script`'s way of not running: it must exit 77 and say `NOT RUN, NOT ARMED:` last, with no key
    and with no project. [] when it does."""
    base = {k: v for k, v in helpers.clean_env().items() if k not in (KEY, PROJECT)}
    base[NO_CONTROLS] = "1"
    cases = (("no key", dict(base, **{PROJECT: "toy-project"})), ("no project", dict(base, **{KEY: "not-a-real-key"})))
    s = helpers.Suite()
    for label, env in cases:
        r = run_script(script, env, cwd)
        s.eq("%s: exit" % label, r.returncode, NOT_RUN_EXIT)
        lines = [l for l in r.stdout.splitlines() if l.strip()]
        s.ok("%s: the last line is `%s: <reason>`" % (label, NOT_RUN), bool(lines) and lines[-1].startswith(NOT_RUN + ": "),
             "stdout %r" % r.stdout[-200:])
    return s.fails


def run_controls(s):
    sub = helpers.Suite()
    good = FakeComments("good")
    check_comment(sub, good.cli, good.read, "TOY-1")
    s.ok("control comment-good: the check passes on a client that converges", not sub.fails, str(sub.fails))
    for mode, want in (("newid", "FAIL: comment twice: comments carrying the body: got 2, want 1"),
                       ("nomark", "FAIL: the mark is still in the body read back")):
        sub, bad = helpers.Suite(), FakeComments(mode)
        check_comment(sub, bad.cli, bad.read, "TOY-1")
        s.ok("control comment-%s: caught" % mode, any(f.startswith(want) for f in sub.fails), "fails: %s" % sub.fails)
    here = os.path.realpath(__file__)
    s.ok("the unarmed exit of this file is 77 with `NOT RUN, NOT ARMED:` last", not unarmed_failures(here, helpers.ROOT),
         str(unarmed_failures(here, helpers.ROOT)))
    src = open(here, encoding="utf-8").read()
    old = "NOT_RUN_EXIT = 77\n"
    assert old in src, "control: the exit code line moved"
    mutant_dir = helpers.mkdtemp("fwx-live-mutant-")
    os.mkdir(os.path.join(mutant_dir, "tests"))
    os.symlink(os.path.join(os.path.dirname(here), "helpers.py"), os.path.join(mutant_dir, "tests", "helpers.py"))
    mutant = os.path.join(mutant_dir, "tests", "test_linear_live.py")
    with open(mutant, "w", encoding="utf-8") as f:
        f.write(src.replace(old, "NOT_RUN_EXIT = 0\n", 1))
    fails = unarmed_failures(mutant, mutant_dir)
    for label in ("no key", "no project"):
        s.ok("control exit0-%s: caught" % label.replace("no ", "no-"),
             "FAIL: %s: exit: got 0, want 77" % label in fails, "fails: %s" % fails)


# --- the live part ------------------------------------------------------------------------------------------------
def live(s, key, project):
    """Returns the list of points that could not run, as strings."""
    repo = helpers.toy_repo({".claude/fwx.json": json.dumps({"schema": 1, "project": {"linear_project": project}}) + "\n"})
    cfg = config.load(repo)
    client = linear.Client(key, project, cfg)
    not_run = []

    def cli(*args, stdin=None, with_key=True):
        env = {k: v for k, v in helpers.clean_env().items() if k not in (KEY, "FWX_LINEAR_ENDPOINT")}
        if with_key:
            env[KEY] = key
        r = subprocess.run([sys.executable, os.path.join(helpers.ROOT, "bin", "fwx"), "linear"] + list(args), cwd=repo,
                           env=env, input=stdin, capture_output=True, text=True, timeout=120)
        return r.returncode, r.stdout, r.stderr

    # 1. the fixed issue
    ident = None
    rc, out, err = cli("create", "--template", "general", stdin=json.dumps(ISSUE))
    first = out.split()
    if s.ok("1. create: exit", rc == 0, "exit %d: %s" % (rc, err.strip()[:300])) and first:
        ident = first[0]
        s.ok("1. create: an issue identifier", bool(linear.IDENT.match(ident)), "stdout %r" % out)
        print("1. the test issue %s was %s" % (ident, "made now" if "created" in out.split("  ")[-1] else "found by its fixed id"))
        rc2, out2, err2 = cli("create", "--template", "general", stdin=json.dumps(ISSUE))
        s.ok("1. create again: the same issue, already there", rc2 == 0 and out2.split()[:1] == [ident] and "already there" in out2,
             "exit %d, stdout %r, stderr %r" % (rc2, out2, err2.strip()[:200]))
        got = client.issue(ident)
        s.ok("1. the title starts with [test]", got["title"].startswith("[test]"), "title %r" % got["title"])
        s.ok("1. the issue does not carry factory", "factory" not in got["labels"], "labels %s" % got["labels"])
    if ident:
        # 2. a comment repeated is made once
        check_comment(s, cli, client.issue, ident)
        # 3. a label put on the issue is found by `list --label`
        try:
            rc, out, err = cli("label", ident, "+" + LABEL)
            s.ok("3. label +%s: exit" % LABEL, rc == 0, "exit %d: %s" % (rc, err.strip()[:300]))
            rc, out, err = cli("list", "--label", LABEL, "--json")
            try:
                found = [i["identifier"] for i in json.loads(out)]
            except ValueError:
                found = []
            s.ok("3. list --label %s finds the test issue" % LABEL, rc == 0 and ident in found,
                 "exit %d, found %s, stderr %r" % (rc, found, err.strip()[:200]))
        finally:
            rc, out, err = cli("label", ident, "-" + LABEL)
            s.ok("3. label -%s afterwards: exit" % LABEL, rc == 0, "exit %d: %s" % (rc, err.strip()[:300]))
        # 4. another project's issue is not touched
        not_run += point4(s, client, cli, project, key, cfg)
    else:
        s.ok("2-4. the test issue exists to run them on", False, "point 1 gave no issue")
    # 5. no key, no request and exit 2
    rc, out, err = cli("list", "--label", LABEL, with_key=False)
    s.eq("5. no key: exit", rc, 2)
    s.ok("5. no key: says %s is not set" % KEY, "%s is not set" % KEY in err, "stderr %r" % err.strip()[:200])
    return not_run


def point4(s, client, cli, project, key, cfg):
    team = client.project()["team"]["id"]
    projects = client._gql("query { projects(first: 100) { nodes { name teams { nodes { id } } } } }", {})["projects"]["nodes"]
    others = [p["name"] for p in projects if p["name"] != project and team in [t["id"] for t in p["teams"]["nodes"]]]
    target = None
    for name in others:
        nodes = client._gql("query($p: String!) { issues(first: 5, filter: { project: { name: { eq: $p } } }) { nodes { identifier "
                            "labels { nodes { name } } } } }", {"p": name})["issues"]["nodes"]
        usable = [n for n in nodes if LABEL not in [l["name"] for l in n["labels"]["nodes"]]]
        if usable:
            target = (name, usable[0]["identifier"], sorted(l["name"] for l in usable[0]["labels"]["nodes"]))
            break
    if not target:
        msg = "4. NOT RUN: looked at %d other project(s) of the team, none with an issue to try" % len(others)
        print(msg)
        return [msg]
    name, ident, before = target
    rc, out, err = cli("label", ident, "+" + LABEL)
    s.eq("4. label on an issue of another project: exit", rc, 2)
    s.ok("4. label on an issue of another project: says whose it is", "belongs to" in err, "stderr %r" % err.strip()[:200])
    after = sorted(l["name"] for l in client._gql("query($id: String!) { issue(id: $id) { labels { nodes { name } } } }",
                                                  {"id": ident})["issue"]["labels"]["nodes"])
    s.ok("4. that issue's labels are unchanged", after == before,
         "%s of project %s had %s and now has %s: the label %s was written there and is to be taken off by hand"
         % (ident, name, before, after, LABEL))
    print("4. tried an issue of 1 of %d other project(s) of the team" % len(others))
    return []


def main():
    s = helpers.Suite()
    if not os.environ.get(NO_CONTROLS):
        run_controls(s)
        if s.fails:
            s.done()
    key, project = os.environ.get(KEY), os.environ.get(PROJECT)
    if not key or not project:
        helpers.cleanup(False)
        print("%d controls ran, no network" % s.checks if s.checks else "no controls ran here")
        print("%s: %s" % (NOT_RUN, " and ".join(n for n, v in ((KEY, key), (PROJECT, project)) if not v) + " not set: the 5 live points did not run"))
        sys.exit(NOT_RUN_EXIT)
    not_run = live(s, key, project)
    print("live: %d of 5 points ran" % (5 - len(not_run)))
    if s.fails or not not_run:
        s.done()
    helpers.cleanup(False)
    print("%d checks" % s.checks)
    print("%s: %s" % (NOT_RUN, "; ".join(not_run)))
    sys.exit(NOT_RUN_EXIT)


if __name__ == "__main__":
    main()
