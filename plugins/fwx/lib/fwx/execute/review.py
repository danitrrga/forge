"""Read a review pass: `fwx wave review` writes its briefs, `fwx wave findings` reads what the reviewers and the verifier returned (09.5 T53).

`review(cwd, part_dir, run, frm, to, security, steps)` numbers the pass (`r1`, `r2` ... by the `review` calls the run's own files record) and writes the
brief of the reviewer, and of the security reviewer when `security` is set, the post-mortem asks for it (`security_review`) or the run's last
`wave merge --final` named a protected path (execute.js: `A.security.needed || st.protected.length > 0`). `next` is `launch`: the session launches
each agent of `reviewers` with its brief, then calls `findings`.

`findings(cwd, part_dir, run, lines, verdicts, control, steps)` is `wave findings`. `lines` are the last lines of the reviewers' replies, every
reviewer of the pass each time (a reviewer whose line is missing or unusable is a miss); `verdicts` is the last line of the verifier's reply. It
decides what reviewPass() of execute.js decides at d348f8d (readReview, validFinding, the criteria rule, asFinding, the routing of the verdicts) and
prints `next`:
  relaunch  nothing usable from `relaunch[*].unit`, the first time: launch it again with its brief and `note`, no round spent
  stop      a second miss: the run ends failed with `why` (`gap` is the line for the part report)
  verify    more than three items: the verifier's brief is `brief`, its unit `unit`; call `findings --verdicts` with its reply
  fix       `ids` are to be fixed: `why` is the text of `fwx wave fix --why`, `brief` the fixer's, `unit` its unit (what `wave report --unit` takes), `head` the BASE it
            starts from, `ids` the value of `wave merge --findings`
  owner     nothing to fix, but the last final merge named a protected path (execute.js ends the run there) or no brief could be written
  done      nothing to fix; `file` are the reviewer's large `outside` items, for the session to file as Linear issues
Every result also carries `items` (the pass's findings with their ids), `outside_of` (the outside item each id came from), `reported`, `criteria`
and the groups `fix`, `consider`, `note`, `dismissed`, `file` with `routes` (id -> group): what the part report reads.

The one behaviour that is not a port is the threshold: the verifier runs only above `THRESHOLD` items (D10), where execute.js ran it on any. Below
it every item is fixed, a large `outside` item excepted (it is too big for a round: it goes to `file`).
D25 (09-trim): a verdict `fix` of severity `low` (the verifier's) goes to `consider`, never to `fix`: only medium and high cost a fix round
and a new gate. Below the threshold nothing is verified, so every item is still fixed.

State is read from the run's own recorded calls (`steps`, oldest first), never from variables of a running script: the pass, its items, and the
misses of each unit (a unit's name holds its pass, so a miss of one pass never counts in the next). Only a `report.json` inside the folder
`fwx scratch new <run> <unit>` makes is read. Imports the standard library, fwx.config, fwx.plan, fwx.plan_step, fwx.state and execute.base,
brief, integrate, prepare and report.
"""
import json
import os
import re

from fwx import config, plan, plan_step, state
from fwx.core import evidence
from fwx.execute import brief, integrate, prepare
from fwx.execute.base import WaveError, out, toplevel
from fwx.execute.report import last_line, norm_path, outside_problem

THRESHOLD = 3
REVIEW_LINE = re.compile(r"reviewed (\S+) looked_at=(\d+) findings=(\d+) criteria_no=(\d+) criteria_unproven=(\d+)\Z")
VERDICT_LINE = re.compile(r"verdicts (\S+)\Z")
VERDICTS = ("fix", "consider", "note", "dismiss")
SEVERITIES = ("none", "low", "medium", "high")
CATCHABLE = ("code", "check", "rule", "none")
MET = ("yes", "no", "unproven")


def _text(v):
    return isinstance(v, str) and v.strip() != ""


def _top(cwd):
    top = toplevel(cwd)
    if top is None:
        raise WaveError("not inside a git repository: %s" % cwd)
    return top


def _protected(steps):
    """The protected paths the run's last `wave merge --final` named."""
    for rec in reversed(steps):
        if rec.get("step") == "integrate" and (rec.get("args") or {}).get("final"):
            return [p for p in (rec.get("result") or {}).get("protected") or [] if isinstance(p, str)]
    return []


def _context(top, part_dir, run):
    """(plan data, ctx) of the part, as the briefs of `wave merge` take them."""
    part = integrate._resolve_part(part_dir)
    try:
        data = plan.load_plan(state.phase_paths(part)["plan"])
    except (plan.PlanError, OSError) as e:
        raise WaveError("the plan of the part cannot be read: %s" % e)
    owner = state.phase_paths(integrate._owner_dir(part))
    paths = {"context": str(owner["context"]), "decisions": str(owner["decisions"]), "plan": str(state.phase_paths(part)["plan"])}
    common = out(top, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if not common:
        raise WaveError("cannot find the git common dir of %s" % top)
    return data, owner, {"run": run, "part": os.path.basename(part), "folder": brief.folder_of(common, run), "paths": paths}


def _write(path, facts, text):
    missing = [p for p in facts["context_files"] if not os.path.isfile(p)]
    if missing:
        raise WaveError("%s: CONTEXT names %s, which is not there" % (facts["unit"], ", ".join(missing)))
    try:
        brief.put(path, text)
    except OSError as e:
        raise WaveError("cannot write %s: %s" % (path, e))
    return path


# ---------------------------------------------------------------------------------------------------- wave review

def review(cwd, part_dir, run, frm, to, security, steps):
    """(0, result): the pass's briefs. Raises WaveError for what stops it before it writes anything."""
    top = _top(cwd)
    for ref in (frm, to):
        if out(top, "rev-parse", "--verify", "--quiet", ref + "^{commit}") is None:
            raise WaveError("%s is not a commit of this repository" % ref)
    data, owner, ctx = _context(top, part_dir, run)
    try:
        asked = prepare._security_why(data, owner["postmortem"], config.load(top))  # as `wave new` decides it: a small plan may have no post-mortem
    except (config.ConfigError, state.StateError) as e:
        raise WaveError(str(e))
    tag = "r%d" % (1 + sum(1 for r in steps if r.get("step") == "review"))
    protected = _protected(steps)
    why = (["--security"] if security else []) + asked + (["the last final merge named a protected path"] if protected else [])
    sec = bool(why)
    agents = [("reviewer", tag, "review-%s" % tag)] + ([("security-reviewer", tag + "-sec", "review-%s-sec" % tag)] if sec else [])
    made = []
    for kind, unit, name in agents:
        facts = brief.review_facts(kind, tag, unit, frm, to, ctx, criteria=data["criteria"] if kind == "reviewer" else (), protected=protected)
        made.append({"role": kind, "unit": unit, "brief": _write(brief.review_path(ctx["folder"], name), facts, brief.render_review(facts))})
    return 0, {"next": "launch", "why": "launch each reviewer with its brief, then `fwx wave findings --run %s --report \"<last line of each reply>\"...`" % run,
               "pass": tag, "from": frm, "to": to, "reviewers": made, "security": " and ".join(why) or "not asked for", "protected": protected}


# ---------------------------------------------------------------------------------------------------- reading a reviewer

def _tail(run, unit):
    return "/.fwx-agent/%s/%s/report.json" % (run, unit)


def _valid(f):
    return (isinstance(f, dict) and all(_text(f.get(k)) for k in ("id", "file", "claim", "evidence"))
            and isinstance(f.get("line"), int) and not isinstance(f.get("line"), bool) and f.get("severity") in brief.SEVERITY)


def _read_review(line, run, unit, want=()):
    """None when the line names no report of `unit`; else (report, rejection): the report is None for a miss, and the rejection is the
    reason when the report was read but is one to write again. `want` are the criterion ids the report must answer (the general reviewer's)."""
    m = REVIEW_LINE.match(last_line(line))
    path = m.group(1).replace("\\", "/") if m else ""
    if not path.endswith(_tail(run, unit)) or ".." in path.split("/"):
        return None
    if int(m.group(2)) == 0:
        return None, None
    try:
        with open(m.group(1), encoding="utf-8") as f:
            rep = json.load(f)
    except (OSError, ValueError):
        return None, None
    if not isinstance(rep, dict) or not isinstance(rep.get("looked_at"), list) or not rep["looked_at"]:
        return None, None
    if not isinstance(rep.get("findings"), list) or not isinstance(rep.get("criteria"), list):
        return None, None
    if any(not _valid(f) for f in rep["findings"]):
        return None, None
    # a defect nearby is an `outside` item with its fix; a reviewer fixes nothing and files nothing, so `issue` is null
    why = outside_problem(rep, "reviewer", False)
    if why:
        return None, why
    rep["outside"] = rep.get("outside", [])
    for c in rep["criteria"]:
        if not (isinstance(c, dict) and isinstance(c.get("id"), str) and c.get("met") in MET and isinstance(c.get("evidence"), str)):
            return None, None
        # a criterion that is not met is also a finding: a report where no finding names it lacks what it was asked for
        if c["met"] == "no" and not any(c["id"] in "%s %s" % (f["claim"], f["evidence"]) for f in rep["findings"]):
            return None, "criterion %s is not met and no finding names it: the claim or the evidence of the finding that reports it contains `%s`" % (c["id"], c["id"])
    left = [i for i in want if i not in {c["id"] for c in rep["criteria"]}]
    if left:  # `criteria: []` would otherwise let a review with nothing checked end as done
        return None, "the report has no result for criteria %s: `criteria` holds one entry per criterion of the plan" % ", ".join(left)
    return rep, None


def _prior(steps, unit):
    """(misses, rejection) of a unit: the `relaunch` results of the run's `findings` calls that named it."""
    n, rejected = 0, None
    for rec in steps:
        if rec.get("step") != "findings":
            continue
        for x in (rec.get("result") or {}).get("relaunch") or []:
            if x.get("unit") == unit:
                n += 1
                rejected = rejected or x.get("rejected")
    return n, rejected


def _result(next_, tag, **kw):
    r = {"next": next_, "why": "", "pass": tag, "unit": None, "ids": [], "brief": None, "head": None, "reported": 0, "items": [], "outside_of": {},
         "fix": [], "consider": [], "note": [], "dismissed": [], "file": [], "routes": {}, "criteria": [], "relaunch": [], "gap": None}
    r.update(kw)
    return r


def _missed(steps, tag, misses, **kw):
    """The result for units that returned nothing usable: a launch again with no round spent, or, for a unit that already had that, the end of the run.
    `misses` are {role, unit, brief, rejected, note}."""
    for m in misses:
        prior, earlier = _prior(steps, m["unit"])
        rejected = m["rejected"] or earlier
        if prior >= 1:
            why = "%s returned a report that was rejected: %s" % (m["role"], rejected) if rejected else "%s did not return" % m["role"]
            return _result("stop", tag, why=why, gap=why, **kw)
    why = "; ".join("%s %s: %s" % (m["role"], m["unit"], m["rejected"] or m["note"].strip() or "no usable report") for m in misses)
    return _result("relaunch", tag, why=why, relaunch=[dict(m, note=m["note"] or ("\nYour last report was rejected, so write it again: %s." % m["rejected"] if m["rejected"] else ""))
                                                       for m in misses], **kw)


# ---------------------------------------------------------------------------------------------------- the items of a pass

def _as_finding(ident, o):
    """An `outside` item as the finding a fixer or the verifier takes."""
    return {"id": ident, "file": norm_path(re.sub(r":\d+\Z", "", o["where"])), "line": int(o["where"].rsplit(":", 1)[1]), "claim": o["what"],
            "evidence": "seen outside the diff or the task, not made by it; the fix its finder proposes: " + o["fix"], "severity": "medium"}


def _items(tag, units, reports, control):
    """(items, outside_of, criteria): the findings of the pass in order, ids prefixed by it (`r1-F1`: a reviewer numbers from F1 every time, and
    `wave merge --findings` and `wave revert` find a commit by its id); an `outside` item of a reviewer is one too, numbered `O<k>` (`SO<k>` for the
    security reviewer's)."""
    items, outside_of, seen, criteria = [], {}, set(), {}

    def take(f, o=None):
        ident = "%s-%s" % (tag, re.sub(r"[^A-Za-z0-9._-]", "_", str(f["id"])))
        while ident in seen:
            ident += ".x"
        seen.add(ident)
        items.append(dict({k: f[k] for k in brief.FINDING_KEYS}, id=ident))
        if o is not None:
            outside_of[ident] = o

    for i, (role, unit) in enumerate(units):
        rep = reports[unit]
        for f in rep["findings"]:
            take(f)
        for k, o in enumerate(rep["outside"], 1):
            take(_as_finding("%s%d" % ("O" if i == 0 else "SO", k), o), o)
        for c in rep["criteria"]:
            criteria[c["id"]] = {"id": c["id"], "met": c["met"], "evidence": c["evidence"]}
    if tag == "r1" and control:
        for f in control:
            take(f)
    return items, outside_of, list(criteria.values())


def _large(outside_of, ident):
    o = outside_of.get(ident)
    return o is not None and o["size"] == "large"


def _route(items, outside_of, by):
    """(groups, routes) of the items. `by` is {id: verdict} from the verifier, or None below the threshold: every item is then to fix."""
    groups = {"fix": [], "consider": [], "note": [], "dismissed": [], "file": []}
    routes = {}
    for it in items:
        ident = it["id"]
        d = (by or {}).get(ident)
        verdict = d["verdict"] if d else "fix"
        severity = d["severity"] if d and d["severity"] in brief.SEVERITY else it["severity"]
        if _large(outside_of, ident) and verdict == "fix":
            # too big for a fix round whatever its severity: returned for the session to file as a Linear issue
            groups["file"].append(outside_of[ident])
            routes[ident] = "file"
            continue
        demoted = verdict == "fix" and d is not None and severity == "low"
        if demoted:
            verdict = "consider"  # D25: a verified finding of severity low is listed for the owner; only medium and high cost a fix round and a new gate
        if verdict == "fix":
            groups["fix"].append(dict(it, severity=severity))
            routes[ident] = "fix"
        elif verdict == "consider":
            groups["consider"].append({"id": ident, "file": it["file"], "line": it["line"], "claim": it["claim"], "severity": severity if demoted else d["severity"]})
            routes[ident] = "consider"
        elif verdict == "note":
            groups["note"].append({"id": ident, "claim": it["claim"]})
            routes[ident] = "note"
        else:
            groups["dismissed"].append({"id": ident, "reason": d["reason"]})
            routes[ident] = "dismissed"
    return groups, routes


def _fixer(top, part_dir, run, fix):
    """(unit, path of the fixer's brief, head): the brief of `brief.fix_facts` for the findings to fix, the findings in a file beside it."""
    data, _, ctx = _context(top, part_dir, run)
    cfg = config.load(top)
    unit, path = brief.next_unit(ctx["folder"], "fix")
    source = os.path.join(ctx["folder"], "briefs", "_findings-%s.json" % unit)
    os.makedirs(os.path.dirname(source), exist_ok=True)
    with open(source, "x", encoding="utf-8") as f:
        json.dump(fix, f, indent=1)
        f.write("\n")
    try:
        quick = evidence.plan_checks(cfg["project"]["checks_quick"], os.devnull)
        facts = brief.fix_facts(fix, source, data["tasks"], quick, data["size"]["tag"], ctx, unit)
        problems = brief.missing(facts)
        if problems:
            raise WaveError("; ".join(problems))
        brief.put(path, brief.render(facts))
    except BaseException:
        os.unlink(source)  # next_unit counts the brief files only: a source left alone would make the next call's exclusive open fail for good
        raise
    return unit, path, out(top, "rev-parse", "HEAD")


def _conclude(top, part_dir, run, tag, steps, items, outside_of, criteria, groups, routes, **kw):
    """The result of a pass whose items are routed: the fixer's brief for what is left to fix, else the end of the review."""
    common = dict(items=items, outside_of=outside_of, criteria=criteria, reported=len(items), routes=routes, **groups)
    common.update(kw)
    fix = groups["fix"]
    if fix:
        ids = [f["id"] for f in fix]
        why = "review findings to fix: %s" % ", ".join(ids)
        try:
            unit, path, head = _fixer(top, part_dir, run, fix)
        except (WaveError, config.ConfigError, state.StateError, plan.PlanError, OSError) as e:
            return _result("owner", tag, why="no brief could be written for the fixer (%s): %s" % (e, why), **common)
        # `unit` is the fixer's, which `wave report --unit` reads, and not the verifier's that `common` may carry
        return _result("fix", tag, why=why, ids=ids, brief=path, head=head, **dict(common, unit=unit))
    protected = _protected(steps)
    next_, why = ("owner", "protected path: %s" % ", ".join(protected)) if protected else ("done", "nothing is left to fix")
    return _result(next_, tag, why=why, **common)


# ---------------------------------------------------------------------------------------------------- wave findings

def _controls(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise WaveError("--control-findings %s cannot be read as a JSON list of findings (%s)" % (path, e))
    problems = brief.finding_problems(data) if isinstance(data, list) else ["it is not a list"]
    if problems:
        raise WaveError("--control-findings %s: %s" % (path, "; ".join(problems)))
    return brief.normalize(data)


def _newest(steps, step, want=None):
    for rec in reversed(steps):
        if rec.get("step") == step and (want is None or (rec.get("result") or {}).get("next") == want):
            return rec["result"]
    return None


def findings(cwd, part_dir, run, lines, verdicts, control, steps):
    """(0, result) of `wave findings`: the reports of a pass (`lines`) or the verdicts of its verifier (`verdicts`), as the module's text says."""
    top = _top(cwd)
    if verdicts is not None:
        return 0, _judge(top, part_dir, run, verdicts, steps)
    passed = _newest(steps, "review")
    if passed is None:
        raise WaveError("run %s has no `fwx wave review` call: there is no review pass to read" % run)
    tag = passed["pass"]
    units = [(x["role"], x["unit"]) for x in passed["reviewers"]]
    reports, misses = {}, []
    asked = [c["id"] for c in _context(top, part_dir, run)[0]["criteria"]]
    for x in passed["reviewers"]:
        found = None
        for line in lines:
            found = _read_review(line, run, x["unit"], asked if x["role"] == "reviewer" else ())
            if found is not None:
                break
        rep, rejected = found if found else (None, None)
        if rep is None:
            misses.append({"role": x["role"], "unit": x["unit"], "brief": x["brief"], "rejected": rejected, "note": ""})
        else:
            reports[x["unit"]] = rep
    if misses:
        return 0, _missed(steps, tag, misses)
    items, outside_of, criteria = _items(tag, units, reports, _controls(control) if control else [])
    if not items:
        return 0, _conclude(top, part_dir, run, tag, steps, items, outside_of, criteria, _route([], {}, None)[0], {})
    if len(items) > THRESHOLD:
        unit, ctx = tag + "-verifier", _context(top, part_dir, run)[2]
        facts = brief.review_facts("review-verifier", tag, unit, passed["from"], passed["to"], ctx, items=items)
        path = _write(brief.review_path(ctx["folder"], "verify-%s" % tag), facts, brief.render_review(facts))
        return 0, _result("verify", tag, why="more than %d items: launch the verifier with its brief, then `fwx wave findings --run %s --verdicts \"<last line of its reply>\"`"
                          % (THRESHOLD, run), unit=unit, brief=path, items=items, outside_of=outside_of, criteria=criteria, reported=len(items))
    groups, routes = _route(items, outside_of, None)
    return 0, _conclude(top, part_dir, run, tag, steps, items, outside_of, criteria, groups, routes)


def _read_verdicts(line, run, unit, items):
    """(by, note): `by` is {id: verdict} when the line names the verifier's report and it covers every item; else None and the reason."""
    m = VERDICT_LINE.match(last_line(line))
    path = m.group(1).replace("\\", "/") if m else ""
    if not path.endswith(_tail(run, unit)) or ".." in path.split("/"):
        return None, ""
    try:
        with open(m.group(1), encoding="utf-8") as f:
            rep = json.load(f)
    except (OSError, ValueError):
        return None, ""
    if not isinstance(rep, dict) or not isinstance(rep.get("verdicts"), list):
        return None, "the report is `{verdicts: [...]}`"
    by = {}
    for k, d in enumerate(rep["verdicts"], 1):
        bad = None
        if not (isinstance(d, dict) and _text(d.get("id"))):
            bad = "it has no `id`"
        elif d.get("verdict") not in VERDICTS:
            bad = "`verdict` is one of %s, got %s" % (", ".join(VERDICTS), json.dumps(d.get("verdict")))
        elif d.get("severity") not in SEVERITIES:
            bad = "`severity` is one of %s, got %s" % (", ".join(SEVERITIES), json.dumps(d.get("severity")))
        elif not isinstance(d.get("reason"), str) or ("catchable_by" in d and d["catchable_by"] not in CATCHABLE):
            bad = "it needs a `reason` and, when it has `catchable_by`, one of %s" % ", ".join(CATCHABLE)
        if bad:
            return None, "verdict %d: %s" % (k, bad)
        by.setdefault(d["id"], d)
    missing = [i["id"] for i in items if i["id"] not in by]
    if missing:
        return None, "no verdict for %s: one verdict per finding id, exactly as written in the brief" % ", ".join(missing)
    return by, ""


def _judge(top, part_dir, run, line, steps):
    """The result of the verifier's reply `line`: its verdicts routed, or its miss."""
    waiting = _newest(steps, "findings", "verify")
    if waiting is None:
        raise WaveError("no review pass of run %s waits for the verifier: `fwx wave findings --report` says `verify` when one does" % run)
    tag, unit, items, outside_of, criteria = waiting["pass"], waiting["unit"], waiting["items"], waiting["outside_of"], waiting["criteria"]
    by, note = _read_verdicts(line, run, unit, items)
    if by is None:
        miss = {"role": "review-verifier", "unit": unit, "brief": waiting["brief"], "rejected": None, "note": "\nYour last report was rejected, so write it again: %s." % note if note else ""}
        return _missed(steps, tag, [miss], unit=unit, brief=waiting["brief"], items=items, outside_of=outside_of, criteria=criteria, reported=len(items))
    groups, routes = _route(items, outside_of, by)
    return _conclude(top, part_dir, run, tag, steps, items, outside_of, criteria, groups, routes, unit=unit)
