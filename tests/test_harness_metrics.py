#!/usr/bin/env python3
"""`forge metrics` and the three scripts under scripts/metrics/ (research/21-para-forge/10, copied
from another project: harness-metrics.mjs at a981164f, harness-baseline.mjs at 8b5b27ad, the 26 cases of
test-harness-metrics.mjs at a981164f; the transcript-folder key became a parameter).

1. The source project's node suite, run as one case: exit 0 AND "cases run: N" with N > 0 (a suite that ran
   nothing exits 0 as well). node missing is a failure here, never a skip. Control: the same suite
   against a copy of harness-metrics.mjs that ignores --transcript-key must fail, the source project's
   "found 0 top-level transcript files in .../<wrong key>" on every case.
2. transcript_key: Claude Code's rule, every character that is not an ASCII letter or digit becomes
   `-`. Control: the source project's rule (only `/`) gives the wrong folder for a dot, a space and an
   underscore, and the same expectations are red against it.
3. harness-baseline.mjs had no test. A toy HOME holds a transcript with two start-up attachments, a
   project CLAUDE.md that imports AGENTS.md, an ancestor CLAUDE.md above the repo, the user CLAUDE.md, a
   memory index and two rules (one gated by `paths:`); every row and the total are checked. Control: the
   same world without the ancestor file must fail the same check on the ancestor row (the defect 8b5b27ad
   fixed in the source project).
4. `forge metrics NAME` (cmd_metrics) in a toy world whose project path has a dot and a space: the unknown
   project, a profile without project_path and a missing transcript folder are FAILs naming the project; the
   metrics and the baseline reach the right folder.

Seen failing before the change: 1 on "no such file: scripts/metrics/test-harness-metrics.mjs";
2 and 4 on "AttributeError: module 'forge.cli' has no attribute 'transcript_key'" / "'cmd_metrics'"."""
import argparse
import contextlib
import datetime
import io
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from forge import cli, lib  # noqa: E402
import sandbox  # noqa: E402

METRICS = os.path.join(sandbox.FORGE, "scripts", "metrics")
failures = []
SESSION_START = datetime.datetime(2001, 9, 9, 10, 0, tzinfo=datetime.timezone.utc)


def stamp(seconds=0, days=0):
    """An ISO timestamp `seconds` and `days` after the toy session's start: the fixtures need dates, and a
    computed one is a fixture, not a dated claim."""
    return (SESSION_START + datetime.timedelta(seconds=seconds, days=days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def want(label, got, expected):
    if got != expected:
        failures.append("%s = %r, want %r" % (label, got, expected))


def node(*args, env=None):
    """(exit code, stdout, stderr) of node over `args`; (None, '', 'node not found') without it."""
    exe = shutil.which("node")
    if not exe:
        return None, "", "node not found"
    r = subprocess.run([exe] + list(args), capture_output=True, text=True, env=env, timeout=300)
    return r.returncode, r.stdout, r.stderr


def suite(script=None):
    """What the node suite did: (exit code, N of "cases run: N", the first FAIL line)."""
    code, out, err = node(os.path.join(METRICS, "test-harness-metrics.mjs"), *([script] if script else []))
    m = re.search(r"^cases run: (\d+)", out, re.M)
    first = next((l for l in (out + err).splitlines() if l.startswith("FAIL")), "")
    return code, int(m.group(1)) if m else None, first


def suite_cases(tmp):
    code, n, _ = suite()
    want("the node suite", (code, n is not None and n > 0), (0, True))
    # A copy that reads the wrong folder whatever it is told: every case must fail.
    with open(os.path.join(METRICS, "harness-metrics.mjs"), encoding="utf-8") as fh:
        text = fh.read()
    anchor = "join(projectsDir, key),"
    want("the control's anchor is in the script", anchor in text, True)
    wrong = os.path.join(tmp, "wrong-key.mjs")
    with open(wrong, "w", encoding="utf-8") as fh:
        fh.write(text.replace(anchor, 'join(projectsDir, "-wrong-key"),'))
    code, n, first = suite(wrong)
    want("control: the suite against a script that ignores the key", (code, n is not None and n > 0,
         "found 0 top-level transcript files" in first), (1, True, True))
    # A script run with no key or no repository says so and exits 1.
    for flag in ("--transcript-key=k", "--repo=/x"):
        code, _, err = node(os.path.join(METRICS, "harness-metrics.mjs"), flag)
        want("harness-metrics.mjs with only %s" % flag.split("=")[0], (code, "is required" in err), (1, True))
        code, _, err = node(os.path.join(METRICS, "harness-baseline.mjs"), flag)
        want("harness-baseline.mjs with only %s" % flag.split("=")[0], (code, "is required" in err), (1, True))


# Folders Claude Code made, read from ~/.claude/projects beside the cwd in their transcripts.
KEYS = [
    ("/home/user/dev/Projects/forge", "-home-user-dev-Projects-forge"),
    ("/home/user/.cache/app-day5/reviewers-live/deny/work", "-home-user--cache-app-day5-reviewers-live-deny-work"),
    ("/home/user/dev/Projects/notes/vault/2 - Sources/academic/AP/Y2/Q1/32VAN",
     "-home-user-dev-Projects-notes-vault-2---Sources-academic-AP-Y2-Q1-32VAN"),
    # Not seen in a folder yet; the rule in Claude Code 2.1.294 (`replace(/[^a-zA-Z0-9]/g, "-")`) says so.
    ("/home/user/dev/a.b c", "-home-user-dev-a-b-c"),
    ("/home/user/dev/my_app", "-home-user-dev-my-app"),
    ("/home/user/café", "-home-user-caf-"),
    ("/home/user/\U0001f600", "-home-user---"),
]


def portal_key(path):
    """The source project's derivation in harness-baseline.mjs (8b5b27ad): only the slash changes."""
    return path.replace("/", "-")


def key_cases():
    for path, expected in KEYS:
        want("transcript_key(%r)" % path, getattr(cli, "transcript_key", lambda p: "no transcript_key")(path), expected)
    # The control: the same expectations against the source project's rule are red for every path with a
    # character other than a letter, a digit, a dash or a slash.
    red = [path for path, expected in KEYS if portal_key(path) != expected]
    want("control: paths the source project's derivation gets wrong", len(red), 6)
    want("control: a dot, a space and an underscore are among them",
         {"/home/user/dev/a.b c", "/home/user/dev/my_app"} <= set(red), True)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return len(text.encode("utf-8"))


def baseline_world(tmp, name, ancestor=True):
    """(env, args, expected rows): a toy HOME and a repo whose path has a dot and a space, and the
    bytes each row of harness-baseline.mjs must report."""
    home = os.path.join(tmp, name, "home")
    repo = os.path.join(home, "work", "my.repo x")
    key = getattr(cli, "transcript_key", lambda p: "no-transcript-key")(repo)
    sessions = os.path.join(home, ".claude", "projects", key)
    rows = {
        "CLAUDE.md (project)": write(os.path.join(repo, "CLAUDE.md"), "project rules\n" "@AGENTS.md\n"),
        "CLAUDE.local.md (project)": 0,
        "AGENTS.md (imported by CLAUDE.md)": write(os.path.join(repo, "AGENTS.md"), "agents text " * 7),
        "CLAUDE.md (user)": write(os.path.join(home, ".claude", "CLAUDE.md"), "user rules " * 5),
        "MEMORY.md (auto-memory index)": write(os.path.join(sessions, "memory", "MEMORY.md"), "- a memory\n" * 3),
        "rules with no paths: (always on)": write(os.path.join(repo, ".claude", "rules", "always.md"), "always on " * 11),
    }
    write(os.path.join(repo, ".claude", "rules", "gated.md"), "---\npaths:\n  - src/**\n---\n" + "gated " * 40)
    if ancestor:
        rows["%s (ancestor)" % os.path.join(home, "work", "CLAUDE.md")] = write(
            os.path.join(home, "work", "CLAUDE.md"), "above the repo " * 4)
    skills = {"type": "skill_listing", "content": "- skill: " * 20}
    hook = {"type": "hook_success", "hookEvent": "SessionStart", "stdout": "started " * 9}
    later = {"type": "skill_listing", "content": "again " * 99}  # a type counts once, at its first appearance
    attachments = {"skill_listing": len(json.dumps(skills, separators=(",", ":"))),
                   "SessionStart hook stdout": len(json.dumps(hook, separators=(",", ":")))}
    lines = [{"type": "attachment", "attachment": a} for a in (skills, hook, later)] + [
        {"type": "user", "timestamp": stamp(), "message": {"role": "user", "content": "go"}}]
    write(os.path.join(sessions, "s1.jsonl"), "".join(json.dumps(l) + "\n" for l in lines))
    env = {"HOME": home, "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "TMPDIR": os.environ.get("TMPDIR", "/tmp")}
    return env, ["--repo=" + repo, "--transcript-key=" + key, "--json"], attachments, rows


def baseline_problems(env, args, attachments, rows):
    """What differs between harness-baseline.mjs's report and the bytes the toy world holds."""
    code, out, err = node(os.path.join(METRICS, "harness-baseline.mjs"), *args, env=env)
    if code != 0:
        return ["exit %s: %s" % (code, (err or out).strip()[:200])]
    rep = json.loads(out)
    bad = ["attachments %r, want %r" % (rep["attachments"], attachments)] if rep["attachments"] != attachments else []
    bad += ["row %r = %r, want %r" % (k, rep["instructions"].get(k), v) for k, v in rows.items()
            if rep["instructions"].get(k, 0) != v]
    # Ancestors above the toy HOME (/tmp, /) belong to the machine, so they are named, not summed away.
    extra = {k: v for k, v in rep["instructions"].items() if k.endswith("(ancestor)") and k not in rows}
    want_total = sum(attachments.values()) + sum(rows.values()) + sum(extra.values())
    if rep["total"] != want_total:
        bad.append("total = %r, want %r" % (rep["total"], want_total))
    return bad


def baseline_cases(tmp):
    world = baseline_world(tmp, "baseline")
    want("harness-baseline.mjs over a toy world", baseline_problems(*world), [])
    # The control: without the CLAUDE.md above the repo the ancestor row is absent, so the same check
    # (expecting it) has to come back red, naming the row.
    bare = baseline_world(tmp, "baseline-bare", ancestor=False)
    expecting = baseline_world(tmp, "baseline-bare-expecting")[3]
    problems = baseline_problems(bare[0], bare[1], bare[2], expecting)
    want("control: no ancestor file, the ancestor row is red", any("(ancestor)" in p for p in problems), True)
    # Also: the session id selects a session, and a missing one is a FAIL naming the folder.
    code, _, err = node(os.path.join(METRICS, "harness-baseline.mjs"), *world[1], "nosuchsession", env=world[0])
    want("a session id with no transcript", (code, "No session transcript found" in err), (1, True))


def commit_world(tmp):
    """(toy HOME, repo path, profiles dir): a repo at a path with a dot and a space holding one commit,
    one session in the transcript folder cli.transcript_key names whose Bash call made that commit, and
    profiles for it, for one with no project_path and for one whose transcripts are missing."""
    home = os.path.join(tmp, "cli", "home")
    repo = os.path.join(tmp, "cli", "work", "my.repo x")
    os.makedirs(repo)
    sandbox.git(repo, "init", "-q")
    sandbox.git(repo, "commit", "-q", "--allow-empty", "-m", "feat: one")
    short = sandbox.git(repo, "rev-parse", "--short=8", "HEAD").strip()
    key = getattr(cli, "transcript_key", lambda p: "no-transcript-key")(repo)
    turn = [
        {"type": "user", "timestamp": stamp(), "message": {"role": "user", "content": "go"}},
        {"type": "assistant", "timestamp": stamp(60), "requestId": "r1", "message": {
            "id": "m1", "role": "assistant", "usage": {"input_tokens": 0, "cache_creation_input_tokens": 100,
                                                       "cache_read_input_tokens": 0, "output_tokens": 0},
            "content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "git commit -m x"}}]}},
        {"type": "user", "timestamp": stamp(63), "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "[main %s] feat: one" % short, "is_error": False}]},
         "toolUseResult": {"stdout": "[main %s] feat: one" % short, "stderr": "", "interrupted": False, "isImage": False}},
    ]
    write(os.path.join(home, ".claude", "projects", key, "s1.jsonl"), "".join(json.dumps(l) + "\n" for l in turn))
    profiles = os.path.join(tmp, "cli", "profiles")
    for name, prof in {"toy": {"project_path": repo}, "nopath": {}, "notranscripts": {"project_path": os.path.join(tmp, "cli", "elsewhere")}}.items():
        write(os.path.join(profiles, name + ".claude.json"), json.dumps(dict(prof, project=name)))
    os.makedirs(os.path.join(tmp, "cli", "elsewhere"))
    return home, repo, profiles


def forge_metrics(home, profiles, **kw):
    """(exit code, stdout, stderr) of cli.cmd_metrics over the toy world (the real HOME and profiles are never read)."""
    args = dict(project="toy", session=None, baseline=False, since=None, until=None, events_until=None, json=True)
    args.update(kw)
    real = lib.HOME, lib.PROFILES
    lib.HOME, lib.PROFILES = home, profiles
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = getattr(cli, "cmd_metrics")(argparse.Namespace(**args))
    except Exception as e:
        code = "raised %s: %s" % (type(e).__name__, e)
    finally:
        lib.HOME, lib.PROFILES = real
    return code, out.getvalue(), err.getvalue()


def metrics_cases(tmp):
    home, repo, profiles = commit_world(tmp)
    if not hasattr(cli, "cmd_metrics"):
        want("forge metrics exists", "no cmd_metrics", "cmd_metrics")
        return
    code, out, err = forge_metrics(home, profiles)
    report = json.loads(out) if code == 0 else {}
    want("forge metrics over a toy project", (code, report.get("metric2_tokensPerChange", {}).get("totalCommits")), (0, 1))
    want("forge metrics --since after the session: zero sessions is a FAIL", forge_metrics(home, profiles, since=stamp(days=30)[:10])[0], 1)
    code, out, err = forge_metrics(home, profiles, baseline=True)
    want("forge metrics --baseline", (code, json.loads(out)["session"].endswith("s1.jsonl") if code == 0 else None), (0, True))
    code, out, err = forge_metrics(home, profiles, baseline=True, session="nosuch")
    want("forge metrics --baseline with an unknown session", (code, "No session transcript found" in err), (1, True))
    code, out, err = forge_metrics(home, profiles, project="nosuch")
    want("forge metrics of an unknown project", (code, "unknown project: nosuch" in out), (1, True))
    code, out, err = forge_metrics(home, profiles, project="nopath")
    want("forge metrics of a profile without project_path", (code, "nopath: the profile has no project_path" in out), (1, True))
    code, out, err = forge_metrics(home, profiles, project="notranscripts")
    want("forge metrics of a project with no transcript folder", (code, "FAIL" in out, "notranscripts: no transcript folder" in out), (1, True, True))
    want("forge metrics --baseline with --since", forge_metrics(home, profiles, baseline=True, since=stamp()[:10])[0], 1)
    want("forge metrics with a session id and no --baseline", forge_metrics(home, profiles, session="s1")[0], 1)


def main():
    tmp = sandbox.mkdtemp("harness-metrics-test-")
    suite_cases(tmp)
    key_cases()
    baseline_cases(tmp)
    metrics_cases(tmp)
    for msg in failures:
        print("FAIL", msg)
    print("%d failure(s)" % len(failures))
    sandbox.cleanup(failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
