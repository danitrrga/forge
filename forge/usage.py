"""What a project's agent really uses, counted from its Claude Code transcripts, and the check of an applied
project by the difference of two `init` captures. `forge metrics NAME --usage` and `--init-diff` (cli.cmd_metrics)
are thin over this module; it imports the standard library only and reads no configuration of its own.

Usage (`collect`, `report`)
  Folders  : under the projects directory, the transcript folder of the project path, of every worktree
             `git worktree list --porcelain` names, of every `<project>/.claude/worktrees/*` and of the
             `worktree_guard.worktree_dirs` of the project (a `path` holds worktrees directly under it, a `prefix`
             names the folder itself; a child of such a folder that is, or is under, another project's project_path is
             that project's and is left out, counted in `looked_at.left_out_other_projects`). They are found by
             listing the projects directory, not by guessing each key,
             because a worktree that was removed has no entry in git and its transcripts stay. A folder that only
             shares the project's key as a prefix (`<key>-other`) is another project and is not read.
  Files    : the top-level `*.jsonl` of each folder (one session each) and `<session>/subagents/*.jsonl`, which
             count toward the parent session. Nothing else is read, and never `~/.claude.json`: its `skillUsage`
             is global, so it cannot say which project used what.
  Counted  : a `Skill` tool_use (`input.skill`; with `:` a plugin skill; a name found under
             `<project>/.claude/skills` a project skill), a `<command-name>` of a user message when the name is a
             listed or project skill (any other /command, built-in or not, is only counted in `unlisted_commands`), a `mcp__<server>__<tool>`
             tool_use (a server named `plugin_<plugin>_<server>` is a plugin's), and the `subagent_type` of an
             `Agent` tool_use. One tool_use id counts once however many lines repeat it.
  Cost     : read from the most recent session that carries each piece, which is not always the same session:
             `listed_bytes` of a skill is its line in the last initial `skill_listing`; of an MCP server, the bytes
             of its tool names in that session's `deferred_tools_delta` (added minus removed); `startup_bytes` of a
             plugin is the stdout of its SessionStart hooks, attributed by the `plugins/cache/<marketplace>/<plugin>/`
             in the hook's command. Real transcripts keep `${CLAUDE_PLUGIN_ROOT}` unexpanded, which names no plugin: the
             output of a hook that matches nothing is counted apart (`startup_unattributed`), and `plugins` is null
             when no hook of the session matched, because the per-plugin cost was then not measured.
  Format   : the attachment fields read (`skill_listing.content` and `.isInitial`, `deferred_tools_delta.addedNames` /
             `addedLines` / `removedNames`, `hook_success.command` and `.stdout`) are Claude Code's transcript format as
             the toy fixture has it, NOT checked against a real transcript when this was written (only the type names
             and `hookEvent` are the ones scripts/metrics/harness-baseline.mjs reads). A field that is named otherwise
             reads as 0 bytes and an empty `listing`, visible in the report; the fixture cannot catch that.

Zero sessions is an error (`usage unknown`), never "0 uses"; fewer than MIN_SESSIONS is reported as `few sessions`.

Init diff (`init_diff`)
  Two captures of the `system/init` event of `claude -p --output-format stream-json` (a JSON object, a JSON array
  of events, or the stream's JSON lines; `skills`, `plugins` and `mcp_servers` are read) and the answers
  of the review (`{name: "keep" | "drop" | "add"}`, or `{"answers": ...}`, or rows `{"id"|"name", "answer"|"mark"}`;
  any other mark, such as `approve` or `open`, is not a claim about the init). A function over the two captures
  because the init also lists the common base, plugin, built-in and project skills: "exactly the marked set" is
  impossible, and "every keep appears" passes with a drop still listed. It passes when no drop is in `after`,
  every keep is, nothing left that was not a drop, and nothing entered that the answers do not mark `add`.
"""
import collections
import glob
import json
import os
import re
import subprocess

MIN_SESSIONS = 5  # no better figure yet (plan 4.2, appendix B): adjusted when the real counts are seen
LISTING_SESSIONS = 10  # `listing` of the report: the most recent sessions that carry a skill listing
KINDS = ("skill", "project-skill", "plugin-skill", "mcp", "plugin-mcp", "agent")
WORKTREES = "--claude-worktrees-"  # what `/.claude/worktrees/` becomes in a folder key
_COMMAND = re.compile(r"<command-name>/?([^<]+)</command-name>")
_PLUGIN_DIR = re.compile(r"plugins/cache/[^/]+/([^/]+)/")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class UsageError(Exception):
    """An input the report cannot be built from; the message is one line that says which."""


def date_ok(s):
    return bool(_DATE.match(s or ""))


def git_worktrees(project_path):
    """The paths `git worktree list --porcelain` gives in project_path; [] when it is no repository or git is not
    there (the transcripts decide, and zero sessions is its own error)."""
    if not os.path.isdir(project_path):
        return []
    try:
        r = subprocess.run(["git", "-C", project_path, "worktree", "list", "--porcelain"], capture_output=True,
                           text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return []
    if r.returncode != 0:
        return []
    return [l[len("worktree "):] for l in r.stdout.splitlines() if l.startswith("worktree ")]


def worktree_dir_specs(prof, home):
    """[(kind, path)] of the project's worktree_guard.worktree_dirs, `~/` expanded against `home`; raises UsageError
    for an entry that is neither {"path": str} nor {"prefix": str} (a folder left out is usage left out)."""
    guard = prof.get("worktree_guard")
    rows = guard.get("worktree_dirs", []) if isinstance(guard, dict) else []
    if not isinstance(rows, list):
        raise UsageError("worktree_guard.worktree_dirs is not a list")
    out = []
    for i, row in enumerate(rows):
        kind = next((k for k in ("path", "prefix") if isinstance(row, dict) and isinstance(row.get(k), str) and row[k]), None)
        if kind is None:
            raise UsageError("worktree_guard.worktree_dirs[%d] has neither a path nor a prefix" % i)
        p = row[kind]
        out.append((kind, os.path.join(home, p[2:]) if p.startswith("~/") else p))
    return out


def folders(projects_dir, project_path, specs, registered, key, others=()):
    """(the folder names under projects_dir that hold this project's sessions, how many folders were left out as
    another project's). A folder that is the project's own, a registered worktree or under `.claude/worktrees` is
    admitted outright. A folder that only matches a `worktree_dirs` entry is admitted unless it is, or is under, the
    path of one of `others` (the other projects' paths) and no more specific path of this project claims it: the
    entry names the folder that holds every project, so its direct children include the sibling projects."""
    try:
        names = sorted(os.listdir(projects_dir))
    except FileNotFoundError:
        return [], 0
    own = key(project_path)
    exact = {own} | {key(p) for p in registered}
    own_pref = own + WORKTREES
    prefixes = [key(p) + ("-" if k == "path" else "") for k, p in specs]
    other_keys = [key(o) for o in others if o != project_path]

    def claim(n, k):
        return len(k) if n == k or n.startswith(k + "-") else -1
    out, left_out = [], 0
    for n in names:
        if not os.path.isdir(os.path.join(projects_dir, n)):
            continue
        if n in exact or n.startswith(own_pref):
            out.append(n)
        elif any(n.startswith(p) for p in prefixes):
            if max((claim(n, k) for k in other_keys), default=-1) > claim(n, own):
                left_out += 1
            else:
                out.append(n)
    return out, left_out


def _blocks(d):
    m = d.get("message")
    c = m.get("content") if isinstance(m, dict) else None
    return c if isinstance(c, list) else []


def _texts(d):
    m = d.get("message")
    c = m.get("content") if isinstance(m, dict) else None
    if isinstance(c, str):
        return [c]
    return [b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"] if isinstance(c, list) else []


class Session:
    def __init__(self, sid, folder):
        self.id, self.folder = sid, folder
        self.first = self.last = None  # dates of the main file's lines
        self.uses = []  # (kind of use, name, date): "skill", "command", "mcp", "agent"
        self.listing = None  # content of the last initial skill_listing
        self.names = None  # tool names live after the deferred_tools_delta lines
        self.hooks = collections.Counter()  # plugin -> SessionStart stdout bytes
        self.hook_n = self.hook_n_attr = self.hook_bytes = 0  # every SessionStart hook, and the part that names a plugin
        self._ids = set()


def read_file(path, sess, main, since, counts):
    """Fold one transcript file into `sess`. `main` False is a subagent file: its tool use counts, its start-up
    attachments (which are its own, not the session's) do not. With `since` a line before it counts as nothing and is
    not dated, but the start-up attachments are read whatever it says; a line with no stamp takes the one before it."""
    date = None
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except OSError as e:
        raise UsageError("cannot read %s: %s" % (path, e.strerror or e))
    with fh:
        for raw in fh:
            if not raw.strip():
                continue
            try:
                d = json.loads(raw)
            except ValueError:
                counts["unreadable_lines"] += 1
                continue
            if not isinstance(d, dict):
                counts["unreadable_lines"] += 1
                continue
            ts = d.get("timestamp")
            if isinstance(ts, str) and _DATE.match(ts[:10]):
                date = ts[:10]
            if main:
                _startup(d, sess)  # whatever `since` says: the listing a later /command is judged against is read once, at the start
            if since and date and date < since:
                continue
            if main and date:
                sess.first = min(sess.first or date, date)
                sess.last = max(sess.last or date, date)
            _uses(d, sess, date)


def _startup(d, sess):
    a = d.get("attachment")
    if not isinstance(a, dict):
        return
    t = a.get("type")
    if t == "skill_listing" and a.get("isInitial", True) and isinstance(a.get("content"), str):
        sess.listing = a["content"]
    elif t == "deferred_tools_delta":
        names = a.get("addedNames")
        if not isinstance(names, list):
            names = [l.split(":", 1)[0].strip() for l in a.get("addedLines", []) if isinstance(l, str)]
        live = set(sess.names or ()) | {n for n in names if isinstance(n, str)}
        live -= {n for n in a.get("removedNames", []) if isinstance(n, str)}
        sess.names = live
    elif t == "hook_success" and str(a.get("hookEvent") or a.get("hookName") or "").startswith("SessionStart"):
        size = len(str(a.get("stdout") or "").encode("utf-8"))
        sess.hook_n += 1
        sess.hook_bytes += size
        m = _PLUGIN_DIR.search(str(a.get("command") or ""))
        if m:
            sess.hooks[m.group(1)] += size
            sess.hook_n_attr += 1


def _uses(d, sess, date):
    if d.get("type") == "assistant":
        for b in _blocks(d):
            if not isinstance(b, dict) or b.get("type") != "tool_use":
                continue
            if b.get("id") is not None:
                if b["id"] in sess._ids:
                    continue
                sess._ids.add(b["id"])
            name, inp = b.get("name") or "", b.get("input") if isinstance(b.get("input"), dict) else {}
            if name == "Skill" and isinstance(inp.get("skill"), str):
                sess.uses.append(("skill", inp["skill"].lstrip("/"), date))
            elif name in ("Agent", "Task"):
                sess.uses.append(("agent", inp.get("subagent_type") if isinstance(inp.get("subagent_type"), str)
                                  else "general-purpose", date))
            elif name.startswith("mcp__") and name.count("__") >= 2:
                sess.uses.append(("mcp", name.split("__")[1], date))
    elif d.get("type") == "user":
        for text in _texts(d):
            m = _COMMAND.search(text)
            if m:
                sess.uses.append(("command", m.group(1).strip(), date))


def collect(projects_dir, names, since=None):
    """(sessions, counts): the Session of each top-level transcript under the folders `names`, with its subagent
    files folded in. With `since`, a session with no line from that day on is left out."""
    sessions, counts = [], collections.Counter()
    for folder in names:
        base = os.path.join(projects_dir, folder)
        for f in sorted(glob.glob(os.path.join(base, "*.jsonl"))):
            sid = os.path.basename(f)[:-len(".jsonl")]
            s = Session(sid, folder)
            read_file(f, s, True, since, counts)
            if since and not (s.last and s.last >= since):
                continue
            subs = sorted(glob.glob(os.path.join(base, sid, "subagents", "*.jsonl")))
            for sf in subs:
                read_file(sf, s, False, since, counts)
            counts["subagent_files"] += len(subs)
            sessions.append(s)
    return sessions, counts


def _listing_lines(content):
    """{skill name: bytes of its line} of a skill_listing's content: lines `- <name>: <description>`, or `- <name>` alone when the description did not fit."""
    out = {}
    for line in content.splitlines():
        m = re.match(r"^- (\S+?)(?::(?: |$)|$)", line)
        if m:
            out[m.group(1)] = len(line.encode("utf-8"))
    return out


def _skill_kind(name, project_skills):
    if name in project_skills:
        return "project-skill", None
    if ":" in name:
        return "plugin-skill", name.split(":", 1)[0]
    return "skill", None


def _server_kind(server):
    if server.startswith("plugin_") and "_" in server[len("plugin_"):]:
        return "plugin-mcp", server[len("plugin_"):].split("_", 1)[0]
    return "mcp", None


def _newest(sessions, has):
    """The most recent session `has` says yes to (by its last day, then its id), or None."""
    return max((s for s in sessions if has(s)), key=lambda s: (s.last or "", s.id), default=None)


def report(project, sessions, counts, folder_names, project_skills, left_out=0):
    """The JSON of schema 1 (plan 4.2, appendix C) for the sessions read."""
    project_skills = set(project_skills)
    listed = set(project_skills)
    for s in sessions:
        if s.listing:
            listed |= set(_listing_lines(s.listing))
    items = {}

    def item(kind, name, plugin):
        return items.setdefault((kind, name), {
            "kind": kind, "name": name, "plugin": plugin, "listed_bytes": 0, "tools": 0, "calls": 0,
            "via": {"tool": 0, "command": 0}, "sessions": 0, "last_seen": None, "_s": set()})

    def use(it, via, s, date):
        it["calls"] += 1
        it["via"][via] += 1
        it["_s"].add(s.id)
        if date:
            it["last_seen"] = max(it["last_seen"] or date, date)

    unlisted = collections.Counter()  # a /command that is no listed skill: a built-in, a plugin's or the project's own command
    for s in sessions:
        for how, name, date in s.uses:
            if how == "command" and name not in listed:
                unlisted[name] += 1
            elif how == "skill" or how == "command":
                kind, plugin = _skill_kind(name, project_skills)
                use(item(kind, name, plugin), "tool" if how == "skill" else "command", s, date)
            elif how == "mcp":
                kind, plugin = _server_kind(name)
                use(item(kind, name, plugin), "tool", s, date)
            elif how == "agent":
                use(item("agent", name, name.split(":", 1)[0] if ":" in name else None), "tool", s, date)
    top = _newest(sessions, lambda s: s.listing)
    if top:
        for name, size in _listing_lines(top.listing).items():
            kind, plugin = _skill_kind(name, project_skills)
            item(kind, name, plugin)["listed_bytes"] = size
    for name in project_skills:
        item("project-skill", name, None)
    names_session = _newest(sessions, lambda s: s.names is not None)
    if names_session:
        servers = collections.defaultdict(list)
        for n in sorted(names_session.names):
            if n.startswith("mcp__") and n.count("__") >= 2:
                servers[n.split("__")[1]].append(n)
        for server, tools in servers.items():
            kind, plugin = _server_kind(server)
            it = item(kind, server, plugin)
            it["listed_bytes"], it["tools"] = sum(len(t.encode("utf-8")) for t in tools), len(tools)
    hooks_session = _newest(sessions, lambda s: s.hook_n)
    for it in items.values():
        it["sessions"] = len(it.pop("_s"))
    out_items = sorted(items.values(), key=lambda i: (KINDS.index(i["kind"]), -i["calls"], i["name"]))
    recent = sorted((s for s in sessions if s.listing), key=lambda s: (s.last or "", s.id), reverse=True)[:LISTING_SESSIONS]
    return {
        "schema": 1, "project": project,
        "looked_at": {"folders": list(folder_names), "left_out_other_projects": left_out, "sessions": len(sessions),
                      "subagent_files": counts["subagent_files"], "unreadable_lines": counts["unreadable_lines"],
                      "first": min((s.first for s in sessions if s.first), default=None),
                      "last": max((s.last for s in sessions if s.last), default=None)},
        "listing": [{"session": s.id, "skills": len(_listing_lines(s.listing)),
                     "skills_bytes": len(s.listing.encode("utf-8")),
                     "mcp_names_bytes": sum(len(n.encode("utf-8")) for n in (s.names or ()) if n.startswith("mcp__"))}
                    for s in recent],
        # null, not []: hooks ran and none names its plugin (the transcript keeps `${CLAUDE_PLUGIN_ROOT}` unexpanded), so
        # the cost per plugin was not measured; [] only when no session ran a SessionStart hook at all
        "plugins": ([{"plugin": p, "startup_bytes": b} for p, b in sorted(hooks_session.hooks.items())] or None) if hooks_session else [],
        "startup_unattributed": {"hooks": hooks_session.hook_n - hooks_session.hook_n_attr,
                                 "bytes": hooks_session.hook_bytes - sum(hooks_session.hooks.values())} if hooks_session else
                                {"hooks": 0, "bytes": 0},
        "unlisted_commands": dict(sorted(unlisted.items(), key=lambda kv: (-kv[1], kv[0]))),
        "items": out_items,
    }


def project_skill_names(project_path):
    """The skills under <project>/.claude/skills (a folder or a link to one)."""
    d = os.path.join(project_path, ".claude", "skills")
    try:
        return sorted(n for n in os.listdir(d) if os.path.isdir(os.path.join(d, n)))
    except OSError:
        return []


# --- init diff ---------------------------------------------------------------------------------------------

def _events(text):
    """The JSON values in a capture: one document, or one per line."""
    try:
        v = json.loads(text)
        return v if isinstance(v, list) else [v]
    except ValueError:
        out = []
        for line in text.splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except ValueError:
                    raise UsageError("not JSON")
        return out


def _names(v):
    out = set()
    for x in v if isinstance(v, list) else []:
        n = x if isinstance(x, str) else x.get("name") if isinstance(x, dict) else None
        if isinstance(n, str) and n:
            out.add(n)
    return out


def load_capture(path):
    """{"skills": set, "plugins": set, "mcp": set} of the first `system/init` event (or the first object that
    carries `skills`) in the file at `path`; UsageError when it cannot be read or holds no such event."""
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as e:
        raise UsageError("cannot read %s: %s" % (path, e.strerror or e))
    try:
        events = _events(text)
    except UsageError:
        raise UsageError("%s is not JSON" % path)
    init = next((e for e in events if isinstance(e, dict) and e.get("type") == "system" and e.get("subtype") == "init"), None)
    init = init or next((e for e in events if isinstance(e, dict) and "skills" in e), None)
    if init is None:
        raise UsageError("%s has no system/init event" % path)
    return {"skills": _names(init.get("skills")), "plugins": _names(init.get("plugins")),
            "mcp": _names(init.get("mcp_servers"))}


def load_answers(path):
    """{name: mark} for the marks `keep`, `drop` and `add` of the answers file."""
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except OSError as e:
        raise UsageError("cannot read %s: %s" % (path, e.strerror or e))
    except ValueError:
        raise UsageError("%s is not JSON" % path)
    if isinstance(doc, dict) and "answers" in doc:
        doc = doc["answers"]
    rows = doc if isinstance(doc, list) else [{"id": k, "answer": v} for k, v in doc.items()] if isinstance(doc, dict) else None
    if rows is None:
        raise UsageError("%s is neither a mapping nor a list of rows" % path)
    marks = {}
    for r in rows:
        if isinstance(r, dict):
            name, mark = r.get("id", r.get("name")), r.get("answer", r.get("mark"))
            if isinstance(name, str) and mark in ("keep", "drop", "add"):
                marks[name] = mark
    if not marks:
        raise UsageError("%s marks nothing keep, drop or add" % path)
    return marks


def count_line(label, cap):
    return "%s: %d skills, %d plugins, %d servers" % (label, len(cap["skills"]), len(cap["plugins"]), len(cap["mcp"]))


def init_diff(before, after, marks):
    """(exit code, lines): 0 and [] when the applied project is what the marks say, 1 and one line per fault,
    2 and one line when a capture is empty (looking at nothing is a failure, never a pass)."""
    for label, cap in (("before", before), ("after", after)):
        if not any(cap.values()):
            return 2, ["the %s capture lists no skills, plugins or servers" % label]
    b, a = (cap["skills"] | cap["plugins"] | cap["mcp"] for cap in (before, after))
    drop = {n for n, m in marks.items() if m == "drop"}
    keep = {n for n, m in marks.items() if m == "keep"}
    add = {n for n, m in marks.items() if m == "add"}
    lines = ["drop still in init: %s" % n for n in sorted(drop & a)]
    lines += ["drop not in before: %s" % n for n in sorted(drop - b)]
    lines += ["keep missing from init: %s" % n for n in sorted(keep - a)]
    lines += ["add missing from init: %s" % n for n in sorted(add - a)]
    lines += ["unexpected removal: %s" % n for n in sorted((b - a) - drop - keep)]
    lines += ["unexpected addition: %s" % n for n in sorted((a - b) - add)]
    return (1 if lines else 0), lines
