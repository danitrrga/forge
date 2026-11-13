#!/usr/bin/env python3
"""`forge metrics NAME --usage` and `--init-diff` (forge/usage.py, cli.cmd_metrics), over a toy world: a HOME of its
own, a toy repository with a linked worktree, and the transcripts of tests/fixtures/usage/ (its `expected.tsv`
holds the counts; the folder names depend on where the toy lives, so the fixture's folders are copied to the keys
cli.transcript_key gives).

The world has five sessions in four folders and one folder of another project that shares the project's key as a
prefix (`decoy`, never read):
  main        s-a (a Skill call, a /command, a /clear, an MCP call written on two lines, an Agent call; its subagent
              file holds one more MCP call, one plugin-MCP call and a listing that must be ignored), s-b (two Skill
              calls, an Agent call, a line that is not JSON, a later non-initial skill_listing)
  worktree    <project>/.claude/worktrees/wt1, a session with an MCP call and a Skill call
  external    a folder the profile only declares in worktree_guard.worktree_dirs, one MCP call
  registered  a worktree `git worktree list` names and nothing else does, one MCP call
  ~/.claude.json holds a skillUsage entry whose name must never come out.

Seen failing before the change (base b4c52fc, no forge/usage.py, `forge metrics` without --usage):
  python3 tests/test_usage.py -> ImportError: cannot import name 'usage' from 'forge'
  forge metrics toy --usage -> rc 2, "forge: error: unrecognized arguments: --usage" (argparse's red: it proves no
  behaviour, so the controls below, one per source, are what count).
Controls, each a world with one source left out that the same check must flag (the message is the check's):
  without .claude/worktrees  -> "mcp toy-db: expected 5 calls, got 4"
  without the external dir   -> the same; without the registered worktree -> the same; without subagents -> the same
  a dump of ~/.claude.json appended to the output -> the decoy name is found in it
  init diff: a check that only asks "every keep appears" lets the still-listed drop through: "expected exit 1, got 0"
The implementation itself was also run with one source disabled each (folder prefix for .claude/worktrees, the
worktree_dirs specs, the git worktree list, the subagent glob, the tool_use id dedupe, the initial-listing test,
`--since`, the plugin attribution of hook output): each went red on the check named for it.
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
from forge import cli, lib, usage  # noqa: E402
import sandbox  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.realpath(__file__)), "fixtures", "usage")
failures = []
DECOY = "decoy-skill-from-the-global-file"


DAY0 = datetime.date(2001, 9, 9)  # the toy sessions' first day; a fixture file says `{D3}` for the third day after it


def day(n):
    return (DAY0 + datetime.timedelta(days=n)).isoformat()


def dated(text):
    for n in range(16):
        text = text.replace("{D%d}" % n, day(n))
    return text


def copy_dated(src, dst, skip_subagents=False):
    """shutil.copytree of a fixture folder with its `{Dn}` placeholders turned into dates."""
    for here, dirs, names in os.walk(src):
        if skip_subagents:
            dirs[:] = [x for x in dirs if x != "subagents"]
        for n in names:
            with open(os.path.join(here, n), encoding="utf-8") as fh:
                text = dated(fh.read())
            write(os.path.join(dst, os.path.relpath(os.path.join(here, n), src)), text)


def want(label, got, expected):
    if got != expected:
        failures.append("%s = %r, want %r" % (label, got, expected))


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def build(tmp, name, skip=()):
    """(home, profiles dir, folder names, project path) of a toy world; `skip` leaves out one source of usage
    ('worktree', 'external', 'registered', 'subagents') for the controls."""
    root = os.path.join(tmp, name)
    home, projects = os.path.join(root, "home"), os.path.join(root, "home", ".claude", "projects")
    project, ext = os.path.join(root, "work", "toy"), os.path.join(root, "ext")
    wt3 = os.path.join(root, "other", "wt3")
    os.makedirs(project)
    sandbox.git(project, "init", "-q")
    sandbox.git(project, "commit", "-q", "--allow-empty", "-m", "one")
    write(os.path.join(project, ".claude", "skills", "proj-skill", "SKILL.md"), "---\nname: proj-skill\n---\n")
    sandbox.git(project, "worktree", "add", "-q", "-b", "wt3", wt3)
    key = cli.transcript_key
    folders = {"main": key(project), "worktree": key(project) + "--claude-worktrees-wt1", "external": key(ext) + "-wt2",
               "registered": key(wt3), "decoy": key(project) + "-other"}
    for role, folder in folders.items():
        if role in skip:
            continue
        copy_dated(os.path.join(FIXTURE, role), os.path.join(projects, folder), "subagents" in skip)
    shutil.copy(os.path.join(FIXTURE, "claude.json"), os.path.join(home, ".claude.json"))
    profiles = os.path.join(root, "profiles")
    guard = {"worktree_dirs": [{"path": ext, "why": "toy"}]}
    lone, empty = os.path.join(root, "work", "lone"), os.path.join(root, "work", "empty")
    copy_dated(os.path.join(FIXTURE, "external"), os.path.join(projects, key(lone)))
    os.makedirs(os.path.join(projects, key(empty)))
    for pname, prof in {"toy": {"project_path": project, "worktree_guard": guard}, "lone": {"project_path": lone},
                        "empty": {"project_path": empty}, "nopath": {},
                        "badguard": {"project_path": project, "worktree_guard": {"worktree_dirs": [{"nope": 1}]}}}.items():
        write(os.path.join(profiles, pname + ".claude.json"), json.dumps(dict(prof, project=pname)))
    return home, profiles, [folders[r] for r in ("main", "worktree", "external", "registered") if r not in skip], project


def run(home, profiles, **kw):
    """(exit code, stdout, stderr) of cli.cmd_metrics over the toy world."""
    args = dict(project="toy", session=None, baseline=False, since=None, until=None, events_until=None, json=True,
                usage=True, init_diff=None, answers=None)
    args.update(kw)
    real = lib.HOME, lib.PROFILES
    lib.HOME, lib.PROFILES = home, profiles
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.cmd_metrics(argparse.Namespace(**args))
    except Exception as e:
        code = "raised %s: %s" % (type(e).__name__, e)
    finally:
        lib.HOME, lib.PROFILES = real
    return code, out.getvalue(), err.getvalue()


def tsv(rep):
    """The reader of expected.tsv's format: what 6.1 builds its usage.tsv from."""
    rows = ["kind\tid\tproject\tcount\tsessions\tlast_seen"]
    rows += ["\t".join([i["kind"], i["name"], rep["project"], str(i["calls"]), str(i["sessions"]), i["last_seen"] or ""])
             for i in rep["items"]]
    return "\n".join(rows) + "\n"


def toy_db_problem(rep):
    """The check every source control is run through: toy-db is called five times, once per source."""
    it = next((i for i in rep["items"] if i["name"] == "toy-db"), None)
    got = it["calls"] if it else 0
    return None if got == 5 else "mcp toy-db: expected 5 calls, got %d" % got


def report_of(home, profiles, **kw):
    code, out, err = run(home, profiles, **kw)
    try:
        return code, json.loads(out), err
    except ValueError:
        return code, {}, out + err


def usage_cases(tmp):
    home, profiles, folders, project = build(tmp, "main")
    code, rep, err = report_of(home, profiles)
    want("--usage --json over the toy world exits 0", (code, err), (0, ""))
    if not rep:
        failures.append("no JSON report: %s" % err[:200])
        return
    with open(os.path.join(FIXTURE, "expected.tsv"), encoding="utf-8") as fh:
        want("expected.tsv, read back from the report", tsv(rep), dated(fh.read()))
    want("schema and project", (rep["schema"], rep["project"]), (1, "toy"))
    want("looked_at", {k: v for k, v in rep["looked_at"].items() if k != "folders"},
         {"sessions": 5, "subagent_files": 1, "unreadable_lines": 1, "first": day(0), "last": day(4)})
    want("the folders read: the four of this project and not the decoy that shares its key as a prefix",
         sorted(rep["looked_at"]["folders"]), sorted(folders))
    want("the six kinds", {i["kind"] for i in rep["items"]}, set(usage.KINDS))
    by = {i["name"]: i for i in rep["items"]}
    want("alpha: three Skill calls, none by command, listed in the last initial listing", (by["alpha"]["via"], by["alpha"]["listed_bytes"], by["alpha"]["plugin"]),
         ({"tool": 3, "command": 0}, 14, None))
    want("proj-skill: one call, by its /command; listed and a project skill", (by["proj-skill"]["via"], by["proj-skill"]["listed_bytes"]),
         ({"tool": 0, "command": 1}, 27))
    want("the plugin skill and the one nobody calls", (by["toy-plugin:beta"]["plugin"], by["toy-plugin:beta"]["listed_bytes"],
                                                       by["unused-skill"]["calls"], by["unused-skill"]["listed_bytes"]), ("toy-plugin", 31, 0, 22))
    want("toy-db: two tools of 18 and 19 bytes (the one the delta removed is gone)", (by["toy-db"]["tools"], by["toy-db"]["listed_bytes"]), (2, 37))
    want("the plugin's MCP server", (by["plugin_toyplug_srv"]["plugin"], by["plugin_toyplug_srv"]["tools"], by["plugin_toyplug_srv"]["listed_bytes"]),
         ("toyplug", 1, 29))
    want("the agent", (by["toy-agent"]["calls"], by["toy-agent"]["sessions"]), (2, 2))
    want("/clear is not a skill, the subagent's own listing is not read, the decoy folder is not read",
         [n for n in ("clear", "only-in-subagent", "decoy-skill") if n in by], [])
    want("listing: the two sessions that carry one, newest first, from their initial listing only",
         rep["listing"], [{"session": "s-b", "skills": 4, "skills_bytes": 97, "mcp_names_bytes": 66},
                          {"session": "s-a", "skills": 4, "skills_bytes": 164, "mcp_names_bytes": 47}])
    want("plugins: the SessionStart stdout of the plugin's hook in the newest session that has one, not the user's hook",
         rep["plugins"], [{"plugin": "toyplug", "startup_bytes": 5}])
    want("five sessions is not few", rep["few_sessions"], False)
    want("the one hook outside a plugin directory is counted apart; /clear, not a skill, is listed apart",
         (rep["startup_unattributed"], rep["unlisted_commands"]), ({"hooks": 1, "bytes": 21}, {"clear": 1}))
    # ~/.claude.json: its skillUsage is global; nothing of it comes out
    raw = run(home, profiles)[1]
    want("the decoy of ~/.claude.json is absent", DECOY in raw, False)
    with open(os.path.join(home, ".claude.json"), encoding="utf-8") as fh:
        want("control: a version that dumps ~/.claude.json prints the decoy", DECOY in raw + fh.read(), True)
    # one control per source: the world without it, the same check
    for source, why in (("worktree", ".claude/worktrees"), ("external", "worktree_dirs"), ("registered", "git worktree list"),
                        ("subagents", "subagent files")):
        h, p, _, _ = build(tmp, "without-" + source, skip=(source,))
        want("control: toy-db without the %s source is flagged" % why, toy_db_problem(report_of(h, p)[1]),
             "mcp toy-db: expected 5 calls, got 4")
    want("toy-db with every source is not flagged", toy_db_problem(rep), None)
    # --since and the minimum of sessions
    code, rep2, err = report_of(home, profiles, since=day(3))
    want("--since the fourth day reads the two sessions from that day on and says so on stderr",
         (code, rep2.get("looked_at", {}).get("sessions"), rep2.get("few_sessions"), "few sessions (2)" in err), (0, 2, True, True))
    want("--since: toy-db calls", next((i["calls"] for i in rep2.get("items", []) if i["name"] == "toy-db"), None), 2)
    want("--since drops the line of a kept session that is older than the day (an agent called the day before)",
         [i["name"] for i in rep2.get("items", []) if i["name"] == "early-agent"], [])
    code, out, err = run(home, profiles, since=day(20))
    want("--since after every session is zero sessions: FAIL, rc 1", (code, "toy: 0 sessions in" in out, "usage unknown" in out), (1, True, True))
    want("--since that is not a date", run(home, profiles, since="yesterday")[0], 1)
    code, out, err = run(home, profiles, project="lone")
    want("one session: rc 0 and 'few sessions (1)'", (code, "few sessions (1)" in err, json.loads(out)["few_sessions"]), (0, True, True))
    code, out, err = run(home, profiles, project="lone", json=False)
    want("text mode says it on stdout", (code, "few sessions (1)" in out), (0, True))
    code, out, err = run(home, profiles, project="empty")
    want("a transcript folder with no session: rc 1, 'usage unknown'", (code, "empty: 0 sessions in" in out, "usage unknown" in out), (1, True, True))
    code, out, err = run(home, profiles, json=False)
    want("text mode lists the items", (code, "toy-db" in out, "mcp" in out), (0, True, True))
    want("a profile with no project_path", (run(home, profiles, project="nopath")[0], "nopath: the profile has no project_path" in run(home, profiles, project="nopath")[1]), (1, True))
    code, out, err = run(home, profiles, project="badguard")
    want("a worktree_dirs entry with neither path nor prefix is a FAIL", (code, "worktree_dirs[0]" in out), (1, True))
    want("--usage with --baseline", run(home, profiles, baseline=True)[0], 1)
    want("--usage with a session id", run(home, profiles, session="s-a")[0], 1)
    want("--usage with --until", run(home, profiles, until=day(3))[0], 1)
    want("a decoy-only project does not exist: unknown project", run(home, profiles, project="nosuch")[0], 1)


def mini(tmp, name, lines):
    """(home, profiles) of a world with one project `p` and one session whose transcript is `lines`: the shapes of
    real transcript objects (an attachment with `type`, `names`, `content`, `isInitial`; a user message whose
    `message.content` is a string), built only from toy names."""
    root = os.path.join(tmp, name)
    project = os.path.join(root, "work", "p")
    os.makedirs(project)
    write(os.path.join(root, "home", ".claude", "projects", cli.transcript_key(project), "s1.jsonl"),
          "".join(json.dumps(l) + "\n" for l in lines))
    write(os.path.join(root, "profiles", "p.claude.json"), json.dumps({"project": "p", "project_path": project}))
    return os.path.join(root, "home"), os.path.join(root, "profiles")


def at(n, sec=0):
    return day(n) + "T10:00:%02d.000Z" % sec


def listing(n, content, names, initial=True):
    return {"type": "attachment", "timestamp": at(n), "attachment": {"type": "skill_listing", "content": content,
                                                                      "names": names, "isInitial": initial}}


def typed(n, command, sec=1):
    return {"type": "user", "timestamp": at(n, sec), "message": {"role": "user", "content":
            "<command-message>%s</command-message>\n<command-name>/%s</command-name>" % (command, command)}}


def review_cases(tmp):
    """The five defects of the review of PR 135, each in a world of its own. Red before the fixes:
    D1 name-only skills: "nameonly: no row" ; D2 an unlisted command: "unlisted_commands = None, want {'custom-cmd': 2, 'clear': 1}";
    D3 --since: "listed-one: no row"; D4 plugins [] with an unexpanded plugin root: "plugins = [], want None";
    D5 a drop or add that is in no capture: rc 0, want 1."""
    body = "- nameonly\n- plug:nameonly\n- listed-one: described at length"
    names = ["nameonly", "plug:nameonly", "listed-one"]
    # D1: a listing line without a description is a skill too (real listings hold them when the budget is short)
    h, p = mini(tmp, "d1", [listing(0, body, names), typed(1, "nameonly"), typed(1, "plug:nameonly", 2), typed(1, "listed-one", 3)])
    by = {i["name"]: i for i in report_of(h, p, project="p")[1].get("items", [])}
    for n, kind, size in (("nameonly", "skill", len("- nameonly")), ("plug:nameonly", "plugin-skill", len("- plug:nameonly")),
                          ("listed-one", "skill", len("- listed-one: described at length"))):
        want("%s: counted once by its /command, listed" % n, (by.get(n) or {}).get("calls") and
             (by[n]["kind"], by[n]["calls"], by[n]["listed_bytes"]), (kind, 1, size))
    # D2: a command that is no listed skill is counted in a list of its own, nothing is dropped without a trace
    h, p = mini(tmp, "d2", [listing(0, body, names), typed(1, "custom-cmd"), typed(1, "custom-cmd", 2), typed(1, "clear", 3)])
    rep = report_of(h, p, project="p")[1]
    want("unlisted commands, counted", rep.get("unlisted_commands"), {"custom-cmd": 2, "clear": 1})
    want("an unlisted command is not an item", [i["name"] for i in rep.get("items", []) if i["name"] in ("custom-cmd", "clear")], [])
    code, out, err = run(h, p, project="p", json=False)
    want("text mode names them", (code, "custom-cmd x2" in out), (0, True))
    # D3: with --since the session's initial listing is still read (only the uses are dated)
    h, p = mini(tmp, "d3", [listing(0, body, names), typed(4, "listed-one")])
    rep = report_of(h, p, project="p", since=day(2))[1]
    it = next((i for i in rep.get("items", []) if i["name"] == "listed-one"), None)
    want("--since: the command after the day still counts, with its listed bytes",
         it and (it["calls"], it["listed_bytes"]), (1, len("- listed-one: described at length")))
    # D4: a SessionStart hook whose command carries an unexpanded plugin root names no plugin: not measured, not zero
    hook = {"type": "attachment", "timestamp": at(0, 2), "attachment": {
        "type": "hook_success", "hookEvent": "SessionStart", "hookName": "SessionStart:startup", "exitCode": 0,
        "command": "bash ${CLAUDE_PLUGIN_ROOT}/hooks/start.sh", "stdout": "hello", "stderr": ""}}
    h, p = mini(tmp, "d4", [listing(0, body, names), hook])
    code, rep, err = report_of(h, p, project="p")
    want("unattributed SessionStart output: plugins is null, the bytes are counted apart, and it says NOT RUN",
         (code, rep.get("plugins"), rep.get("startup_unattributed"), "NOT RUN, NOT ARMED: plugin startup_bytes" in err),
         (0, None, {"hooks": 1, "bytes": 5}, True))
    h, p = mini(tmp, "d4b", [listing(0, body, names)])
    want("no SessionStart hook at all is a true zero: plugins is []", report_of(h, p, project="p")[1].get("plugins"), [])


def init_event(skills, plugins, servers):
    return {"type": "system", "subtype": "init", "skills": skills, "plugins": [{"name": n, "path": "/srv/" + n} for n in plugins],
            "mcp_servers": [{"name": n, "status": "connected"} for n in servers], "tools": ["Bash"]}


def weak_diff(before, after, marks):
    """The check the plan rejects: every keep appears. It cannot see a drop that is still listed."""
    names = after["skills"] | after["plugins"] | after["mcp"]
    return 1 if any(m == "keep" and n not in names for n, m in marks.items()) else 0


def init_cases(tmp):
    home, profiles, _, _ = build(tmp, "init")
    d = os.path.join(tmp, "init-files")
    before = init_event(["alpha", "gamma", "base-one"], ["p1", "p2"], ["toy-db", "plugin_p1_x"])
    marks = {"gamma": "drop", "plugin_p1_x": "drop", "alpha": "keep", "p2": "keep", "toy-db": "keep", "base-one": "approve"}
    ok_after = init_event(["alpha", "base-one"], ["p1", "p2"], ["toy-db"])

    def files(**docs):
        out = {}
        for k, v in docs.items():
            out[k] = os.path.join(d, k + ".json")
            write(out[k], v if isinstance(v, str) else json.dumps(v))
        return out

    f = files(before=before, ok=ok_after, answers=marks,
              listed=init_event(["alpha", "gamma", "base-one"], ["p1", "p2"], ["toy-db"]),
              nokeep=init_event(["gamma", "base-one"], ["p1", "p2"], ["toy-db"]),
              added=init_event(["alpha", "base-one", "fresh"], ["p1", "p2"], ["toy-db"]),
              lost=init_event(["alpha"], ["p1", "p2"], ["toy-db"]),
              empty=init_event([], [], []), blank="", notjson="{",
              stream='{"type":"system","subtype":"hook_started"}\n' + json.dumps(ok_after) + '\n{"type":"result"}\n',
              nomarks={"alpha": "approve", "gamma": "open"}, rows={"answers": [{"id": n, "answer": m} for n, m in marks.items()]})

    def diff(after, answers="answers", bef="before", **kw):
        return run(home, profiles, usage=False, json=False, init_diff=[f[bef], f[after]], answers=f[answers], **kw)
    code, out, err = diff("ok")
    want("drops gone, keeps kept, nothing added: rc 0, counts of both captures",
         (code, "before: 3 skills, 2 plugins, 2 servers" in out, "after: 2 skills, 2 plugins, 1 servers" in out), (0, True, True))
    want("the same from the stream's JSON lines, and with the answers as rows", (diff("stream")[0], diff("ok", answers="rows")[0]), (0, 0))
    code, out, err = diff("listed")
    want("a drop still listed: rc 1 naming it", (code, "drop still in init: gamma" in out), (1, True))
    code, out, err = diff("listed")
    want("control: the check that only asks 'every keep appears' passes the listed drop (expected exit 1, got 0)",
         weak_diff(usage.load_capture(f["before"]), usage.load_capture(f["listed"]), usage.load_answers(f["answers"])), 0)
    code, out, err = diff("nokeep")
    want("a keep missing: rc 1 naming it", (code, "keep missing from init: alpha" in out), (1, True))
    code, out, err = diff("added")
    want("an addition nobody declared: rc 1 naming it", (code, "unexpected addition: fresh" in out), (1, True))
    write(f["answers"], json.dumps(dict(marks, fresh="add")))
    want("the same addition marked add by the answers: rc 0", diff("added")[0], 0)
    write(f["answers"], json.dumps(marks))
    code, out, err = diff("lost")
    want("a skill that left and was not marked: rc 1 naming it", (code, "unexpected removal: base-one" in out), (1, True))
    for label, after in (("an empty capture", "empty"), ("a zero-byte capture", "blank"), ("a capture that is not JSON", "notjson")):
        want("%s: rc 2" % label, diff(after)[0], 2)
    want("an empty before capture: rc 2", diff("ok", bef="empty")[0], 2)
    want("answers that mark nothing keep, drop or add: rc 2 (zero looked at is a failure)", diff("ok", answers="nomarks")[0], 2)
    want("a capture file that is not there: rc 2", run(home, profiles, usage=False, json=False, init_diff=[f["before"], os.path.join(d, "none.json")],
                                                       answers=f["answers"])[0], 2)
    want("--init-diff without --answers: rc 2", run(home, profiles, usage=False, json=False, init_diff=[f["before"], f["ok"]])[0], 2)
    want("--init-diff with --usage: rc 1", run(home, profiles, usage=True, json=False, init_diff=[f["before"], f["ok"]], answers=f["answers"])[0], 1)
    want("--init-diff of an unknown project: rc 1", diff("ok", project="nosuch")[0], 1)
    # a mark that names something in no capture was not done, so it cannot be counted as done
    write(f["answers"], json.dumps(dict(marks, ghost="drop")))
    code, out, err = diff("ok")
    want("a drop that was in no capture: rc 1 naming it", (code, "drop not in before: ghost" in out, "PASS" in out), (1, True, False))
    write(f["answers"], json.dumps(dict(marks, ghost="add")))
    code, out, err = diff("ok")
    want("an add that never entered: rc 1 naming it", (code, "add missing from init: ghost" in out), (1, True))
    write(f["answers"], json.dumps(marks))


def main():
    tmp = sandbox.mkdtemp("usage-test-")
    for cases in (usage_cases, review_cases, init_cases):
        try:
            cases(tmp)
        except Exception as e:  # a case that cannot finish is a red line, not a traceback
            failures.append("%s raised %s: %s" % (cases.__name__, type(e).__name__, e))
    for msg in failures:
        print("FAIL", msg)
    sandbox.cleanup()
    print("test_usage: %s" % ("%d failures" % len(failures) if failures else "all passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
