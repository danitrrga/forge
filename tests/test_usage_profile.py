#!/usr/bin/env python3
"""`forge metrics NAME --usage --by-profile` (forge/usage.py by_profile, cli.metrics_usage), over a toy world: a HOME of its
own, one project, the toy transcripts of tests/fixtures/usage/profile/ (p-a, p-b) and their session records
(profile/records/), which the test copies into a toy `lib.STATE/profile-sessions/`.

What a transcript carries: a `cost-state` line (Claude Code's own running total of the session: `totalCostUSD` and, per
model, `inputTokens`, `outputTokens`, `cacheReadInputTokens`, `cacheCreationInputTokens`, `costUSD`; the LAST one of the
main file is the session's total). p-a has two, 0.10 then 0.25, so a version that reads the first or adds them up is wrong.
The shape was read from real transcripts (not guessed like the module's other fields); a session without such a line has no
cost, which is reported as unknown (`cost_usd` null, `with_cost` 0), never as 0.

Seen failing before the change (base 3ecfca4, no `usage.by_profile`, no `--by-profile`): 22 FAIL lines, among them
  "two groups with their tokens and cost = 'profiles: 0, expected 2'" and
  "full_cases raised AttributeError: module 'forge.usage' has no attribute 'by_profile'".
Controls, each a version that leaves out one thing, run through the same check function as the real case:
  by_profile handed a reader that finds no record -> "profiles: 1, expected 2" (two transcripts, records A and B: the plan's
    control), and "profiles: 1, expected 3" on the full world
  a reader that drops `parent`                    -> "profile-b runs: [], expected parent p-a"
The implementation was also run with one thing broken at a time, and the suite went red on the check named for it:
  the first cost-state of a file instead of the last -> "profile-a: cost 0.1, expected 0.25"
  every cost-state added up                          -> "profile-a: cost 0.35, expected 0.25"
  a session with no record dropped, not `default`    -> "profiles: 2, expected 3"
  the tokens left at 0                               -> "profile-a: 1 sessions and 0 tokens, expected 1 and 1350"
  an unknown cost as 0                               -> "no cost-state: cost null, with_cost 0, tokens 0 = (0, 0, 0, 0)"
"""
import argparse
import contextlib
import datetime
import io
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from forge import cli, lib, profiles, usage  # noqa: E402
import sandbox  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.realpath(__file__)), "fixtures", "usage", "profile")
failures = []
DAY0 = datetime.date(2001, 9, 9)  # a fixture file says `{D1}` for the day after it, as tests/fixtures/usage/ does


def want(label, got, expected):
    if got != expected:
        failures.append("%s = %r, want %r" % (label, got, expected))


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def day(n):
    return (DAY0 + datetime.timedelta(days=n)).isoformat()


def read(path):
    """A fixture file's text with its `{Dn}` placeholders turned into dates."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    for n in range(2):
        text = text.replace("{D%d}" % n, day(n))
    return text


def build(tmp, name, sessions, project="toy"):
    """(home, registry, state) of a world with one project and `sessions`: [(session id, fixture transcript or None for an
    empty file, record or None)]. A record is a dict, or a fixture file name under records/ (the record the fixture holds)."""
    root = os.path.join(tmp, name)
    home, registry, state = os.path.join(root, "home"), os.path.join(root, "projects"), os.path.join(root, "state")
    path = os.path.join(root, "work", project)
    os.makedirs(path)
    folder = os.path.join(home, ".claude", "projects", cli.transcript_key(path))
    os.makedirs(folder)
    for sid, transcript, record in sessions:
        write(os.path.join(folder, sid + ".jsonl"), read(os.path.join(FIXTURE, transcript)) if transcript else "")
        if isinstance(record, str):
            write(os.path.join(state, "profile-sessions", sid + ".json"), read(os.path.join(FIXTURE, "records", record)))
        elif record is not None:
            write(os.path.join(state, "profile-sessions", sid + ".json"), json.dumps(record))
    write(os.path.join(registry, project + ".claude.json"), json.dumps({"project": project, "project_path": path}))
    return home, registry, state


def run(home, registry, state, **kw):
    """(exit code, stdout, stderr) of cli.cmd_metrics over the toy world."""
    args = dict(project="toy", session=None, baseline=False, since=None, until=None, events_until=None, json=True,
                usage=True, by_profile=True, init_diff=None, answers=None)
    args.update(kw)
    real = lib.HOME, lib.PROJECTS, lib.STATE
    lib.HOME, lib.PROJECTS, lib.STATE = home, registry, state
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.cmd_metrics(argparse.Namespace(**args))
    except Exception as e:
        code = "raised %s: %s" % (type(e).__name__, e)
    finally:
        lib.HOME, lib.PROJECTS, lib.STATE = real
    return code, out.getvalue(), err.getvalue()


def report_of(*world, **kw):
    code, out, err = run(*world, **kw)
    try:
        return code, json.loads(out), err
    except ValueError:
        return code, {}, out + err


def groups_problem(rep, expected):
    """The check every control is run through: how many groups, which, and the figures of each."""
    got = {g["profile"]: g for g in rep.get("profiles", [])}
    if len(got) != len(expected):
        return "profiles: %d, expected %d" % (len(got), len(expected))
    for name, (sessions, tokens, cost) in expected.items():
        g = got.get(name)
        if g is None:
            return "no group %s (have %s)" % (name, sorted(got))
        if (g["sessions"], g["tokens"]["total"]) != (sessions, tokens):
            return "%s: %d sessions and %d tokens, expected %d and %d" % (name, g["sessions"], g["tokens"]["total"], sessions, tokens)
        if g["cost_usd"] != cost:
            return "%s: cost %r, expected %r" % (name, g["cost_usd"], cost)
    return None


def runs_problem(rep):
    """The session of `forge run` (p-d) is listed under its profile with its parent."""
    runs = next((g["runs"] for g in rep.get("profiles", []) if g["profile"] == "profile-b"), None)
    if runs == [{"session": "p-d", "parent": "p-a"}]:
        return None
    return "profile-b runs: %r, expected parent p-a" % (runs,)


# p-a: 100 + 50 + 1000 + 200 tokens, cost 0.25 (its last cost-state); p-b: 7 + 3 + 70 + 9, cost 1.5
A, B = (1, 1350, 0.25), (1, 89, 1.5)


def plan_cases(tmp):
    world = build(tmp, "plan", [("p-a", "p-a.jsonl", "p-a.json"), ("p-b", "p-b.jsonl", "p-b.json")])
    code, rep, err = report_of(*world)
    want("two transcripts, two records: rc and the few-sessions line", (code, err), (0, "few sessions (2)\n"))
    want("two groups with their tokens and cost", groups_problem(rep, {"profile-a": A, "profile-b": B}), None)
    want("looked at: two sessions, both with a record", (rep.get("looked_at", {}).get("sessions"), rep.get("looked_at", {}).get("with_record"),
                                                          rep.get("looked_at", {}).get("without_record")), (2, 2, 0))
    want("the tokens by kind", [g["tokens"] for g in rep.get("profiles", []) if g["profile"] == "profile-a"],
         [{"input": 100, "output": 50, "cache_read": 1000, "cache_creation": 200, "total": 1350}])
    by = {g["profile"]: g for g in rep.get("profiles", [])}
    want("profile-a: its skill and its server, counted from its own session", (by["profile-a"]["skills"], by["profile-a"]["servers"]),
         ([{"kind": "skill", "name": "alpha", "calls": 1}], [{"kind": "mcp", "name": "toy-db", "calls": 2}]))
    want("profile-b: its own", (by["profile-b"]["skills"], by["profile-b"]["servers"]),
         ([{"kind": "plugin-skill", "name": "toy-plugin:beta", "calls": 1}], [{"kind": "mcp", "name": "other-srv", "calls": 1}]))
    # control: the version that ignores the records puts both in one group
    sessions, counts = usage.collect(os.path.join(world[0], ".claude", "projects"), os.listdir(os.path.join(world[0], ".claude", "projects")))
    blind = usage.by_profile("toy", sessions, counts, [], [], lambda sid: None)
    want("control: a version that ignores the records is flagged", groups_problem(blind, {"profile-a": A, "profile-b": B}),
         "profiles: 1, expected 2")


def full_cases(tmp):
    run_record = {"profile": "profile-b", "project": "toy", "launcher_pid": 4244, "at": 1000100000.0, "parent": "p-a", "print": True}
    world = build(tmp, "full", [("p-a", "p-a.jsonl", "p-a.json"), ("p-b", "p-b.jsonl", "p-b.json"),
                                ("p-c", "p-a.jsonl", None), ("p-d", "p-b.jsonl", run_record)])
    code, rep, err = report_of(*world)
    want("full world: rc and the few-sessions line", (code, err), (0, "few sessions (4)\n"))
    B2 = (2, 178, 3.0)
    want("a session with no record is default; a forge run session is under its profile", groups_problem(
        rep, {"profile-a": A, "profile-b": B2, "default": A}), None)
    by = {g["profile"]: g for g in rep.get("profiles", [])}
    want("the run session carries its parent, the other does not", by.get("profile-b", {}).get("runs"),
         [{"session": "p-d", "parent": "p-a"}])
    want("a profile with no run session has an empty runs", (by.get("profile-a", {}).get("runs"), by.get("default", {}).get("runs")), ([], []))
    look = rep.get("looked_at", {})
    want("looked at: four sessions, three with a record", (look.get("sessions"), look.get("with_record"), look.get("without_record")), (4, 3, 1))
    want("the groups are listed by sessions, then name", [g["profile"] for g in rep.get("profiles", [])], ["profile-b", "default", "profile-a"])
    # control: records ignored
    sessions, counts = usage.collect(os.path.join(world[0], ".claude", "projects"), os.listdir(os.path.join(world[0], ".claude", "projects")))
    blind = usage.by_profile("toy", sessions, counts, [], [], lambda sid: None)
    want("control: a version that ignores the records is flagged on the full world",
         groups_problem(blind, {"profile-a": A, "profile-b": B2, "default": A}), "profiles: 1, expected 3")
    # control: a reader that drops `parent`, through the same check
    want("the parents of the real record are found", runs_problem(rep), None)
    lost = usage.by_profile("toy", sessions, counts, [], [], lambda sid: ({k: v for k, v in profiles_read(world, sid).items() if k != "parent"}
                                                                           if profiles_read(world, sid) else None))
    want("control: a version that forgets the parent is flagged", runs_problem(lost), "profile-b runs: [], expected parent p-a")
    # --json and the text carry the same groups
    code, out, err = run(*world, json=False)
    want("text mode: rc", code, 0)
    for g in rep.get("profiles", []):
        line = next((l for l in out.splitlines() if l.startswith("profile %s: " % g["profile"])), "")
        want("text line of %s names its sessions, tokens and cost" % g["profile"], (" %d sessions" % g["sessions"] in line,
                                                                                    " %d tokens" % g["tokens"]["total"] in line,
                                                                                    "%.2f USD" % g["cost_usd"] in line), (True, True, True))
    want("text mode says how many sessions it looked at", "looked at 4 sessions" in out, True)
    want("text mode says the session with a parent", "p-d (parent p-a)" in out, True)


def profiles_read(world, sid):
    """The record of `sid` in the toy world's state (profiles.read_session over a toy lib.STATE)."""
    real = lib.STATE
    lib.STATE = world[2]
    try:
        return profiles.read_session(sid)
    finally:
        lib.STATE = real


def edge_cases(tmp):
    # a project with no record at all: one group, default, and how many sessions it looked at
    world = build(tmp, "norec", [("p-a", "p-a.jsonl", None), ("p-b", "p-b.jsonl", None)])
    code, rep, err = report_of(*world)
    want("no record at all: one group, default, with every session", (code, groups_problem(rep, {"default": (2, 1439, 1.75)})), (0, None))
    want("no record at all: says how many it looked at", (rep.get("looked_at", {}).get("sessions"), rep.get("looked_at", {}).get("with_record"),
                                                           rep.get("looked_at", {}).get("without_record")), (2, 0, 2))
    code, out, err = run(*world, json=False)
    want("no record at all, text: says how many it looked at and that none had a record", (code, "0 with a record, 2 without" in out,
                                                                                         "profile default: " in out), (0, True, True))
    # zero sessions is the existing exit, unchanged
    world = build(tmp, "none", [])
    code, out, err = run(*world)
    want("zero sessions: rc 1 and 'usage unknown', as without the flag", (code, "toy: 0 sessions in" in out, "usage unknown" in out), (1, True, True))
    want("zero sessions without the flag: the same text", run(*world, by_profile=False)[1], out)
    # a record whose profile is not a name: default, and said
    world = build(tmp, "badrec", [("p-a", "p-a.jsonl", {"profile": 7, "project": "toy"}), ("p-b", "p-b.jsonl", {"profile": "", "project": "toy"}),
                                  ("p-c", "p-a.jsonl", "p-a.json")])
    code, rep, err = report_of(*world)
    want("a record with no usable profile is counted as default and said", (code, [g["profile"] for g in rep.get("profiles", [])],
                                                                             rep.get("looked_at", {}).get("unusable_records")),
         (0, ["default", "profile-a"], 2))
    # a session with no cost-state line: cost unknown, never 0
    world = build(tmp, "nocost", [("p-a", None, "p-a.json")])
    code, rep, err = report_of(*world)
    g = (rep.get("profiles") or [{}])[0]
    want("no cost-state: cost null, with_cost 0, tokens 0", (code, g.get("cost_usd"), g.get("with_cost"), g.get("tokens", {}).get("total")),
         (0, None, 0, 0))
    code, out, err = run(*world, json=False)
    want("no cost-state, text: cost says unknown", (code, "cost unknown" in out), (0, True))
    # one session with a cost and one without: the sum is of the one, and with_cost says so
    world = build(tmp, "halfcost", [("p-a", "p-a.jsonl", "p-a.json"), ("p-c", None, "p-a.json")])
    code, rep, err = report_of(*world)
    g = (rep.get("profiles") or [{}])[0]
    want("half the sessions with a cost: the sum of those, and the count", (g.get("sessions"), g.get("with_cost"), g.get("cost_usd")), (2, 1, 0.25))
    # --since keeps the session whole
    world = build(tmp, "since", [("p-a", "p-a.jsonl", "p-a.json"), ("p-b", "p-b.jsonl", "p-b.json")])
    code, rep, err = report_of(*world, since=day(1))
    want("--since: only the session from that day on, whole", (code, groups_problem(rep, {"profile-b": B})), (0, None))
    # the flag needs --usage; the plain --usage output has no groups
    code, out, err = run(*world, usage=False)
    want("--by-profile without --usage: rc 1 and says so", (code, "--by-profile needs --usage" in out), (1, True))
    code, out, err = run(*world, init_diff=["x", "y"], answers="z")
    want("--by-profile with --init-diff: rc 1", (code, "--by-profile" in out), (1, True))
    code, rep, err = report_of(*world, by_profile=False)
    want("without --by-profile: the report of schema 1, no groups", (code, "profiles" in rep, "items" in rep), (0, False, True))


def main():
    tmp = sandbox.mkdtemp("usage-profile-test-")
    for cases in (plan_cases, full_cases, edge_cases):
        try:
            cases(tmp)
        except Exception as e:  # a case that cannot finish is a red line, not a traceback
            failures.append("%s raised %s: %s" % (cases.__name__, type(e).__name__, e))
    for msg in failures:
        print("FAIL", msg)
    sandbox.cleanup()
    print("test_usage_profile: %s" % ("%d failures" % len(failures) if failures else "all passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
