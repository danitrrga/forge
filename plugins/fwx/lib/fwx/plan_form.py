"""The form of the plan files and what a script can check in them: the second half of `fwx plan lint`.

referent: pstack plugins/pstack/skills/poteto-mode/scripts/check-plan.mjs @36885ea (the headings in order, the intro under ten
lines, the code-fence logic) and the plan-form prototype (history, undefined ids, `file:line` cites, a budget). pstack's prose
style rules (dashes, quotes, colons), lanes, perf boxes and appendices are not adopted: they belong to its program format.

`plan.check_phase` calls `check(dir, seen, out)` once, after the structure checks: `seen` is {file relative to `dir`: frontmatter
or None} of every plan file it read (`plan.md` and the `plan.md` of each subphase), `out` its result, to which this adds
errors and warnings as `<file>: <field>: <reason>`. A plan file whose frontmatter did not load is left alone here: its
structure error is the one to fix first. Everything is an error but the first budget step.

Per plan file: `## Goal` then `## Approach`; a `## Goal` of fewer than ten non-empty lines and 150 words; no edit history (git is
the history); no `T<n>`, `C<n>` or `D<n>` in the prose that `tasks`, `criteria` or `decisions.tsv` does not define; every
`` `file:line` `` cite points at a file with that line (in the phase folder or the main checkout); the body under 3600 words
(a warning) and 4800 (an error); a non-empty `## Size` when the plan exceeds its band or differs from `premortem.md`.
`premortem.md`: `## Verdict`, `## Failure reasons`, `## Size`, and the verdict matches the failure reasons listed. `postmortem.md`:
its six headings; each finding (a list item under `## Findings`) has a severity and an `evidence:` field, a blocker or warning
with `unproven` evidence is an error, and the verdict matches the findings; `security_review` is true when a task writes a file
that `project.protected_paths` covers.

Length is counted in words, not lines: a cap in lines is passed by one long line. The two figures are 12 words to the line of the
300 and 400 lines the plan format first named (no measurement behind them yet); `## Goal` also keeps its ten lines, which is the
shape it must have, with a word cap beside it for the same reason.

What cannot run says so: a cite with no main checkout to look in, and a protected-path check with no configuration, give a
`NOT RUN, NOT ARMED` warning (neither a pass nor an error). A cite or a protected path the plan does not have is nothing to look at
and gives nothing.

Imports the standard library, `config`, `plan` and `core.globs`; the checks that need git or the configuration reach them only when
a cite or a task asks.
"""
import os
import re

from fwx import config, plan, state
from fwx.core import globs

HEADINGS = {
    "plan.md": ("Goal", "Approach"),
    "premortem.md": ("Verdict", "Failure reasons", "Size"),
    "postmortem.md": ("Verdict", "Findings", "Criteria", "Checked", "Needs from the owner before executing", "Not found wrong"),
}
GOAL_LINES, GOAL_WORDS = 10, 150   # a Goal of this many non-empty lines, or more words, is an error
WORDS_WARN, WORDS_ERROR = 3600, 4800
SEVERITIES = ("blocker", "warning", "info")

_HISTORY = re.compile(r"(?:Ajustado el|Revisado el|Adjusted on)\s+(?:\d{4}-\d{2}-\d{2}|\d{1,2}[/.]\d{1,2}[/.]\d{2,4})", re.I)
_ID = re.compile(r"(?<![\w/.:])([TCD]\d+)(?![\w/]|\.\w)")
_CITE = re.compile(r"`([\w./-]+\.(?:md|py|mjs|js|ts|tsx|jsx|json|sh|txt|toml|tsv|yml|yaml|html|css|sql|rs|go|rb|java|c|h|cpp|ini|cfg)):(\d+)(?:-(\d+))?`")
_ITEM = re.compile(r"^(\s*)(?:[-*+]|\d+[.)])\s+(.*)$")
_SEVERITY = re.compile(r"^[\s*_\[(]*(blocker|warning|info)\b", re.I)
_EVIDENCE = re.compile(r"\bevidence:\s*(.*?)\s*(?:/\s*(?:owner|hint):|\Z)", re.I | re.S)
_NONE = re.compile(r"\W*none\W*\Z", re.I)


def _scan(path):
    """(body lines [(text, in_code)], {heading: [lines under it]}, [headings in order]) of a file; the first of two equal
    headings wins; None when the file cannot be read."""
    try:
        body = plan._body(path)
    except plan.PlanError:
        return None
    sections, order, kept = {}, [], None
    for text, code in body:
        if not code and text.startswith("## "):
            name = text[3:].strip()
            order.append(name)
            kept = sections.setdefault(name, []) if name not in sections else None
        elif kept is not None:
            kept.append((text, code))
    return body, sections, order


def _items(lines):
    """The list items of a section, outside code fences: the text of each, continuation lines and deeper items included.
    An item whose text is `None` is no item."""
    items, base = [], None
    for text, code in lines:
        if code or not text.strip():
            continue
        m = _ITEM.match(text)
        if m and (base is None or len(m.group(1)) <= base):
            base = len(m.group(1)) if base is None else base
            items.append(m.group(2))
        elif items:
            items[-1] += "\n" + text.strip()
    return [i for i in items if not _NONE.match(i)]


class _Form:
    def __init__(self, dir, out):
        self.dir, self.errors, self.warnings = dir, out["errors"], out["warnings"]
        self._main = False  # not looked for yet; then (root, None) or (None, why)

    def error(self, rel, field, reason):
        self.errors.append("%s: %s: %s" % (rel, field, reason))

    def warn(self, rel, field, reason):
        self.warnings.append("%s: %s: %s" % (rel, field, reason))

    def main(self):
        """(main checkout, None), or (None, why not)."""
        if self._main is False:
            try:
                self._main = (os.path.realpath(config.main_checkout(self.dir)), None)
            except config.ConfigError as e:
                self._main = (None, str(e))
        return self._main

    def headings(self, rel, scanned):
        order = scanned[2]
        required = [h for h in HEADINGS[os.path.basename(rel)]]
        for h in required:
            if h not in order:
                self.error(rel, "## " + h, "missing")
        present = [h for h in required if h in order]
        for a, b in zip(present, present[1:]):
            if order.index(b) < order.index(a):
                self.error(rel, "## " + b, "comes before ## " + a)


def _in(root, rel):
    """The real path of `rel` under `root` when it is a file there, else None (a path that leaves `root` is not one)."""
    p = os.path.realpath(os.path.join(root, rel))
    return p if (p == root or p.startswith(root + os.sep)) and os.path.isfile(p) else None


def _lines_of(path):
    with open(path, "rb") as f:
        data = f.read()
    return data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)


def _goal(f, rel, sections):
    if "Goal" not in sections:
        return
    text = [t for t, _ in sections["Goal"] if t.strip()]
    words = sum(len(t.split()) for t in text)
    if len(text) >= GOAL_LINES:
        f.error(rel, "## Goal", "%d lines, under ten required" % len(text))
    if words >= GOAL_WORDS:
        f.error(rel, "## Goal", "%d words, under %d required" % (words, GOAL_WORDS))


def _prose(body):
    return [t for t, code in body if not code]


def _history(f, rel, body):
    for text in _prose(body):
        for m in _HISTORY.finditer(text):
            f.error(rel, "body", 'edit history in the plan (git is the history): "%s"' % m.group(0))


def _ids(f, rel, body, data, decisions):
    defined = {"T": {t["id"] for t in plan._tasks_of(data)},
               "C": {c["id"] for c in data.get("criteria", []) if isinstance(c, dict) and isinstance(c.get("id"), str)}
               if isinstance(data.get("criteria"), list) else set(),
               "D": decisions}
    where = {"T": "tasks", "C": "criteria", "D": "decisions.tsv"}
    seen = set()
    for text in _prose(body):
        for m in _ID.finditer(text):
            i = m.group(1)
            if i not in defined[i[0]] and i not in seen:
                seen.add(i)
                f.error(rel, "body", "%s is not defined in %s" % (i, where[i[0]]))


def _cites(f, rel, body):
    """Each `file:line` cite of the prose: a file of the phase folder or of the main checkout, with that line."""
    unlooked, why = 0, None
    done = set()
    for text in _prose(body):
        for m in _CITE.finditer(text):
            name, first, last = m.group(1), int(m.group(2)), int(m.group(3) or m.group(2))
            if m.group(0) in done:
                continue
            done.add(m.group(0))
            path = _in(os.path.realpath(f.dir), name)
            if path is None:
                root, why = f.main()
                if root is None:
                    unlooked += 1
                    continue
                path = _in(root, name)
            if path is None:
                f.error(rel, "body", "cited file not found: " + name)
            elif first < 1 or last < first:
                f.error(rel, "body", "%s:%s is not a line%s" % (name, m.group(2) if last == first else "%s-%s" % (m.group(2), m.group(3)),
                                                                "" if last == first else " range"))
            elif last > _lines_of(path):
                f.error(rel, "body", "%s:%d is past its end (%d lines)" % (name, last, _lines_of(path)))
    if unlooked:
        f.warn(rel, "body", "NOT RUN, NOT ARMED: %d cite(s) not looked at, no main checkout (%s)" % (unlooked, why))


def _budget(f, rel, body):
    n = sum(len(t.split()) for t, _ in body)
    if n > WORDS_ERROR:
        f.error(rel, "body", "%d words, over the %d allowed" % (n, WORDS_ERROR))
    elif n > WORDS_WARN:
        f.warn(rel, "body", "%d words, over %d: is every line needed?" % (n, WORDS_WARN))


def _size(f, rel, data, sections, premortem):
    """A plan that warned about its size says why in `## Size`."""
    size = data.get("size") if isinstance(data.get("size"), dict) else {}
    tag, tasks = size.get("tag"), plan._tasks_of(data)
    reasons = []
    if tag in plan.BAND and len(tasks) > plan.BAND[tag]:
        reasons.append("the plan exceeds the %s band (%d tasks, %d allowed)" % (tag, len(tasks), plan.BAND[tag]))
    if premortem is not None and rel == "plan.md":
        for field, mine, theirs in (("size.tag", tag, premortem["size_tag"]), ("size.parts", size.get("parts"), premortem["parts"])):
            if mine != theirs:
                reasons.append("%s is %s and premortem.md says %s" % (field, mine, theirs))
    if not reasons:
        return
    text = "\n".join(t for t, _ in sections.get("Size", [])).strip()
    if not text:
        f.error(rel, "## Size", "%s, but %s: say why" % ("missing" if "Size" not in sections else "empty", "; ".join(reasons)))


def _valid(path, problems):
    """The frontmatter of a file when it loads and passes `problems`, else None."""
    try:
        data = plan.read_frontmatter(path)
    except plan.PlanError:
        return None
    return None if problems(data) else data


def _premortem(f, rel, data, sections):
    reasons = _items(sections.get("Failure reasons", []))
    if data["verdict"] == "ok" and reasons:
        f.error(rel, "## Failure reasons", "verdict ok with a failure reason listed")
    if data["verdict"] == "objections" and not reasons:
        f.error(rel, "## Failure reasons", "verdict objections with no failure reason listed")


def _postmortem(f, rel, data, sections):
    count = {k: 0 for k in SEVERITIES}
    for n, item in enumerate(_items(sections.get("Findings", [])), 1):
        m = _SEVERITY.match(item)
        if not m:
            f.error(rel, "findings[%d]" % n, "no severity (blocker, warning or info first)")
            continue
        sev = m.group(1).lower()
        count[sev] += 1
        ev = _EVIDENCE.search(item)
        if not ev:
            f.error(rel, "findings[%d]" % n, "no evidence: field")
        elif not ev.group(1).strip():
            f.error(rel, "findings[%d]" % n, "evidence: empty")
        elif sev != "info" and ev.group(1).lstrip(" `*_\"'").lower().startswith("unproven"):
            f.error(rel, "findings[%d]" % n, "unproven evidence on a %s" % sev)
    if data["verdict"] == "ok":
        for sev in ("blocker", "warning"):
            if count[sev]:
                f.error(rel, "findings", "verdict ok with a %s finding" % sev)
    if data["verdict"] == "objections" and not count["blocker"] + count["warning"]:
        f.error(rel, "findings", "verdict objections without a blocker or warning finding")


def _security(f, rel, seen):
    """security_review is true when a task writes a path the project protects."""
    tasks = [(r, t) for r, d in seen.items() if d is not None for t in plan._tasks_of(d) if isinstance(t.get("files"), list)]
    if not tasks:
        return
    try:
        cfg = config.load(f.dir)
    except config.ConfigError as e:
        f.warn(rel, "security_review", "NOT RUN, NOT ARMED: the protected paths are unknown (%s)" % e)
        return
    protected = cfg["project"].get("protected_paths")
    protected = [g for g in protected if isinstance(g, str)] if isinstance(protected, list) else []
    for r, t in tasks:
        for name in t["files"]:
            p = plan._norm(name) if isinstance(name, str) else ""
            glob = next((g for g in protected if p and (globs.matches(p, g) or globs.matches(p + "/", g))), None)
            if glob:
                f.error(rel, "security_review", "task %s%s touches a protected path (%s): security_review must be true"
                        % (t["id"], "" if r == "plan.md" else " of " + r, glob))
                break


def check(dir, seen, out):
    """Add the form errors and warnings of the phase folder `dir` to `out`; see the module text."""
    f = _Form(dir, out)
    decisions = {r.get("id") for r in state.read_rows(os.path.join(dir, "decisions.tsv"))}
    pre_path = os.path.join(dir, "premortem.md")
    premortem = _valid(pre_path, plan._premortem_problems) if os.path.exists(pre_path) else None
    for rel, data in seen.items():
        scanned = _scan(os.path.join(dir, rel)) if data is not None else None
        if scanned is None:
            continue
        body, sections, _ = scanned
        f.headings(rel, scanned)
        _goal(f, rel, sections)
        _history(f, rel, body)
        _ids(f, rel, body, data, decisions)
        _cites(f, rel, body)
        _budget(f, rel, body)
        _size(f, rel, data, sections, premortem)
    for name, semantic in (("premortem.md", _premortem), ("postmortem.md", _postmortem)):
        path = os.path.join(dir, name)
        scanned = _scan(path) if os.path.exists(path) else None
        if scanned is None:
            continue
        f.headings(name, scanned)
        data = _valid(path, plan._premortem_problems if name == "premortem.md" else plan._postmortem_problems)
        if data is not None:
            semantic(f, name, data, scanned[1])
    post_path = os.path.join(dir, "postmortem.md")
    post = _valid(post_path, plan._postmortem_problems) if os.path.exists(post_path) else None
    if post is not None and post["security_review"] is False:
        _security(f, "postmortem.md", seen)
