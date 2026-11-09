"""The audit of what each subagent was handed: `fwx context-base audit`, read from the transcripts, never from what a model says.

Claude Code writes one transcript per subagent, `<projects-dir>/<folder>/<session>/subagents/agent-<id>.jsonl` (a Workflow agent
under `subagents/workflows/wf_<id>/`) with an `agent-<id>.meta.json` beside it, and records a SubagentStart hook's context as an
attachment of type `hook_additional_context` whose `content` is a list of strings, one per hook (measured, 2.5 U1). This module
compares what that attachment carries with what the table of cases (data/context-base.tsv) says the agent's type should get, and
with the base file as it is today.

Per agent, one verdict:
  ok          got what its type gets (or got nothing and its type gets nothing)
  stale       got the base, but its mark is not today's (a warning, not a failure)
  not armed   got nothing, and there is no base file today (no `--file`, no open phase with a base): counted, not a failure
  missing     should have got the base, there is one today, and no attachment carries it (with the hook's stderr when it failed)
  over-cap    an entry starts with `<persisted-output>`: Claude Code stored a context over 10,000 units instead of delivering it
  wrong       a type that gets nothing was handed the base, or a type without `map+decided` was handed `## Decided`
  double      two `# Base context` marks in what one agent was handed

Only the entries that carry the base's mark count as ours: another hook's `hook_additional_context` (a memory plugin's, say) is
ignored. A hook that exits 0 with no output leaves no attachment at all (measured), so silence is judged by the file of today and
never by a `hook_success`.

Imports the standard library, config, state and context_base.
"""
import glob
import json
import os
import re

from fwx import config, context_base as cb, state

MARK_LINE = re.compile(r"^# Base context · [0-9a-f]{8}$", re.M)
PERSISTED = "<persisted-output>"
DECIDED = re.compile(r"^## Decided$", re.M)
FAILS = ("missing", "over-cap", "wrong", "double")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
UNKNOWN_TYPE = "?"  # no meta.json: the hook saw a type we cannot, so the default row of the table is the best guess


class AuditError(Exception):
    """A usage problem or an unusable input; the message says which."""


def projects_dir(given=None):
    return given or os.path.join(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude"), "projects")


def _folder_name(path):
    """Claude Code's folder of a cwd: every character that is not a letter or a digit becomes `-` (measured, 2.5 U1 c)."""
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def _project_folders(pdir, project):
    """The folders of `pdir` that belong to `project`: the encoded name, and above 200 characters the first 200 and `-<hash>`
    (the hash is not computed here: a prefix match)."""
    found = []
    for p in dict.fromkeys([os.path.abspath(project), os.path.realpath(project)]):
        name = _folder_name(p)
        if len(name) <= 200:
            cands = [name]
        else:
            cands = [d for d in _listdir(pdir) if d.startswith(name[:200] + "-") and len(d) == 207]
        for c in cands:
            full = os.path.join(pdir, c)
            if os.path.isdir(full) and full not in found:
                found.append(full)
    return found


def _listdir(d):
    try:
        return sorted(os.listdir(d))
    except (FileNotFoundError, NotADirectoryError):
        return []


def _has_agents(session_dir):
    return bool(glob.glob(os.path.join(session_dir, "subagents", "**", "agent-*.jsonl"), recursive=True))


def find_sessions(pdir, session=None, project=None, last=1):
    """`[(session_id, folder)]`: the session `session` wherever it lives (`<pdir>/*/<session>`, found by its id: the folder's
    name is not computed), or the `last` most recent sessions of `project` that have a subagent transcript, newest first
    (by the modification time of the session's own transcript, else of its folder)."""
    if session is not None:
        if not _ID.match(session):
            raise AuditError("bad session id %r: letters, digits, . _ - only" % (session,))
        return [(session, d) for d in sorted(glob.glob(os.path.join(glob.escape(pdir), "*", session))) if os.path.isdir(d)
                and _has_agents(d)]
    found = []
    for folder in _project_folders(pdir, project):
        for name in _listdir(folder):
            d = os.path.join(folder, name)
            if os.path.isdir(d) and _has_agents(d):
                own = d + ".jsonl"
                found.append((os.path.getmtime(own if os.path.exists(own) else d), name, d))
    found.sort(reverse=True)
    return [(name, d) for _, name, d in found[:last]]


def _json_line(line):
    try:
        v = json.loads(line)
    except ValueError:
        return None
    return v if isinstance(v, dict) else None


def _cwd_of(path):
    """The `cwd` of the first line of a transcript that has one, or None."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"cwd"' in line:
                    v = _json_line(line)
                    if v and isinstance(v.get("cwd"), str):
                        return v["cwd"]
    except OSError:
        pass
    return None


def agent_files(session_dir):
    """`[(agent_id, jsonl path)]` of every subagent transcript of a session, the Workflow ones included, in path order."""
    paths = sorted(glob.glob(os.path.join(glob.escape(session_dir), "subagents", "**", "agent-*.jsonl"), recursive=True))
    return [(os.path.basename(p)[len("agent-"):-len(".jsonl")], p) for p in paths]


def agent_type(jsonl_path):
    try:
        with open(jsonl_path[:-len(".jsonl")] + ".meta.json", encoding="utf-8") as f:
            t = json.load(f).get("agentType")
    except (OSError, ValueError, AttributeError):
        return UNKNOWN_TYPE
    return t if isinstance(t, str) and t else UNKNOWN_TYPE


def read_agent(jsonl_path):
    """What a transcript says about the SubagentStart hooks: `{entries: [str], errors: [stderr]}`. `entries` are the strings
    of every `hook_additional_context` attachment of that event; `errors` the stderr of its `hook_non_blocking_error`s."""
    entries, errors = [], []
    with open(jsonl_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if "hook_additional_context" not in line and "hook_non_blocking_error" not in line:
                continue
            v = _json_line(line)
            a = v.get("attachment") if v else None
            if not isinstance(a, dict) or a.get("hookEvent") != "SubagentStart":
                continue
            if a.get("type") == "hook_additional_context":
                c = a.get("content")
                entries += [x for x in (c if isinstance(c, list) else [c]) if isinstance(x, str)]
            elif a.get("type") == "hook_non_blocking_error":
                errors.append(str(a.get("stderr", "")).strip())
    return {"entries": entries, "errors": errors}


def judge(agent_type_, read, today):
    """`(verdict, detail)` for one agent. `today` is the text of the base file as it is now, or None when there is none."""
    want = cb.sections_for(agent_type_)
    mine = [e for e in read["entries"] if MARK_LINE.search(e) or (e.startswith(PERSISTED) and (want != "none" or MARK_LINE.search(e)))]
    persisted = [e for e in mine if e.startswith(PERSISTED)]
    if persisted:
        return "over-cap", "Claude Code stored the context instead of delivering it"
    got = "\n".join(mine)
    if not mine:
        if want == "none":
            return "ok", ""
        if today is None:
            return "not armed", ""
        err = next((e for e in read["errors"] if "context-base" in e), read["errors"][0] if read["errors"] else "")
        return "missing", ("hook error: " + err) if err else "no hook_additional_context carries the base"
    if want == "none":
        return "wrong", "its type gets nothing and it was handed the base"
    if want == "map" and DECIDED.search(got):
        return "wrong", "handed `## Decided`, its type gets the map only"
    n = len(MARK_LINE.findall(got))
    if n > 1:
        return "double", "%d `# Base context` marks in what it was handed" % n
    if today is not None and MARK_LINE.search(got).group(0) != today.split("\n", 1)[0]:
        return "stale", "its mark %s is not today's %s" % (MARK_LINE.search(got).group(0)[len("# Base context · "):],
                                                        today.split("\n", 1)[0][len("# Base context · "):])
    return "ok", ""


def _today(cwd, session_id, fixed):
    """The base file's text as it is now: `fixed` (the path of --file) or the base of the phase the session resolves to."""
    if fixed is not None:
        return cb._text(fixed)
    if not cwd or not os.path.isdir(cwd):
        return None
    try:
        phase = state.resolve(cwd, session_id)["phase_dir"]
        return cb._text(cb.base_path(phase)) if phase else None
    except (state.StateError, config.ConfigError, cb.ContextBaseError, OSError):
        return None


def audit(sessions, file=None, project=None):
    """`{sessions, rows: [{session, id, type, verdict, detail}], counts}` over `sessions` (from `find_sessions`)."""
    if file is not None and cb._text(file) is None:
        raise AuditError("%s is not there" % file)
    rows = []
    for sid, folder in sessions:
        files = agent_files(folder)
        own = folder + ".jsonl"
        cwd = project or _cwd_of(own) or next((c for c in (_cwd_of(p) for _, p in files) if c), None)
        today = _today(cwd, sid, file)
        for aid, path in files:
            t = agent_type(path)
            verdict, detail = judge(t, read_agent(path), today)
            rows.append({"session": sid, "id": aid, "type": t, "verdict": verdict, "detail": detail})
    counts = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    return {"sessions": len(sessions), "rows": rows, "counts": counts}


def report(result):
    """The lines to print and the exit code: 77 with no transcript, 1 with any failure, else 0."""
    rows, c = result["rows"], result["counts"]
    if not rows:
        return ["NOT RUN, NOT ARMED: no subagent transcript found"], 77
    out = ["audited %d subagent(s) in %d session(s): %d ok, %d stale, %d not armed"
           % (len(rows), result["sessions"], c.get("ok", 0), c.get("stale", 0), c.get("not armed", 0))]
    for r in rows:
        if r["verdict"] in FAILS:
            out.append("FAIL %s %s: %s%s" % (r["id"], r["type"], r["verdict"], (" (%s)" % r["detail"]) if r["detail"] else ""))
        elif r["verdict"] == "stale":
            out.append("WARN %s %s: stale (%s)" % (r["id"], r["type"], r["detail"]))
    return out, 1 if any(r["verdict"] in FAILS for r in rows) else 0
