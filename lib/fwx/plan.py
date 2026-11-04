"""The plan files of a phase: `plan.md`, `premortem.md` and `postmortem.md` read, validated and checked for structure.

referent: pstack plugins/pstack/skills/poteto-mode/scripts/check-plan.mjs @36885ea (the code-fence logic of `section`,
reimplemented in Python); Every compound-engineering (the size bands). The rest is fwx's own: the file format is fixed by
the plan format, whose frontmatter is JSON between two `---` lines (JSON is YAML 1.2, so no YAML reader is needed).

What other parts import: PlanError, TAGS, TYPES, VERDICTS, BAND, read_frontmatter, load_plan, load_premortem,
load_postmortem, section, check_phase. A `load_*` takes the path of the file (not of the phase folder) and returns the
frontmatter as a dict, or raises PlanError for the first problem. `load_plan` does not look at what needs the whole folder:
two tasks of a wave writing the same file, a `part` above `size.parts` (the tasks of a subphase's plan carry the part
of the phase's task that owns them), or a subphase folder, are for `check_phase`, so a plan whose tasks clash still
loads and the caller (3.4's `prepare`) decides what to do with it.

Imports the standard library and `state` (for `read_rows`); nothing here needs the configuration or a git repository.
"""
import difflib
import json
import os
import re

from fwx import state

TAGS = ("small", "normal", "big")
TYPES = ("bug", "refactor", "feature")
VERDICTS = ("ok", "objections", "back-to-discuss")
REVIEWS = ("blocking", "async")
BAND = {"small": 4, "normal": 6, "big": 8}  # tasks per plan file (Every's bands)
CRITERIA = (2, 5)

_SUBPHASE = re.compile(r"\d+\.\d+-[^/\\]+\Z")
_OPEN_FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})(.*)$")
_CLOSE_FENCE = re.compile(r"^[ \t]*(`+|~+)[ \t]*$")
_DECISION = re.compile(r"D(\d+)\Z")


class PlanError(Exception):
    """A plan file the framework cannot use. `.path` is the file (or the label given to the loader), `.field` the field
    and `.reason` what is wrong; the text is `<path>: <field>: <reason>`."""

    def __init__(self, path, field, reason):
        self.path, self.field, self.reason = path, field, reason
        super().__init__("%s: %s: %s" % (path, field, reason))


# ---------------------------------------------------------------- reading

def _lines(path):
    """The lines of a file, without a BOM; a file that cannot be read is a PlanError."""
    try:
        with open(str(path), encoding="utf-8") as f:
            return f.read().lstrip("﻿").splitlines()
    except OSError as e:
        raise PlanError(path, "file", "cannot be read (%s)" % (e.strerror or e))
    except UnicodeDecodeError as e:
        raise PlanError(path, "file", "is not UTF-8 (%s)" % e.reason)


def _split(lines):
    """(frontmatter lines or None, index of the first body line)."""
    if not lines or lines[0].rstrip() != "---":
        return None, 0
    for i in range(1, len(lines)):
        if lines[i].rstrip() == "---":
            return lines[1:i], i + 1
    return None, 0


def read_frontmatter(path, label=None):
    """The frontmatter of a file: the JSON object between its first two `---` lines. PlanError when the file cannot be
    read, has no frontmatter, or the frontmatter is not a JSON object."""
    shown = label or path
    front, _ = _split(_lines(path))
    if front is None:
        raise PlanError(shown, "frontmatter", "missing (the file must open with a --- line, the JSON, and a closing --- line)")
    try:
        data = json.loads("\n".join(front))
    except ValueError as e:
        raise PlanError(shown, "frontmatter", "is not JSON (%s)" % e)
    if not isinstance(data, dict):
        raise PlanError(shown, "frontmatter", "is not a JSON object")
    return data


def _body(path):
    """[(line, in_code)] of the body: the lines after the frontmatter, each marked when it is inside a code fence. A fence
    opens with three or more backticks or tildes (a backtick fence cannot carry a backtick in its info text) and closes on
    a line of the same character, no fewer of them and nothing else; one never closed runs to the end of the file."""
    lines = _lines(path)
    _, start = _split(lines)
    fence, out = None, []
    for text in lines[start:]:
        if fence and (m := _CLOSE_FENCE.match(text)) and m.group(1)[0] == fence[0] and len(m.group(1)) >= fence[1]:
            out.append((text, True))
            fence = None
        elif fence:
            out.append((text, True))
        else:
            m = _OPEN_FENCE.match(text)
            if m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
                fence = (m.group(1)[0], len(m.group(1)))
            out.append((text, fence is not None))
    return out


def section(path, heading):
    """The text under `## <heading>` up to the next `## ` line, outside any code fence (a heading inside a fence is not
    one), with the blank lines at either end dropped. None when the heading is not there; an empty string when it is."""
    found, kept = False, []
    for text, code in _body(path):
        if not code and text.startswith("## "):
            if found:
                break
            found = text[3:].strip() == heading
            continue
        if found:
            kept.append(text)
    return "\n".join(kept).strip("\n") if found else None


# ---------------------------------------------------------------- validation

def _int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _text(v):
    return isinstance(v, str) and bool(v.strip())


class _Problems:
    """What a validator found, in file order: (field, reason) pairs."""

    def __init__(self):
        self.found = []

    def add(self, field, reason):
        self.found.append((field, reason))

    def unknown(self, obj, allowed, field):
        for k in obj:
            if k not in allowed:
                near = difflib.get_close_matches(k, allowed, n=1, cutoff=0.7)
                self.add(field + "." + k if field else k,
                         "unknown field%s" % (' (did you mean "%s"?)' % near[0] if near else ""))

    def value(self, obj, key, field, ok, what, required=True):
        """obj[key] when it passes `ok`, else None after recording why."""
        name = field + "." + key if field else key
        if key not in obj:
            if required:
                self.add(name, "missing")
            return None
        v = obj[key]
        if not ok(v):
            self.add(name, v == "" and "empty" or "must be %s" % what)
            return None
        return v

    def one_of(self, obj, key, field, options, required=True):
        return self.value(obj, key, field, lambda v: v in options and isinstance(v, str), "one of %s" % ", ".join(options), required)


def _object(p, obj, key, field, keys, required=True):
    sub = p.value(obj, key, field, lambda v: isinstance(v, dict), "an object", required)
    if sub is not None:
        p.unknown(sub, keys, field + "." + key if field else key)
    return sub


def _list(p, obj, key, field, required=True):
    v = p.value(obj, key, field, lambda v: isinstance(v, list), "a list", required)
    return v


def _reasons(p, items, field):
    """items: [{what, why}] with both texts non-empty."""
    for i, it in enumerate(items):
        name = "%s[%d]" % (field, i)
        if not isinstance(it, dict):
            p.add(name, "must be an object {what, why}")
            continue
        p.unknown(it, ("what", "why"), name)
        for k in ("what", "why"):
            p.value(it, k, name, _text, "a non-empty string")


def _plan_problems(data):
    p = _Problems()
    keys = ("size", "criteria", "tasks", "not_built", "later")
    p.unknown(data, keys, "")
    size = _object(p, data, "size", "", ("tag", "parts", "agents"))
    if size is not None:
        p.one_of(size, "tag", "size", TAGS)
        p.value(size, "parts", "size", lambda v: _int(v) and v >= 1, "an integer of at least 1")
        p.value(size, "agents", "size", lambda v: _int(v) and v >= 1, "an integer of at least 1")
    criteria = _list(p, data, "criteria", "")
    if criteria is not None:
        if not CRITERIA[0] <= len(criteria) <= CRITERIA[1]:
            p.add("criteria", "%d criteria, %d to %d required" % (len(criteria), *CRITERIA))
        for i, c in enumerate(criteria):
            name = "criteria[%d]" % i
            if not isinstance(c, dict):
                p.add(name, "must be an object {id, text, measure}")
                continue
            p.unknown(c, ("id", "text", "measure"), name)
            for k in ("id", "text", "measure"):
                p.value(c, k, name, _text, "a non-empty string")
    tasks = _list(p, data, "tasks", "")
    if tasks is not None:
        if not tasks:
            p.add("tasks", "empty")
        _tasks(p, tasks)
    for k in ("not_built", "later"):
        items = _list(p, data, k, "")
        if items is not None:
            _reasons(p, items, k)
    return p.found


def _tasks(p, tasks):
    ids = {}
    for i, t in enumerate(tasks):
        if isinstance(t, dict) and _text(t.get("id")) and isinstance(t["id"], str):
            ids.setdefault(t["id"], t)
    seen = set()
    for i, t in enumerate(tasks):
        tid = t.get("id") if isinstance(t, dict) and isinstance(t.get("id"), str) and t["id"].strip() else None
        name = "tasks[%s]" % (tid if tid else i)
        if not isinstance(t, dict):
            p.add(name, "must be an object")
            continue
        p.unknown(t, ("id", "part", "subphase", "type", "wave", "files", "depends_on", "tests", "size", "ui", "firefox", "review"), name)
        if p.value(t, "id", name, _text, "a non-empty string") is not None:
            if t["id"] in seen:
                p.add(name + ".id", "duplicate of an earlier task")
            seen.add(t["id"])
        p.value(t, "part", name, lambda v: _int(v) and v >= 1, "an integer of at least 1")
        p.value(t, "subphase", name, lambda v: isinstance(v, str) and bool(_SUBPHASE.match(v)),
                'a folder name like "03.1-slug"', required=False)
        ttype = p.one_of(t, "type", name, TYPES)
        wave = p.value(t, "wave", name, lambda v: _int(v) and v >= 1, "an integer of at least 1")
        files = _list(p, t, "files", name)
        if files is not None:
            if not files:
                p.add(name + ".files", "empty")
            for j, f in enumerate(files):
                if not _text(f):
                    p.add("%s.files[%d]" % (name, j), "must be a non-empty string")
        deps = _list(p, t, "depends_on", name)
        for d in deps or []:
            if not isinstance(d, str):
                p.add(name + ".depends_on", "%r is not a task id" % (d,))
            elif d not in ids:
                p.add(name + ".depends_on", "%s is not a task of this plan" % d)
            elif wave is not None and _int(ids[d].get("wave")) and ids[d]["wave"] >= wave:
                p.add(name + ".depends_on", "%s is in wave %d, not before wave %d" % (d, ids[d]["wave"], wave))
        p.one_of(t, "size", name, TAGS)
        ui = p.value(t, "ui", name, lambda v: isinstance(v, bool), "true or false")
        fx = p.value(t, "firefox", name, lambda v: isinstance(v, bool), "true or false", required=False)
        if fx and ui is False:
            p.add(name + ".firefox", "true needs ui: true")
        p.one_of(t, "review", name, REVIEWS, required=False)
        tests = _list(p, t, "tests", name)
        if tests is not None:
            if not tests and ttype in ("bug", "refactor") and ui is False:
                p.add(name + ".tests", "empty (a %s task with ui false needs a test)" % ttype)
            for j, test in enumerate(tests):
                tn = "%s.tests[%d]" % (name, j)
                if not isinstance(test, dict):
                    p.add(tn, "must be an object {run, measures, red}")
                    continue
                p.unknown(test, ("run", "measures", "red"), tn)
                for k in ("run", "measures", "red"):
                    p.value(test, k, tn, _text, "a non-empty string")


def _round_problems(data, keys, extra):
    p = _Problems()
    p.unknown(data, keys, "")
    p.one_of(data, "verdict", "", VERDICTS)
    p.value(data, "round", "", lambda v: _int(v) and v >= 1, "an integer of at least 1")
    extra(p, data)
    return p.found


def _premortem_extra(p, data):
    p.one_of(data, "size_tag", "", TAGS)
    p.value(data, "parts", "", lambda v: _int(v) and v >= 1, "an integer of at least 1")


def _postmortem_extra(p, data):
    p.value(data, "security_review", "", lambda v: isinstance(v, bool), "true or false")


def _premortem_problems(data):
    return _round_problems(data, ("verdict", "size_tag", "parts", "round"), _premortem_extra)


def _postmortem_problems(data):
    return _round_problems(data, ("verdict", "security_review", "round"), _postmortem_extra)


def _load(path, label, problems):
    data = read_frontmatter(path, label)
    found = problems(data)
    if found:
        raise PlanError(label or path, *found[0])
    return data


def load_plan(path, label=None):
    """The validated frontmatter of a `plan.md` (the path of the file). PlanError on the first problem; `label` is what
    the error shows instead of the path."""
    return _load(path, label, _plan_problems)


def load_premortem(path, label=None):
    """The validated frontmatter of a `premortem.md`: {verdict, size_tag, parts, round}."""
    return _load(path, label, _premortem_problems)


def load_postmortem(path, label=None):
    """The validated frontmatter of a `postmortem.md`: {verdict, security_review, round}."""
    return _load(path, label, _postmortem_problems)


def _problems_of(path, label, problems):
    """(data or None, [PlanError]): every problem of a file, for the checker."""
    try:
        data = read_frontmatter(path, label)
    except PlanError as e:
        return None, [e]
    return data, [PlanError(label or path, f, r) for f, r in problems(data)]


# ---------------------------------------------------------------- the phase

def _norm(f):
    f = f.strip()
    while f.startswith("./"):
        f = f[2:]
    return f.rstrip("/")


def _overlap(a, b):
    """The shared path of two declared paths when one is the other or lies inside the other (a folder), else None."""
    a, b = _norm(a), _norm(b)
    if a == b or b.startswith(a + "/"):
        return a
    if a.startswith(b + "/"):
        return b
    return None


def _clash(x, y):
    for a in x.get("files", []):
        for b in y.get("files", []):
            if isinstance(a, str) and isinstance(b, str) and (hit := _overlap(a, b)):
                return hit
    return None


def _tasks_of(data):
    t = data.get("tasks") if isinstance(data, dict) else None
    return [x for x in t if isinstance(x, dict) and isinstance(x.get("id"), str)] if isinstance(t, list) else []


def _clashes(label, data):
    out = []
    tasks = _tasks_of(data)
    for i, x in enumerate(tasks):
        for y in tasks[i + 1:]:
            if x.get("wave") == y.get("wave") and _int(x.get("wave")) and (hit := _clash(x, y)):
                out.append({"plan": label, "wave": x["wave"], "tasks": [x["id"], y["id"]], "file": hit})
    return out


def _wave_warnings(label, data, w):
    """A task that would fit in an earlier wave: every task it depends on is before that wave, and none of the tasks of
    that wave writes a file it writes."""
    tasks = [t for t in _tasks_of(data) if _int(t.get("wave"))]
    by_id = {t["id"]: t for t in tasks}
    for t in tasks:
        deps = [by_id[d]["wave"] for d in t.get("depends_on", []) if isinstance(d, str) and d in by_id]
        for earlier in range(max(deps, default=0) + 1, t["wave"]):
            if not any(o is not t and o["wave"] == earlier and _clash(t, o) for o in tasks):
                w.append("%s: tasks[%s].wave: could run in wave %d (its dependencies end earlier and no task there writes its files)"
                         % (label, t["id"], earlier))
                break


def _plan_warnings(label, data, w):
    size = data.get("size") if isinstance(data.get("size"), dict) else {}
    tasks = _tasks_of(data)
    tag = size.get("tag")
    if tag in BAND and len(tasks) > BAND[tag]:
        w.append("%s: tasks: %d tasks, the %s band is %d" % (label, len(tasks), tag, BAND[tag]))
    widest = max([sum(1 for t in tasks if t.get("wave") == n) for n in {t.get("wave") for t in tasks}], default=0)
    if _int(size.get("agents")) and tasks and size["agents"] != widest:
        w.append("%s: size.agents: %d, but the widest wave has %d task(s)" % (label, size["agents"], widest))
    _wave_warnings(label, data, w)


def _cited(folder, texts, w):
    """A decision with support chosen or approved, not replaced by a later one, that no plan text cites."""
    rows = state.read_rows(os.path.join(folder, "decisions.tsv"))
    replaced = {r.get("supersedes") for r in rows}
    for r in rows:
        i = r.get("id", "")
        if _DECISION.match(i) and r.get("support") in ("chosen", "approved") and i not in replaced \
                and not any(re.search(r"\b%s\b" % re.escape(i), t) for t in texts):
            w.append("plan.md: body: %s (%s) is not cited" % (i, r["support"]))


def _read_text(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return ""


def check_phase(dir):
    """The structure check of a phase folder: its `plan.md` and the `plan.md` of each subphase, plus the frontmatter of
    `premortem.md` and `postmortem.md` when they exist. Returns {errors, warnings, plans, tasks, waves, parts, clashes}:
    errors and warnings are lists of `<file>: <field>: <reason>` (the file relative to `dir`); plans, tasks and waves count
    what was read (waves per plan file, summed); parts is the phase's `size.parts` (0 when its plan cannot say);
    clashes lists {plan, wave, tasks, file} for two tasks of one wave that write the same path. The caller decides
    what an error means; a folder that is not one raises PlanError."""
    dir = str(dir)
    if not os.path.isdir(dir):
        raise PlanError(dir, "folder", "is not a folder")
    out = {"errors": [], "warnings": [], "plans": 0, "tasks": 0, "waves": 0, "parts": 0, "clashes": []}
    errors, warnings = out["errors"], out["warnings"]
    seen = {}  # label -> frontmatter, every plan file read

    def read(rel, problems):
        path = os.path.join(dir, rel)
        if not os.path.exists(path):
            return None
        data, found = _problems_of(path, rel, problems)
        errors.extend(str(e) for e in found)
        return data

    def count(rel, data):
        out["plans"] += 1
        seen[rel] = data
        if data is not None:
            tasks = _tasks_of(data)
            out["tasks"] += len(tasks)
            out["waves"] += len({t.get("wave") for t in tasks if _int(t.get("wave"))})
            out["clashes"].extend(_clashes(rel, data))

    plan = read("plan.md", _plan_problems)
    if not os.path.exists(os.path.join(dir, "plan.md")):
        errors.append("plan.md: file: missing")
    else:
        count("plan.md", plan)
        size = plan.get("size") if isinstance(plan, dict) and isinstance(plan.get("size"), dict) else {}
        parts = size.get("parts") if _int(size.get("parts")) else 0
        out["parts"] = parts
        for t in _tasks_of(plan):
            if _int(t.get("part")) and parts and t["part"] > parts:
                errors.append("plan.md: tasks[%s].part: %d is above size.parts %d" % (t["id"], t["part"], parts))
        if parts > 1:
            subs = {}
            for t in _tasks_of(plan):
                sub = t.get("subphase")
                if not isinstance(sub, str) or not _SUBPHASE.match(sub):
                    if "subphase" not in t:
                        errors.append("plan.md: tasks[%s].subphase: missing (size.parts is %d, each task is a subphase)" % (t["id"], parts))
                    continue
                if not os.path.isdir(os.path.join(dir, sub)):
                    errors.append("plan.md: tasks[%s].subphase: %s has no folder" % (t["id"], sub))
                    continue
                subs.setdefault(sub, []).append(t)
            for sub, owners in sorted(subs.items()):
                rel = sub + "/plan.md"
                data = read(rel, _plan_problems)
                if not os.path.exists(os.path.join(dir, rel)):
                    errors.append("%s: file: missing" % rel)
                    continue
                count(rel, data)
                parts_of = {o.get("part") for o in owners}
                for t in _tasks_of(data):
                    if t.get("part") not in parts_of:
                        errors.append("%s: tasks[%s].part: %s, but the phase's task %s is part %s"
                                      % (rel, t["id"], t.get("part"), owners[0]["id"], owners[0].get("part")))
    premortem = read("premortem.md", _premortem_problems)
    read("postmortem.md", _postmortem_problems)
    for c in out["clashes"]:
        errors.append("%s: waves[%d].files: %s and %s both write %s" % (c["plan"], c["wave"], c["tasks"][0], c["tasks"][1], c["file"]))
    for rel, data in seen.items():
        if data is not None:
            _plan_warnings(rel, data, warnings)
    if isinstance(premortem, dict) and isinstance(seen.get("plan.md"), dict) and not _premortem_problems(premortem):
        size = seen["plan.md"].get("size") if isinstance(seen["plan.md"].get("size"), dict) else {}
        for field, mine, theirs in (("size.tag", size.get("tag"), premortem["size_tag"]), ("size.parts", size.get("parts"), premortem["parts"])):
            if mine != theirs:
                warnings.append("plan.md: %s: %s, but premortem.md says %s" % (field, mine, theirs))
    if isinstance(seen.get("plan.md"), dict):
        _cited(dir, [_read_text(os.path.join(dir, rel)) for rel in seen], warnings)
    from fwx import plan_form  # here, not at the top: plan_form imports this module
    plan_form.check(dir, seen, out)
    return out
