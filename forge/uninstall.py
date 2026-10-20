"""forge uninstall: take out of this machine what forge wrote, and nothing else.

What is forge's comes from two places. The ownership record (forge/owned.py) names each value a writer put
in a file, by its digest: a claim whose value is still exactly that is removed (an item from its list, a key
from its object, a hook entry, a file or link; a list, object, hook group or event it leaves empty goes with
it, and a settings.local.json or ~/.codex/hooks.json left as {} is deleted, never ~/.claude.json or
~/.claude/settings.json); one edited since is the user's, stays, and is named on a '  ! ' line. No value is
restored: a key forge set falls back to Claude Code's default. The rest is forge's by construction and needs
no claim: the links in ~/.claude/skills and $CODEX_HOME/skills that resolve into <forge>/skills/ (never their
target), a project's .agents/skills links (skills._agents_link), the guard entries of a settings.local.json
(skills._runs_forge_guard), the copy of AGENT-SYSTEM.md and the pointer block sync_system_doc.py writes,
~/.gsd/defaults.json while it is forge's copy, ~/.cache/forge/, this checkout's SessionStart row when the
record does not hold it, and last the state directory, the record with it.

Scopes: everything (the default), with forge's SessionStart row second-to-last and the state directory last,
both only when nothing before them failed; `--integration N`, refused while N is on in config/forge.json:
N's claims and what N has by construction; `--project N`, refused unless the profile is frozen or gone: what
lies under its project_path and its part of ~/.claude.json. A dry-run unless --apply, and a dry-run writes
nothing at all; --apply writes through lib (lib.may_write) under lib.lock, ~/.claude.json only when nobody
wrote it since it was read. It never reads config/secrets.json or credentials/: it decides by digests.
An ownership record that cannot be read stops every scope (exit 1, the record stays for repair); no record at
all is "only what forge makes by construction", and a whole uninstall that finds nothing says nothing is left
(exit 0). `--project N` leaves what lies under another profile's project_path inside N's. A link where a
directory was (~/.cache/forge, the state directory) is removed as a link; a settings.local.json or hooks.json
that is a link and is left empty is written through, never unlinked.

Left in place and said: GSD's agents and engine in ~/.claude (the command that removes them is printed), a
.bak older than the record, and the checkout itself (the command that deletes it is printed, never run)."""
import collections
import importlib.util
import json
import os
import re
import shutil
import sys

from forge import hooks, lib, mcp, owned, skills

USER_SETTINGS = os.path.join(lib.HOME, ".claude", "settings.json")
CLAUDE_JSON = os.path.join(lib.HOME, ".claude.json")
CODEX_HOOKS = os.path.join(lib.CODEX_HOME, "hooks.json")
HINDSIGHT = os.path.join(lib.HOME, ".hindsight", "coding-agent.json")
GSD_DEFAULTS = os.path.join(lib.HOME, ".gsd", "defaults.json")
CACHE = os.path.join(lib.HOME, ".cache", "forge")
SKILL_DIRS = {"claude": os.path.join(lib.HOME, ".claude", "skills"), "codex": os.path.join(lib.CODEX_HOME, "skills")}
GSD_REMOVE = "npx get-shit-done-cc@latest --claude --global --uninstall"
SLP = os.path.join(".claude", "settings.local.json")


def _system_doc():
    """scripts/sync/sync_system_doc.py as a module, for its banner, its canonical doc and its markers. It reads
    its argv when imported (lib.context), so it is imported with none: a dry-run context, which writes nothing."""
    p = os.path.join(lib.ROOT, "scripts", "sync", "sync_system_doc.py")
    spec = importlib.util.spec_from_file_location("forge_system_doc", p)
    mod = importlib.util.module_from_spec(spec)
    argv, sys.argv = sys.argv, [p]
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.argv = argv
    return mod


def _inside(p, d):
    return p == d or p.startswith(d + os.sep)


def _session_start(cmd):
    """Whether hook command `cmd` runs this checkout's `forge session-start`, with whatever else it says
    (lib.installed_root's reading, with an end: `session-start-audit` is another command)."""
    m = re.search(r"(\S+)/bin/forge session-start(?:\s|$)", cmd) if isinstance(cmd, str) else None
    return bool(m) and os.path.realpath(m.group(1)) == os.path.realpath(lib.ROOT)


def _session_row():
    """The command of the SessionStart row this checkout writes (hooks.USER_HOOKS), byte for byte."""
    return next((row[1] for row in hooks.USER_HOOKS if row[3] == "forge session-start"), None)


def _get(doc, path):
    for k in path:
        doc = doc[k]
    return doc


def _prune(doc, path):
    """Take out the list or object at `path` while this run has left it empty, and each parent it empties in
    turn; the document itself stays (the caller decides about the file)."""
    while path:
        node = _get(doc, path)
        if not isinstance(node, (dict, list)) or node:
            return
        del _get(doc, path[:-1])[path[-1]]
        path = path[:-1]


def _drop_entries(doc, event, drop):
    """Take out of doc["hooks"][event] every entry for which drop(group, entry) holds; a group, the event and
    `hooks` left empty go with them. Returns how many went."""
    groups = doc["hooks"][event]
    n = 0
    for g in list(groups):
        if not (isinstance(g, dict) and isinstance(g.get("hooks"), list)):
            continue
        kept = [h for h in g["hooks"] if not (isinstance(h, dict) and drop(g, h))]
        if len(kept) != len(g["hooks"]):
            n += len(g["hooks"]) - len(kept)
            g["hooks"] = kept
            if not kept:
                groups[:] = [x for x in groups if x is not g]
    if n:
        _prune(doc, ["hooks", event])
    return n


def _hook_entries(doc):
    """Every well-formed hook entry of doc["hooks"], whatever its event."""
    events = doc.get("hooks")
    return [h for groups in (events.values() if isinstance(events, dict) else []) if isinstance(groups, list)
            for g in groups if isinstance(g, dict) and isinstance(g.get("hooks"), list)
            for h in g["hooks"] if isinstance(h, dict)]


def _drop_hooks(doc, drop):
    """_drop_entries over every event that is a list."""
    events = doc.get("hooks")
    if not isinstance(events, dict):
        return 0
    return sum(_drop_entries(doc, event, drop) for event in list(events) if isinstance(events.get(event), list))


class Run:
    """One uninstall: what it loaded, what it will write, what it said. Every file is read once, changed in
    memory and written (or deleted) once, at commit."""

    def __init__(self, apply):
        self.apply, self.files, self.failed, self.changes = apply, {}, False, []

    def say(self, line):
        print(line, flush=True)

    def fail(self, line):
        self.failed = True
        self.say("  ! " + line)

    def verb(self, what):
        return what if self.apply else "would " + what

    def json(self, path):
        """The JSON object at `path`, loaded once, or None when there is none; lib.Unreadable for one that
        cannot be read, which is never written."""
        if path not in self.files:
            mtime = os.stat(path).st_mtime_ns if os.path.exists(path) else None
            doc = lib.read_owned(path, None)
            self.files[path] = {"kind": "json", "doc": doc, "was": lib.dumps(doc), "mtime": mtime}
        return self.files[path]["doc"]

    def text(self, path):
        if path not in self.files:
            try:
                with open(path, encoding="utf-8", newline="") as fh:
                    text = fh.read()
            except FileNotFoundError:
                text = None
            except (OSError, UnicodeDecodeError) as e:
                raise lib.Unreadable(path, str(e)) from e
            self.files[path] = {"kind": "text", "doc": text, "was": text}
        return self.files[path]["doc"]

    def set_text(self, path, text):
        self.files[path]["doc"] = text

    def delete(self, path, tree=False):
        self.files[path] = {"kind": "tree" if tree else "delete"}

    def commit(self):
        """Write or delete every file changed in memory; nothing for a dry-run. Returns nothing: a file that
        could not be written is a '!' line and the run fails."""
        files, self.files = self.files, {}
        if not self.apply:
            return
        for path, f in files.items():
            if f["kind"] == "tree":
                if os.path.islink(path):  # a link to a directory goes as a link, its target stays
                    lib.unlink(path)
                    self.changes.append(("unlink", path))
                elif os.path.isdir(path):
                    try:
                        shutil.rmtree(path)
                    except OSError as e:
                        self.fail("%s could not be removed (%s)" % (lib.short(path), e))
                        continue
                    lib.record("rmtree", path)
                    self.changes.append(("rmtree", path))
                continue
            if f["kind"] != "delete" and (f["doc"] is None or (lib.dumps(f["doc"]) if f["kind"] == "json" else f["doc"]) == f["was"]):
                continue  # not changed by this run
            # Left empty by this run: a settings.local.json or ~/.codex/hooks.json at {}, a text file with nothing in it.
            emptied = (f["doc"] == {} and (path.endswith(os.sep + SLP) or path == CODEX_HOOKS) if f["kind"] == "json"
                       else f["kind"] == "text" and not f["doc"].strip())
            if f["kind"] == "delete" or (emptied and not os.path.islink(path)):  # an emptied link is written through
                if os.path.lexists(path):
                    lib.unlink(path)
                    self.changes.append(("unlink", path))
                continue
            if f["kind"] == "json":
                if path == CLAUDE_JSON and os.path.exists(path) and os.stat(path).st_mtime_ns != f["mtime"]:
                    # Every open Claude Code session writes this file too (mcp.ClaudeJson.commit's rule).
                    self.fail("%s changed by another process while uninstalling; not written, run it again" % lib.short(path))
                    continue
                lib.write_json(path, f["doc"], mode="keep")
            else:
                lib.write_text(path, f["doc"], mode="keep")
            self.changes.append(("wrote", path))


class Scope:
    """Which claims and which by-construction items a run takes: everything, an integration's, a project's."""

    def __init__(self, a, claims):
        self.integration, self.project = a.integration, a.project
        self.whole = not (a.integration or a.project)
        self.name = "integration " + a.integration if a.integration else "project " + a.project if a.project else "everything"
        self.refusal = None
        profs = lib.profiles()
        if a.integration and lib.on(a.integration):
            self.refusal = "%s is on in config/forge.json: set it false first" % a.integration
        prof = profs.get(a.project) if a.project else None
        if prof is not None and not prof.get("frozen"):
            self.refusal = ("%s is a live profile, which the next forge sync writes again: set \"frozen\": true in "
                            "config/profiles/%s.claude.json, or delete it, first" % (a.project, a.project))
        if a.project and prof is None:  # gone: its paths are where its claims are
            keys = {c["part"][len("mcp:"):] for cs in (claims or {}).values() for c in cs
                    if c["owner"] == a.project and c.get("part", "").startswith("mcp:")}
            dirs = {os.path.dirname(os.path.dirname(f)) for f, cs in (claims or {}).items()
                    if f.endswith(os.sep + SLP) and any(c["owner"] == a.project for c in cs)}
            self.ppaths = sorted(keys | dirs)
        elif a.project:
            self.ppaths = [os.path.normpath(prof["project_path"])] if prof.get("project_path") else []
        else:
            self.ppaths = sorted({os.path.normpath(p["project_path"]) for p in profs.values() if p.get("project_path")})
        if a.project and not self.ppaths and not self.refusal:
            self.refusal = "%s: no profile with a project_path and no claim of it in the record" % a.project
        self.real = [os.path.realpath(p) for p in self.ppaths]
        # Another profile's tree inside this project's is its own: a path belongs to the longest project_path.
        others = {os.path.realpath(p["project_path"]) for n, p in profs.items() if n != a.project and p.get("project_path")}
        self.nested = [o for o in others if any(o != d and _inside(o, d) for d in self.real)] if a.project else []
        self.keys = {"mcp:" + mcp.project_key(p) for p in self.ppaths}

    def has(self, *what):
        """Whether a by-construction item belonging to any of `what` (whole, codex, gsd, project) is in scope."""
        return (self.whole and "whole" in what) or (self.integration in what) or (bool(self.project) and "project" in what)

    def under(self, path):
        d = os.path.realpath(os.path.dirname(path))
        return any(_inside(d, p) for p in self.real) and not any(_inside(d, n) for n in self.nested)

    def _takes(self, file, c):
        if self.whole:
            return True
        if self.project:
            return self.under(file) or (file == CLAUDE_JSON and c.get("part") in self.keys)
        return c["owner"] == self.integration or (self.integration == "codex" and (file == CODEX_HOOKS or c.get("part") == "skills"))

    def select(self, claims):
        """[(file, claim)] in scope, in the record's order. A claimed .bak goes with its file when every claim of
        that file is in scope (a project's: when it lies under the project)."""
        out = [(f, c) for f, cs in claims.items() for c in cs if c.get("part") != "bak" and self._takes(f, c)]
        taken = collections.Counter(f for f, _ in out)
        for f, cs in claims.items():
            for c in cs:
                if c.get("part") != "bak":
                    continue
                base = f[:-len(".bak")]
                whole_file = base in claims and taken.get(base) == sum(1 for x in claims[base] if x.get("part") != "bak")
                if self.whole or (self.under(f) if self.project else whole_file and taken.get(base)):
                    out.append((f, c))
        return out


def _found(run, file, c):
    """owned.current over the run's loaded copy of `file`."""
    if c["kind"] == "file":
        if file in run.files:  # already deleted by this run
            return False, None
        return owned.current(file, c)
    if c["kind"] == "item" and c["at"][:1] == ["line"]:
        text = run.text(file)
        return (False, None) if text is None else owned.current(file, c, text)
    doc = run.json(file)
    return (False, None) if doc is None else owned.current(file, c, doc)


def _take_out(run, file, c):
    """Remove claim `c`, found and unchanged, from the run's copy of `file`."""
    kind, at = c["kind"], c["at"]
    if kind == "file":
        run.delete(file)
    elif kind == "item" and at[:1] == ["line"]:
        lines = run.text(file).splitlines(keepends=True)
        run.set_text(file, "".join(l for l in lines if l.strip() != at[1]))
    elif kind == "hook":
        doc = run.json(file)
        event, matcher, cmd = (at[1], None, at[2]) if at[0] == "hooks" else at
        _drop_entries(doc, event, lambda g, h: h.get("command") == cmd and (at[0] == "hooks" or g.get("matcher") == matcher)
                      and owned.removable(c, h))
    else:
        doc = run.json(file)
        parent = _get(doc, at[:-1])
        if kind == "item":
            parent[:] = [v for v in parent if v != at[-1]]
        else:
            del parent[at[-1]]
        _prune(doc, at[:-1])


def _claims(run, chosen):
    """Take out every claim of `chosen` whose value is unchanged; name each edited one. Returns the claims
    handled (removed, edited or already gone), which leave the record."""
    handled, by_file = [], {}
    for f, c in chosen:
        by_file.setdefault(f, []).append(c)
    for f, cs in by_file.items():
        removed = gone = 0
        try:
            for c in cs:
                found, value = _found(run, f, c)
                if not found:
                    gone += 1
                elif not owned.removable(c, value):
                    run.say("  ! %s %s was edited, left in place" % (lib.short(f), json.dumps(c["at"], ensure_ascii=False)))
                else:
                    _take_out(run, f, c)
                    removed += 1
                handled.append((f, c))
        except lib.Unreadable as e:
            run.fail("%s could not be read (%s): its claims are left in place" % (lib.short(f), e.reason))
            continue
        if removed or gone:
            run.say("   %s -> %s %d claim(s)%s" % (lib.short(f), run.verb("remove"), removed,
                                                   ", %d already gone" % gone if gone else ""))
    return handled


def _by_construction(run, scope):
    """What forge made that needs no claim, in scope. Returns how many items it found."""
    n = 0
    forge_skills = os.path.realpath(os.path.join(lib.ROOT, "skills"))
    for agent, d in SKILL_DIRS.items():
        if not scope.has("whole", agent) or not os.path.isdir(d):
            continue
        links = [os.path.join(d, x) for x in sorted(os.listdir(d))]
        links = [p for p in links if os.path.islink(p) and _inside(os.path.realpath(p), forge_skills)]
        for p in links:
            run.delete(p)
        if links:
            run.say("   %s -> %s %d link(s) into forge's skills/" % (lib.short(d), run.verb("remove"), len(links)))
        n += len(links)
    doc_mod = _system_doc() if scope.has("whole", "project") else None
    for pp in scope.ppaths:
        if scope.has("whole", "codex", "project"):
            d = os.path.join(pp, ".agents", "skills")
            links = [x for x in (sorted(os.listdir(d)) if os.path.isdir(d) else [])
                     if os.path.islink(os.path.join(d, x)) and os.readlink(os.path.join(d, x)) == skills._agents_link(x)]
            for x in links:
                run.delete(os.path.join(d, x))
            if links:
                run.say("   %s -> %s %d link(s)" % (lib.short(d), run.verb("remove"), len(links)))
            n += len(links)
        if doc_mod is None:
            continue
        n += _project_files(run, pp, doc_mod)
    if scope.has("whole", "gsd") and os.path.lexists(GSD_DEFAULTS):
        n += 1
        src = os.path.join(lib.ROOT, "config", "gsd", "defaults.json")
        if not os.path.islink(GSD_DEFAULTS) and os.path.isfile(src) and lib.holds(GSD_DEFAULTS, _read(src)):
            run.delete(GSD_DEFAULTS)
            run.say("   %s -> %s" % (lib.short(GSD_DEFAULTS), run.verb("remove")))
        else:
            run.say("  ! %s is not forge's copy of config/gsd/defaults.json, left in place" % lib.short(GSD_DEFAULTS))
    cache = CACHE if scope.whole else os.path.join(CACHE, "gsd-stage") if scope.integration == "gsd" else None
    if cache and os.path.isdir(cache):
        n += 1
        run.delete(cache, tree=True)
        run.say("   %s -> %s" % (lib.short(cache), run.verb("remove")))
    return n


def _read(p):
    with open(p, encoding="utf-8", newline="") as fh:
        return fh.read()


def _project_files(run, pp, doc_mod):
    """A project's guard entries, its copy of AGENT-SYSTEM.md and its pointer block. Returns how many it found."""
    n = 0
    slp = os.path.join(pp, SLP)
    try:
        doc = run.json(slp)
    except lib.Unreadable as e:
        run.fail("%s could not be read (%s): its guard entries are left in place" % (lib.short(slp), e.reason))
        doc = None
    if doc is not None:
        scripts = [row[0] for row in skills.GUARDS]
        k = _drop_hooks(doc, lambda g, h: any(skills._runs_forge_guard(h.get("command"), s) for s in scripts))
        if k:
            run.say("   %s -> %s %d guard entry(ies)" % (lib.short(slp), run.verb("remove"), k))
        n += k
    copy = os.path.join(pp, ".claude", "AGENT-SYSTEM.md")
    if os.path.lexists(copy):
        n += 1
        try:
            ours = not os.path.islink(copy) and lib.holds(copy, doc_mod.GEN_BANNER + _read(doc_mod.CANON))
        except OSError as e:
            run.fail("%s left in place: %s cannot be read (%s), so the copy cannot be compared" % (lib.short(copy), lib.short(doc_mod.CANON), e.strerror))
        else:
            if ours:
                run.delete(copy)
                run.say("   %s -> %s" % (lib.short(copy), run.verb("remove")))
            else:
                run.say("  ! %s is not the copy forge writes, left in place" % lib.short(copy))
    md = os.path.join(pp, "CLAUDE.md")
    try:
        text = None if os.path.islink(md) else run.text(md)
    except lib.Unreadable:
        text = None
    if text is not None and (doc_mod.BEGIN in text or doc_mod.END in text):
        n += 1
        b, e = text.find(doc_mod.BEGIN), text.find(doc_mod.END)
        if (text.count(doc_mod.BEGIN), text.count(doc_mod.END)) != (1, 1) or e < b:  # forge writes exactly one pair
            run.say("  ! %s: the markers are not one BEGIN then one END, left in place" % lib.short(md))
        else:
            head, tail = text[:b].rstrip("\n"), text[e + len(doc_mod.END):].lstrip("\n")
            new = head + ("\n\n" if head and tail else "\n" if head else "") + tail
            run.set_text(md, new)
            run.say("   %s -> %s the pointer block%s" % (lib.short(md), run.verb("remove"),
                                                       "; the file is left empty and goes" if not new.strip() else ""))
    return n


def _old_baks(scope, claims):
    """The .bak files beside what forge writes with a once-ever backup that the record does not claim."""
    bases = []
    if scope.has("whole"):
        bases += [CLAUDE_JSON, USER_SETTINGS]
    if scope.has("whole", "codex"):
        bases.append(CODEX_HOOKS)
    if scope.has("whole", "hindsight"):
        bases.append(HINDSIGHT)
    for pp in scope.ppaths:
        if scope.has("whole", "project"):
            bases.append(os.path.join(pp, SLP))
        if scope.has("whole", "codex", "project"):
            bases.append(os.path.join(pp, ".codex", "config.toml"))
    claimed = {f for f, cs in (claims or {}).items() if any(c.get("part") == "bak" for c in cs)}
    out = []
    for b in bases:
        bak = os.path.realpath(b) + ".bak"
        if os.path.lexists(bak) and bak not in claimed and bak not in out:
            out.append(bak)
    return out


def _last(run, scope, deferred):
    """forge's SessionStart row in ~/.claude/settings.json: through its claim when the record holds it, else by
    its exact command; a row that runs forge's session-start with anything changed is the user's, and named.
    Returns how many items it found by construction (0 or 1)."""
    if deferred:
        _claims(run, deferred)
    try:
        doc = run.json(USER_SETTINGS)
    except lib.Unreadable as e:
        if not deferred:  # the claims above named it
            run.fail("%s could not be read (%s): forge's SessionStart row is left in place" % (lib.short(USER_SETTINGS), e.reason))
        return 0
    row = _session_row()
    k = 0 if deferred or doc is None or row is None else _drop_hooks(doc, lambda g, h: h.get("command") == row)
    if k:
        run.say("   %s -> %s forge's SessionStart row" % (lib.short(USER_SETTINGS), run.verb("remove")))
    if doc is not None and any(_session_start(h.get("command")) for h in _hook_entries(doc)):
        run.say("  ! %s: a SessionStart row that runs forge's session-start was edited, left in place" % lib.short(USER_SETTINGS))
    run.commit()
    return 1 if k else 0


def _record():
    """(claims, warning): the ownership record's claims, None when there is no record to go by."""
    claims, warn = owned.load()
    return (None if warn or not os.path.exists(owned.path()) else claims), warn


def _plan(a):
    """(scope, claims, lines): what the record and the arguments allow, and the '!' lines that stop the run."""
    claims, warn = _record()
    scope = Scope(a, claims)
    if scope.refusal:
        return scope, claims, ["  ! " + scope.refusal]
    if warn:  # nothing is known of what forge wrote: the record stays for repair, not deleted with the state directory
        return scope, claims, [warn, "  ! the record is kept: repair it, or delete it to uninstall only what forge makes by construction"]
    return scope, claims, []


def main(a):
    """forge uninstall [--integration N | --project N] [--apply]: 0, or 1 on a FAIL or a refusal."""
    scope, claims, stop = _plan(a)
    print("forge uninstall: %s (%s)" % (scope.name, "APPLY" if a.apply else "dry-run: nothing is written; --apply removes"), flush=True)
    if not stop and a.apply:
        ok, why = lib.may_write()
        stop = [] if ok else ["  ! " + why]
    if stop:
        print("\n".join(stop))
        return 1
    run = Run(a.apply)
    had_state = os.path.isdir(lib.STATE)  # before lib.lock, which makes it
    if not a.apply:
        return _uninstall(run, scope, claims, had_state)
    with lib.lock():
        scope, claims, stop = _plan(a)  # the record as a sync that ran before the lock left it
        if stop:
            print("\n".join(stop))
            return 1
        return _uninstall(run, scope, claims, had_state)


def _uninstall(run, scope, claims, had_state):
    if claims is None:
        run.say("== claims == NOT RUN, NOT ARMED: no ownership record (%s); only what forge makes by construction"
                % lib.short(owned.path()))
        chosen = []
    else:
        run.say("== claims (%s) ==" % lib.short(owned.path()))
        chosen = scope.select(claims)
    deferred = [(f, c) for f, c in chosen
                if scope.whole and f == USER_SETTINGS and c["kind"] == "hook" and _session_start(c["at"][-1])]
    handled = _claims(run, [x for x in chosen if x not in deferred])
    run.say("== made by construction ==")
    items = _by_construction(run, scope)
    run.commit()
    if claims is not None and not (scope.whole and not run.failed) and handled and run.apply:
        gone = {id(c) for _, c in handled}
        for f in dict.fromkeys(f for f, _ in handled):
            owned.record(f, [c for c in claims[f] if id(c) not in gone], True)
    if scope.whole and run.failed:
        run.say("  ! forge's SessionStart row and %s stay while something above failed: run it again once that is fixed"
                % lib.short(lib.STATE))
    elif scope.whole:
        run.say("== last ==")
        items += _last(run, scope, deferred) + had_state
    lib.journal(run.changes, "uninstall", scope.name)  # nothing for a dry-run, which changes nothing
    if scope.whole and not run.failed and os.path.isdir(lib.STATE):
        run.delete(lib.STATE, tree=True)
        if had_state:  # else the run's own lock made it
            run.say("   %s -> %s" % (lib.short(lib.STATE), run.verb("remove")))
        run.commit()
    baks = _old_baks(scope, claims)
    if baks:
        run.say(".bak files older than the record, left in place:")
        for b in baks:
            run.say("   " + lib.short(b))
    run.say("looked at %d claim(s) and %d item(s) forge made by construction" % (len(chosen), items))
    if claims is None and not items:
        if not (scope.whole and not run.failed):
            run.say("FAIL: looked at zero: no ownership record and nothing forge made by construction")
            return 1
        run.say("nothing left of forge on this machine: no ownership record, no state directory, nothing made by construction")
    if scope.whole or scope.integration == "gsd":
        run.say("GSD's agents and engine stay installed in ~/.claude; to remove them: " + GSD_REMOVE)
    if scope.whole:
        run.say("To delete the forge checkout itself (never run by forge): rm -rf %s" % lib.ROOT)
    return 1 if run.failed else 0
