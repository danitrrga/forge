#!/usr/bin/env python3
"""`fwx discuss start`: the JSON the discuss opens with, in a toy repo with the Linear client replaced in the module.

The decision checks call `discuss.build(...)` / `discuss.waiting(...)` in this process, with a fake Linear client and a
fixed clock; the wiring checks (exit codes, one line when off, the JSON on stdout, under 1 s with no network) go through
`bin/fwx discuss start`. The fake client builds each issue with the real `linear.Client._shape`, so the `url` check is
against the client's own shape and not against a copy of it.

Seen red before the command existed (lib/fwx/commands/discuss.py absent; the test stops at the import):
  FAIL: cannot import fwx.commands.discuss: cannot import name 'discuss' from 'fwx.commands' (lib/fwx/commands/__init__.py)
Seen red for `url` against the `_shape` of lib/fwx/linear.py before it carried `url` (with the rest of the command in place):
  FAIL: waiting: ok and the whole count: got ('NOT RUN', {'status': 'NOT RUN', 'reason': "Linear answered something this
  command cannot read (KeyError: 'url')"}), want ('ok', 3)    (20 checks, the rest not run)

Controls, each seen red on a copy of the repo with discuss.py changed in one place (first FAIL shown; the count is the
number of checks that failed):
  - framework flag not read:
      FAIL: framework off but exit 0
  - no key answered with an empty list:
      FAIL: waiting reported 0 while Linear was not queried: got {'status': 'ok', 'count': 0, 'groups': []}
  - Linear asked without a cap:
      FAIL: waiting blocked: a client that takes 6 s was still running after 3 s
  - groups by createdAt (the fake carries it, 40 days old or 1 h):
      FAIL: DTC-1 (updated 2 h ago) is in the group today: got 'older', want 'today'
  - other limits (24 h made 1 h):
      FAIL: DTC-1 (updated 2 h ago) is in the group today: got 'week', want 'today'
  - `items` not capped, or `count` taken from the items:
      FAIL: 7 issues older than a week: items capped at 5: got 7, want 5 / count is the whole 7: got 5, want 7
  - a phase with no stage row taken for a re-entry (`last_stage is None` read as `discuss`):
      FAIL: fresh phase reported as reentry
  - a version that gives no `url` (lib/fwx/linear.py `_shape` without it): the FAIL of the red above
  - `factory_ui_bugs` the constant False:
      FAIL: factory_ui_bugs ignored the configuration: got False, want True
"""
import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

sys.path.insert(0, os.path.join(helpers.ROOT, "lib"))
s = helpers.Suite()
try:
    from fwx import config, linear, state  # noqa: E402
    from fwx.commands import discuss  # noqa: E402
except ImportError as e:
    print("FAIL: cannot import fwx.commands.discuss: %s" % e)
    sys.exit(1)

NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
FMT = "%Y-%m-%dT%H:%M:%SZ"


def ago(**kw):
    return (NOW - timedelta(**kw)).strftime(FMT)


def node(ident, updated, label="needs-owner", created=None):
    """A Linear issue node as the client's query returns it, with a createdAt far from updatedAt (grouping by it is wrong)."""
    return {"identifier": ident, "title": "title of " + ident, "description": "d", "updatedAt": updated,
            "createdAt": created or ago(days=40), "state": {"name": "Todo", "type": "unstarted"},
            "labels": {"nodes": [{"name": label}]}, "project": {"name": "toy-project"}, "assignee": None,
            "url": "https://linear.example.test/" + ident}


REAL_CLIENT = linear.Client


class FakeClient:
    """Stands for linear.Client in the module under test: no network. Its issues go through the real `_shape`."""
    nodes, delay, error, made = [], 0, None, []

    def __init__(self, api_key, project, cfg=None, **kw):
        FakeClient.made.append({"project": project, "timeout": kw.get("timeout")})
        self.shaper = REAL_CLIENT(api_key, project, cfg)

    def waiting(self):
        time.sleep(FakeClient.delay)
        if FakeClient.error:
            raise FakeClient.error
        return [dict(self.shaper._shape(n), createdAt=n["createdAt"]) for n in FakeClient.nodes]  # createdAt: a trap for a grouping by it


discuss.linear.Client = FakeClient  # the module under test and linear.py are the same object: only this test process sees it


def toy(cfg=None):
    files = {"README": "toy\n"}
    base = {"schema": 1, "project": {"linear_project": "toy-project"}}
    if cfg is not None:
        base.update(cfg)
    files[".claude/fwx.json"] = json.dumps(base)
    return helpers.toy_repo(files)


def load(repo):
    return config.load(repo)


def with_key(on):
    if on:
        os.environ["LINEAR_API_KEY"] = "key-not-printed"
    else:
        os.environ.pop("LINEAR_API_KEY", None)


def group_of(w, ident):
    return next((g["age"] for g in w.get("groups", []) for i in g["items"] if i["id"] == ident), None)


# ---- the framework flag: exit 1 and one line ----
off = toy({"framework": False})
r = helpers.fwx(off, "discuss", "start", "--json")
s.ok("framework off but exit 0", r.returncode == 1, "exit %d, stdout %r" % (r.returncode, r.stdout))
s.eq("framework off: one line, nothing else", (len(r.stdout.splitlines()), r.stderr), (1, ""))
on = toy()
r = helpers.fwx(on, "discuss", "start", "--json")
s.eq("framework on: exit", r.returncode, 0)
outside = helpers.mkdtemp("fwx-nogit-")
r = helpers.fwx(outside, "discuss", "start", "--json")
s.eq("outside a repository: exit 2", (r.returncode, r.stdout, "git repository" in r.stderr), (2, "", True))
s.eq("an unknown flag: exit 2", helpers.fwx(on, "discuss", "start", "--nope").returncode, 2)
s.eq("no subcommand: exit 2", helpers.fwx(on, "discuss").returncode, 2)

# ---- no Linear is NOT RUN, never 0 ----
with_key(False)
w = discuss.waiting(load(on), NOW)
s.eq("no key: NOT RUN", w.get("status"), "NOT RUN")
s.ok("waiting reported 0 while Linear was not queried", w.get("status") == "NOT RUN" and "count" not in w, "got %r" % w)
s.ok("no key: the reason names the variable", "LINEAR_API_KEY" in w.get("reason", ""), "got %r" % w)
s.eq("no key: the client was never built", FakeClient.made, [])
with_key(True)
w = discuss.waiting(load(helpers.toy_repo({"README": "toy\n", ".claude/fwx.json": '{"schema": 1}'})), NOW)
s.eq("no linear_project: NOT RUN", (w.get("status"), "linear_project" in w.get("reason", "")), ("NOT RUN", True))
FakeClient.nodes, FakeClient.delay, FakeClient.error = [], 6, None
saved = discuss.WAIT_S
s.eq("the cap on Linear is 5 s", saved, 5)
discuss.WAIT_S = 0.4  # the cap is scaled so the check does not take 5 s; the real figure is checked above
box = {}
t = threading.Thread(target=lambda: box.update(w=discuss.waiting(load(on), NOW)), daemon=True)
t0 = time.time()
t.start()
t.join(3)
s.ok("waiting blocked", not t.is_alive(), "a client that takes 6 s was still running after 3 s")
if not t.is_alive():
    s.eq("a client slower than the cap: NOT RUN", box["w"].get("status"), "NOT RUN")
    s.ok("a client slower than the cap: the reason says time", "did not answer" in box["w"].get("reason", ""),
         "got %r" % box["w"])
discuss.WAIT_S = saved
FakeClient.delay = 0
for label, exc in (("a refusal", linear.LinearError("Linear answered 401", "unauthorized")),
                   ("a network error", linear.LinearError("cannot reach Linear after 3 attempts: refused", "network")),
                   ("a crash", RuntimeError("boom"))):
    FakeClient.error = exc
    w = discuss.waiting(load(on), NOW)
    s.eq("%s: NOT RUN with its reason, no count" % label, (w.get("status"), "count" in w, str(exc) in w.get("reason", "")),
         ("NOT RUN", False, True))
FakeClient.error = None
s.ok("the key is not in any answer", "key-not-printed" not in json.dumps(w), "leaked")

# ---- grouping by updatedAt ----
FakeClient.made = []
FakeClient.nodes = [node("DTC-1", ago(hours=2)), node("DTC-2", ago(days=3), "factory-review"),
                    node("DTC-3", ago(days=20), "factory-failed", created=ago(hours=1))]
w = discuss.waiting(load(on), NOW)
s.eq("waiting: ok and the whole count", (w["status"], w.get("count", w)), ("ok", 3))
if w["status"] != "ok":
    s.done()  # nothing below reads a waiting block that was not made; the FAIL above says why
for ident, how, want in (("DTC-1", "2 h", "today"), ("DTC-2", "3 days", "week"), ("DTC-3", "20 days", "older")):
    s.eq("%s (updated %s ago) is in the group %s" % (ident, how, want), group_of(w, ident), want)
s.eq("the groups come in the order today, week, older", [g["age"] for g in w.get("groups", [])], ["today", "week", "older"])
s.eq("the client is fixed to the configured project and capped", FakeClient.made, [{"project": "toy-project", "timeout": 5}])
items = [i for g in w.get("groups", []) for i in g["items"]]
s.eq("waiting: every item carries its url", {i["id"]: i.get("url") for i in items},
     {k: "https://linear.example.test/" + k for k in ("DTC-1", "DTC-2", "DTC-3")})
s.eq("waiting: the label that makes it wait", {i["id"]: i["label"] for i in items},
     {"DTC-1": "needs-owner", "DTC-2": "factory-review", "DTC-3": "factory-failed"})
s.eq("waiting: an item is exactly id, label, title, url", sorted(items[0]) if items else None, ["id", "label", "title", "url"])
FakeClient.nodes = [node("DTC-%d" % n, ago(days=10 + n)) for n in range(7)] + [node("DTC-9", ago(minutes=5))]
w = discuss.waiting(load(on), NOW)
older = next(g for g in w["groups"] if g["age"] == "older")
s.eq("7 issues older than a week: count is the whole 7", older["count"], 7)
s.eq("7 issues older than a week: items capped at 5", len(older["items"]), 5)
s.eq("the cap is per group: today still has its one", [(g["age"], g["count"]) for g in w["groups"]],
     [("today", 1), ("older", 7)])
s.eq("waiting: the total count adds the groups", w["count"], 8)
s.eq("the freshest of a group come first", [i["id"] for i in older["items"]], ["DTC-0", "DTC-1", "DTC-2", "DTC-3", "DTC-4"])

# ---- the phase: new, then back from a later stage ----
repo = toy()
cfg = load(repo)
phase = str(state.new_phase("first", cwd=repo, session="sess-1"))
d = discuss.build(cfg, cwd=repo, session="sess-1", now=NOW)
s.eq("a bound phase: its absolute folder and no stage", (d["bound"]["phase_dir"], d["bound"]["stage"]), (phase, None))
s.ok("fresh phase reported as reentry", d["bound"]["reentry"] is False, "got %r" % d["bound"])
state.append_audit(phase, "stage", "premortem why", cwd=repo)
d = discuss.build(cfg, cwd=repo, session="sess-1", now=NOW)
s.eq("after premortem: stage and no reentry", (d["bound"]["stage"], d["bound"]["reentry"]), ("premortem", False))
state.append_audit(phase, "stage", "discuss premortem: the plan needs the owner", cwd=repo)
d = discuss.build(cfg, cwd=repo, session="sess-1", now=NOW)
s.eq("after premortem then discuss: reentry on the stage discuss", (d["bound"]["stage"], d["bound"]["reentry"]), ("discuss", True))
s.eq("open phases: the folder, no subproject, the stage", d["open_phases"], [{"dir": phase, "subproject": None, "stage": "discuss"}])
d = discuss.build(cfg, cwd=repo, session="other", now=NOW)
s.eq("another session binds nothing and is no reentry", d["bound"], {"subproject": None, "phase_dir": None, "stage": None, "reentry": False})
d = discuss.build(cfg, cwd=repo, session="other", phase=phase, now=NOW)
s.eq("--phase names the phase without a session", (d["bound"]["phase_dir"], d["bound"]["reentry"]), (phase, True))
fresh = str(state.new_phase("second", cwd=repo, session="sess-2", subproject="api"))
d = discuss.build(cfg, cwd=repo, session="sess-2", now=NOW)
s.eq("a phase of a subproject: bound with it", (d["bound"]["subproject"], d["bound"]["phase_dir"]), ("api", fresh))
s.eq("subprojects are listed", d["subprojects"], ["api"])
s.eq("open phases cover the root and every subproject", [(p["subproject"], p["stage"]) for p in d["open_phases"]],
     [(None, "discuss"), ("api", None)])
d2 = discuss.build(cfg, cwd=repo, session="other", phase=fresh, now=NOW)
s.eq("--phase finds its subproject by the path", d2["bound"]["subproject"], "api")
r = helpers.fwx(repo, "discuss", "start", "--json", "--phase", os.path.join(repo, "nowhere"))
s.eq("--phase that is no phase: exit 2", (r.returncode, r.stdout), (2, ""))
state.cancel_phase(fresh)
s.eq("a cancelled phase is not open", [p["dir"] for p in discuss.build(cfg, cwd=repo, session="x", now=NOW)["open_phases"]], [phase])

# ---- the configuration, and nothing by another road ----
for want in (True, False):
    r2 = toy({"factory": {"ui_bugs": want}})
    d = discuss.build(load(r2), cwd=r2, now=NOW)
    s.eq("factory_ui_bugs ignored the configuration (set %s)" % want, d["factory_ui_bugs"], want)
r2 = toy({"models": {"researcher": {"small": "haiku", "normal": "opus"}, "demo": {"normal": "opus"},
                     "decisions": {"small": "fable"}}, "project": {"linear_project": "toy-project", "ui": True,
                                                                    "verdict_command": "make verdict"},
          "paths": {"verdict": "/tool/design.py"}})
d = discuss.build(load(r2), cwd=r2, now=NOW)
s.eq("models: each role's size from config.model", d["models"],
     {"researcher": {"small": "haiku", "normal": "opus"}, "demo": {"normal": "opus"}, "decisions": {"small": "fable"}})
s.eq("ui, verdict_command, verdict_tool follow the configuration", (d["ui"], d["verdict_command"], d["verdict_tool"]),
     (True, "make verdict", "/tool/design.py"))
d = discuss.build(load(on), cwd=on, now=NOW)
s.eq("defaults: no ui, no verdict, the seed's models", (d["ui"], d["verdict_command"], d["verdict_tool"], d["models"]["demo"]),
     (False, None, None, {"normal": "sonnet"}))
s.eq("the keys are those of Appendix C", sorted(d), sorted(["framework", "config", "project", "main_checkout", "ui",
     "verdict_command", "verdict_tool", "factory_ui_bugs", "subprojects", "bound", "open_phases", "models", "waiting"]))
s.eq("config is the file read", d["config"], os.path.join(on, ".claude", "fwx.json"))
s.eq("read-only: no session file, no .fwx/ made", (os.path.exists(os.path.join(on, ".git", "fwx")), os.path.exists(os.path.join(on, ".fwx"))),
     (False, False))

# ---- the command line: the JSON on stdout, in under 1 s, with no network ----
with_key(False)
t0 = time.time()
r = helpers.fwx(on, "discuss", "start", "--json")
took = time.time() - t0
j = json.loads(r.stdout) if r.returncode == 0 else {}
s.eq("--json: exit 0 and the waiting block says NOT RUN", (r.returncode, j.get("waiting", {}).get("status")), (0, "NOT RUN"))
s.ok("--json: under 1 s", took < 1, "took %.2f s" % took)
s.eq("--json: framework true, no phase bound", (j.get("framework"), j.get("bound", {}).get("phase_dir")), (True, None))
r = helpers.fwx(on, "discuss", "start")
s.ok("without --json: lines to read", r.returncode == 0 and r.stdout.startswith("project: ") and "NOT RUN" in r.stdout, r.stdout[:200])
r = helpers.fwx(repo, "discuss", "start", "--json", env={"CLAUDE_CODE_SESSION_ID": "sess-1"})
j = json.loads(r.stdout)
s.eq("the session of the environment is the bound one", (j["bound"]["phase_dir"], j["bound"]["reentry"]), (phase, True))

s.done()
