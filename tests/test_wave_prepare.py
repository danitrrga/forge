#!/usr/bin/env python3
"""`fwx wave prepare` and `fwx wave check-base` (3.4 U2): lib/fwx/commands/wave.py, lib/fwx/execute/prepare.py, base.py.

The run builds toy repos (tests/helpers.py `toy_repo`, with a linked worktree on the phase branch as the session has) and
asks the command through `bin/fwx`. The user's Claude Code folder is a toy one (`CLAUDE_CONFIG_DIR`), so no real setting
reaches a case. Nothing here reads the real HOME, the real configuration or a real project.

Seen red before the code existed (python3 tests/test_wave_prepare.py, first lines; `fwx wave` was not a command):
  FAIL: prepare, the base case: exit: got (2, "fwx: unknown command: wave\n\nusage: fwx <command> [args]\n\ncommands:\n  budget ...
  FAIL: prepare, the base case: stdout is the args: got <not JSON: ''>, want an object
  FAIL: args: run: got None, want '01-alpha-fe27f07-1'

Controls: each case also runs on a copy of bin/ and lib/ with one line of the code changed (`MUTANTS` below, each line must
be in the file exactly once), and must fail with the text in `MUTANTS`; the good code passes first (188 checks). The first FAIL
line of each, seen red:
  clash not marked:        FAIL: clash: wave 1 serial=False, want True: got False, want True
  red base not run:        FAIL: red base: prepare exit 0 on a red base: got 0, want 1
  ignored file allowed:    FAIL: ignored: prepare exit 0 with ignored config/forge.json: got 0, want 2
  default branch allowed:  FAIL: default branch: exit: got 0, want 2
  baseRef not read:        FAIL: baseRef absent: prepare exit 0 with baseRef absent: got 0, want 2
  baseRef not from user:   FAIL: baseRef from the user's settings: exit: got 2, want 0
  unattended never set:    FAIL: unattended: factory args.unattended False, want True: got False, want True
  done from every branch:  FAIL: done: a trailer on another branch is not done: got ['T1', 'T3'], want ['T1']
  checks of the checkout:  FAIL: from a worktree: exit: got (2, 'fwx wave prepare: no checks defined: ...'), want (0, '')
  subphase as a phase:     FAIL: subphase: context.md is the parent's: got '.../03-alpha/03.1-beta/context.md', want '.../03-alpha/context.md'
  check-base by merge-base: FAIL: check-base: an ancestor of HEAD is another base: exit 0, want 42: got 0, want 42
  check-base, main checkout: FAIL: check-base: the main checkout: exit 0, want 42: got 0, want 42
"""
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

ROOT = helpers.ROOT
s = helpers.Suite()
PHASE = "01-alpha"
CRIT = [{"id": "C1", "text": "it works", "measure": "m1"}, {"id": "C2", "text": "it is tested", "measure": "m2"}]


def runner(root):
    def run(cwd, *args, env=None):
        return subprocess.run([sys.executable, os.path.join(root, "bin", "fwx")] + list(args), cwd=cwd,
                              env=helpers.clean_env(**(env or {})), capture_output=True, text=True)
    return run


def task(tid, wave, files, size="small", ui=False, deps=(), typ="feature"):
    return {"id": tid, "part": 1, "type": typ, "wave": wave, "files": list(files), "depends_on": list(deps),
            "tests": [{"run": "python3 t.py", "measures": "m", "red": "r"}], "size": size, "ui": ui}


def front(obj):
    return "---\n%s\n---\n\nbody\n" % json.dumps(obj, indent=1)


class Scene:
    """A main checkout on master, a linked worktree on `phase` (or, with wt=False, the main one on `phase`), the part's
    folder in the main checkout's `.fwx/`, the project's configuration and settings in its ignored `.claude/`."""

    def __init__(self, tasks=None, recipe=("true",), base_ref="head", security=False, wt=True, config=None, size="normal",
                 sub=False, settings=None, user=None, plan_extra=None):
        self.repo = helpers.toy_repo({"README": "toy\n", ".gitignore": ".fwx/\n.claude/\nconfig/forge.json\n",
                                      "src/a.py": "a\n", "src/b.py": "b\n"})
        cfg = {"schema": 1, "project": {"checks": list(recipe)}}
        cfg.update(config or {})
        helpers.write(self.repo, ".claude/fwx.json", json.dumps(cfg))
        local = settings if settings is not None else ({"worktree": {"baseRef": base_ref}} if base_ref else None)
        if local is not None:
            helpers.write(self.repo, ".claude/settings.local.json", json.dumps(local))
        self.conf = helpers.mkdtemp("fwx-claude-")
        if user is not None:
            helpers.write(self.conf, "settings.json", json.dumps(user))
        self.env = {"CLAUDE_CONFIG_DIR": self.conf}
        if wt:
            self.cwd = helpers.add_worktree(self.repo, "phase")
        else:
            helpers.git(self.repo, "checkout", "-q", "-b", "phase")
            self.cwd = self.repo
        phases = os.path.join(self.repo, ".fwx", "milestones", "v1", "phases")
        self.phase = os.path.join(phases, "03-alpha" if sub else PHASE)
        self.part = os.path.join(self.phase, "03.1-beta") if sub else self.phase
        plan = {"size": {"tag": size, "parts": 1, "agents": 2}, "criteria": CRIT,
                "tasks": tasks if tasks is not None else [task("T1", 1, ["src/a.py"]), task("T2", 2, ["src/b.py"], size="big")],
                "not_built": [], "later": []}
        plan.update(plan_extra or {})
        helpers.write(self.part, "plan.md", front(plan))
        helpers.write(self.part, "postmortem.md", front({"verdict": "ok", "security_review": security, "round": 1}))
        helpers.write(self.phase, "context.md", "# context\n")
        helpers.write(self.phase, "decisions.tsv", "date\tid\tdecision\twhy\trejected\tsupport\tsource\tsupersedes\n")
        self.name = os.path.basename(self.part)

    def head(self):
        return helpers.git(self.cwd, "rev-parse", "HEAD").strip()

    def commit(self, name, message, cwd=None):
        helpers.write(cwd or self.cwd, name, name + "\n")
        helpers.git(cwd or self.cwd, "add", "-A")
        helpers.git(cwd or self.cwd, "commit", "-q", "-m", message)

    def prepare(self, R, *extra, plane="session", branch="phase", cwd=None, env=None):
        e = dict(self.env)
        e.update(env or {})
        return R(cwd or self.cwd, "wave", "prepare", "--part-dir", self.part, "--plane", plane, "--branch", branch, *extra, env=e)

    def audit_exists(self):
        return os.path.exists(os.path.join(self.part, "audit.tsv"))


def args_of(r):
    try:
        v = json.loads(r.stdout)
    except ValueError:
        return None
    return v if isinstance(v, dict) else None


def ok_args(S, label, r):
    S.eq("%s: exit" % label, (r.returncode, r.stderr.strip()[:200] if r.returncode else ""), (0, ""))
    a = args_of(r)
    S.ok("%s: stdout is the args" % label, a is not None, "got <not JSON: %r>, want an object" % r.stdout[:80])
    return a or {}


def refused(S, label, sc, r, needle):
    """Exit 2, nothing on stdout, nothing written, and the reason on stderr."""
    S.eq("%s: exit" % label, r.returncode, 2)
    S.eq("%s: stdout empty" % label, r.stdout, "")
    S.ok("%s: the refusal says %r" % (label, needle), needle in r.stderr, "stderr %r" % r.stderr[:300])
    S.ok("%s: nothing written" % label, not sc.audit_exists())


# ---------------------------------------------------------------------------------------------------- the cases

def case_base(R, S):
    sc = Scene()
    r = sc.prepare(R)
    a = ok_args(S, "prepare, the base case", r)
    base = sc.head()
    S.eq("args: run", a.get("run"), "%s-%s-1" % (PHASE, base[:7]))
    S.eq("args: plane, unattended, isolation", (a.get("plane"), a.get("unattended"), a.get("isolation")), ("session", False, "native"))
    S.eq("args: branch, base", (a.get("branch"), a.get("base")), ("phase", base))
    S.eq("args: checkout is the worktree", a.get("checkout"), sc.cwd)
    S.eq("args: part_dir and phase_dir", (a.get("part_dir"), a.get("phase_dir")), (sc.part, sc.phase))
    S.eq("args: paths", a.get("paths"), {"context": os.path.join(sc.phase, "context.md"), "decisions": os.path.join(sc.phase, "decisions.tsv"),
                                         "plan": os.path.join(sc.part, "plan.md"), "postmortem": os.path.join(sc.part, "postmortem.md"),
                                         "config": os.path.join(sc.repo, ".claude", "fwx.json")})
    S.eq("args: criteria", a.get("criteria"), CRIT)
    S.eq("args: no fix, no revert, no control findings", (a.get("fix"), a.get("revert"), a.get("control_findings")), (None, [], []))
    S.eq("args: no clash, nothing done", (a.get("plan_failures"), a.get("done")), ([], []))
    S.eq("args: security not needed", a.get("security", {}).get("needed"), False)
    waves = a.get("waves") or []
    S.eq("waves: numbers, ordered", [w.get("n") for w in waves], [1, 2])
    S.eq("waves: serial false without a clash", [w.get("serial") for w in waves], [False, False])
    t1 = (waves[0]["tasks"] or [{}])[0] if waves else {}
    S.eq("task: fields", (t1.get("id"), t1.get("type"), t1.get("size"), t1.get("ui"), t1.get("trailer")),
         ("T1", "feature", "small", False, "%s/T1" % PHASE))
    S.ok("task: has a brief key (U9 fills it)", "brief" in t1, repr(t1))
    S.ok("prepare wrote nothing in the part", not sc.audit_exists())


def case_models(R, S):
    cfg = {"models": {"executor": {"small": "haiku", "normal": "sonnet", "big": "opus"},
                      "reviewer": {"small": "haiku", "normal": "sonnet", "big": "opus"},
                      "security-reviewer": {"small": "haiku", "normal": "sonnet", "big": "fable"},
                      "review-verifier": {"small": "haiku", "normal": "sonnet", "big": "opus"}}}
    sc = Scene(config=cfg, size="big")
    a = ok_args(S, "models", sc.prepare(R))
    m = a.get("models") or {}
    S.eq("models: executor by the task's size", m.get("executor"), {"T1": "haiku", "T2": "opus"})
    S.eq("models: runner is executor small, verifier is small, reviewer and fixer by the plan's size",
         (m.get("runner"), m.get("review_verifier"), m.get("reviewer"), m.get("fixer"), m.get("security_reviewer")),
         ("haiku", "haiku", "opus", "opus", "fable"))
    sd = Scene()
    m = ok_args(S, "models, defaults", sd.prepare(R)).get("models") or {}
    roles = ["runner", "fixer", "reviewer", "review_verifier", "security_reviewer"]
    S.ok("every role carries a model alias", all(m.get(k) in ("sonnet", "opus", "haiku", "fable") for k in roles)
         and all(v in ("sonnet", "opus", "haiku", "fable") for v in (m.get("executor") or {"x": None}).values()), repr(m))


def case_clash(R, S):
    sc = Scene(tasks=[task("T1", 1, ["src/a.py"]), task("T2", 1, ["src/"]), task("T3", 2, ["src/b.py"])])
    a = ok_args(S, "clash", sc.prepare(R))
    waves = a.get("waves") or [{}, {}]
    S.eq("clash: wave 1 serial=%s, want True" % waves[0].get("serial"), waves[0].get("serial"), True)
    S.eq("clash: wave 2 is not serial", waves[1].get("serial"), False)
    S.eq("clash: plan_failures names wave, tasks and the shared path", a.get("plan_failures"),
         [{"wave": 1, "tasks": ["T1", "T2"], "files": ["src"]}])


def case_red_base(R, S):
    sc = Scene(recipe=["echo boom; exit 3"])
    r = sc.prepare(R)
    S.eq("red base: prepare exit %d on a red base" % r.returncode, r.returncode, 1)
    out = args_of(r) or {}
    S.eq("red base: status and rounds", (out.get("status"), out.get("rounds")), ("needs-owner", "0/3"))
    S.ok("red base: the reason names the command and its exit", "echo boom; exit 3=3" in out.get("reason", ""), repr(out))
    S.ok("red base: stderr says rounds 0/3 and shows the output", "rounds 0/3" in r.stderr and "boom" in r.stderr, r.stderr)
    S.ok("red base: no evidence row written", not sc.audit_exists())
    ok = Scene(recipe=["false"])
    sha = ok.head()
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    from fwx import state  # noqa: E402
    state.append_audit(ok.part, "evidence", sha=sha, rc="0", detail="{}")
    ev = ok.prepare(R)
    S.eq("red base: a green evidence row for the sha stands in for the run: exit", ev.returncode, 0)
    other = Scene(recipe=["false"])
    state.append_audit(other.part, "evidence", sha="0" * 40, rc="0", detail="{}")
    S.eq("red base: a green row for another sha does not", other.prepare(R).returncode, 1)
    none = Scene(recipe=[])
    refused(S, "no checks at all", none, none.prepare(R), "no checks")


def case_ignored(R, S):
    sc = Scene(tasks=[task("T1", 1, ["src/a.py"]), task("T2", 1, ["config/forge.json"])])
    r = sc.prepare(R)
    S.eq("ignored: prepare exit %d with ignored config/forge.json" % r.returncode, r.returncode, 2)
    refused(S, "ignored", sc, r, "config/forge.json")


def case_default_branch(R, S):
    sc = Scene(wt=False)
    helpers.git(sc.repo, "checkout", "-q", "master")
    r = sc.prepare(R, branch="master")
    refused(S, "default branch", sc, r, "default branch")
    S.ok("default branch: the refusal names the default branch", "default branch" in r.stderr, "stderr %r" % r.stderr[:80])
    cfg = Scene(config={"project": {"checks": ["true"], "default_branch": "phase"}})
    refused(S, "default branch from the configuration", cfg, cfg.prepare(R), "default branch")
    other = Scene()
    refused(S, "a checkout on another branch", other, other.prepare(R, branch="elsewhere"), "elsewhere")
    d = Scene()
    helpers.write(d.cwd, "junk.txt", "x\n")
    refused(S, "a dirty integration checkout", d, d.prepare(R), "uncommitted")


def case_plan(R, S):
    sc = Scene(plan_extra={"criteria": []})
    refused(S, "a plan that does not validate", sc, sc.prepare(R), "criteria")
    nm = Scene()
    os.remove(os.path.join(nm.part, "postmortem.md"))
    refused(S, "no postmortem", nm, nm.prepare(R), "postmortem.md")
    bad = Scene()
    refused(S, "a plane that is neither", bad, bad.prepare(R, plane="both"), "plane")


def case_base_ref(R, S):
    sc = Scene(base_ref=None)
    r = sc.prepare(R)
    S.eq("baseRef absent: prepare exit %d with baseRef absent" % r.returncode, r.returncode, 2)
    refused(S, "baseRef absent", sc, r, "worktree.baseRef is absent, not head")
    fr = Scene(base_ref="fresh")
    refused(S, "baseRef fresh", fr, fr.prepare(R), "worktree.baseRef is fresh, not head")
    ok_args(S, "baseRef head from the main checkout's settings.local.json, run from a linked worktree", Scene().prepare(R))
    ok_args(S, "baseRef head, run from the main checkout", Scene(wt=False).prepare(R))
    u = Scene(base_ref=None, user={"worktree": {"baseRef": "head"}})
    S.eq("baseRef from the user's settings: exit", u.prepare(R).returncode, 0)
    o = Scene(base_ref="fresh", user={"worktree": {"baseRef": "head"}})
    refused(S, "baseRef: the local file outranks the user's", o, o.prepare(R), "worktree.baseRef is fresh, not head")
    bad = Scene(settings={})
    helpers.write(bad.repo, ".claude/settings.local.json", "{not json")
    refused(S, "settings that are not JSON", bad, bad.prepare(R), "settings.local.json")


def case_unattended(R, S):
    sc = Scene()
    S.eq("unattended: a session plane", ok_args(S, "session", sc.prepare(R)).get("unattended"), False)
    f = ok_args(S, "factory", sc.prepare(R, plane="factory"))
    S.eq("unattended: factory args.unattended %s, want True" % f.get("unattended"), f.get("unattended"), True)
    S.eq("unattended: --unattended on a session", ok_args(S, "flag", sc.prepare(R, "--unattended")).get("unattended"), True)
    S.eq("unattended: the plane stays", f.get("plane"), "factory")


def case_security(R, S):
    sc = Scene(security=True)
    sec = ok_args(S, "security from the postmortem", sc.prepare(R)).get("security") or {}
    S.eq("security: postmortem security_review", sec.get("needed"), True)
    S.ok("security: why names the postmortem", "postmortem" in sec.get("why", ""), repr(sec))
    pl = Scene()
    sec = ok_args(S, "security flag", pl.prepare(R, "--security")).get("security") or {}
    S.eq("security: --security", sec.get("needed"), True)
    S.ok("security: why names the flag", "--security" in sec.get("why", ""), repr(sec))


def case_done(R, S):
    sc = Scene(tasks=[task("T1", 1, ["src/a.py"]), task("T2", 1, ["src/b.py"]), task("T3", 2, ["README"])])
    sc.commit("one.txt", "feat: one\n\nFwx-Task: %s/T1\nFwx-Run: r" % PHASE)
    sc.commit("two.txt", "mention Fwx-Task: %s/T2 in the subject" % PHASE)
    helpers.git(sc.cwd, "branch", "other")
    helpers.git(sc.cwd, "checkout", "-q", "other")
    sc.commit("three.txt", "feat: three\n\nFwx-Task: %s/T3" % PHASE)
    helpers.git(sc.cwd, "checkout", "-q", "phase")
    a = ok_args(S, "done", sc.prepare(R))
    S.eq("done: a trailer on another branch is not done", a.get("done"), ["T1"])
    S.eq("done: base is the head of the phase branch", a.get("base"), sc.head())


def case_worktree_checks(R, S):
    sc = Scene(recipe=["touch ran-in-checkout"])
    a = ok_args(S, "from a worktree", sc.prepare(R))
    S.ok("from a worktree: the checks are the main checkout's, run in the worktree", os.path.exists(os.path.join(sc.cwd, "ran-in-checkout")))
    S.ok("from a worktree: the worktree has no fwx.json of its own", not os.path.exists(os.path.join(sc.cwd, ".claude", "fwx.json")))
    S.eq("from a worktree: config path is the main's", (a.get("paths") or {}).get("config"), os.path.join(sc.repo, ".claude", "fwx.json"))


def case_subphase(R, S):
    sc = Scene(sub=True)
    a = ok_args(S, "subphase", sc.prepare(R))
    p = a.get("paths") or {}
    S.eq("subphase: context.md is the parent's: got %r, want %r" % (p.get("context"), os.path.join(sc.phase, "context.md")),
         p.get("context"), os.path.join(sc.phase, "context.md"))
    S.eq("subphase: decisions.tsv is the parent's", p.get("decisions"), os.path.join(sc.phase, "decisions.tsv"))
    S.eq("subphase: plan.md is its own", p.get("plan"), os.path.join(sc.part, "plan.md"))
    S.eq("subphase: phase_dir is the parent, part_dir the subphase", (a.get("phase_dir"), a.get("part_dir")), (sc.phase, sc.part))
    S.eq("subphase: the trailer names the subphase", ((a.get("waves") or [{"tasks": [{}]}])[0]["tasks"][0].get("trailer")), "03.1-beta/T1")


def case_fix_options(R, S):
    sc = Scene()
    f = os.path.join(helpers.mkdtemp("fwx-find-"), "f.json")
    findings = [{"id": "F1", "file": "src/a.py", "line": 1, "claim": "c", "evidence": "e", "severity": "low"}]
    helpers.write(os.path.dirname(f), "f.json", json.dumps(findings))
    a = ok_args(S, "options", sc.prepare(R, "--fix", f, "--revert", "F1,F2", "--control-findings", f))
    S.eq("options: fix (with --revert nothing is launched, so fix.brief is None: 3.4 U9)", a.get("fix"), {"source": f, "findings": findings, "brief": None})
    S.eq("options: revert, control findings", (a.get("revert"), a.get("control_findings")), (["F1", "F2"], findings))
    refused(S, "--fix with a file that is not there", sc, sc.prepare(R, "--fix", f + ".none"), "--fix")


def case_check_base(R, S):
    sc = Scene()
    base = sc.head()
    cb = lambda cwd, *a: R(cwd, "wave", "check-base", *a, env=sc.env)  # noqa: E731
    r = cb(sc.cwd, base)
    S.eq("check-base: the HEAD of a linked worktree: exit", (r.returncode, r.stderr), (0, ""))
    S.eq("check-base: a short sha", cb(sc.cwd, base[:7]).returncode, 0)
    S.eq("check-base: --worktree is this one", cb(sc.cwd, base, "--worktree", sc.cwd).returncode, 0)
    r = cb(sc.cwd, base, "--worktree", sc.repo)
    S.eq("check-base: --worktree is another folder: exit", r.returncode, 42)
    S.ok("check-base: --worktree names both", sc.cwd in r.stderr and sc.repo in r.stderr, r.stderr)
    r = cb(sc.repo, base)
    S.eq("check-base: the main checkout: exit %d, want 42" % r.returncode, r.returncode, 42)
    S.ok("check-base: the main checkout says `not a linked worktree: <path>`", "not a linked worktree: %s" % sc.repo in r.stderr, r.stderr)
    sc.commit("more.txt", "feat: more")
    r = cb(sc.cwd, base)
    S.eq("check-base: an ancestor of HEAD is another base: exit %d, want 42" % r.returncode, r.returncode, 42)
    S.ok("check-base: `wrong base: HEAD <x>, expected <sha>`", "wrong base: HEAD %s, expected %s" % (sc.head(), base) in r.stderr, r.stderr)
    S.eq("check-base: the new HEAD", cb(sc.cwd, sc.head()).returncode, 0)
    S.eq("check-base: the other branch's HEAD", cb(sc.cwd, helpers.git(sc.repo, "rev-parse", "master").strip()).returncode, 42)
    for bad in ("HEAD", "phase", "abc", "zzzzzzz"):
        S.eq("check-base: %r is not a sha: usage error" % bad, cb(sc.cwd, bad).returncode, 2)
    S.eq("check-base: no argument", cb(sc.cwd).returncode, 2)
    outside = helpers.mkdtemp("fwx-nogit-")
    r = cb(outside, base)
    S.eq("check-base: outside git fails closed", (r.returncode, "not a linked worktree: %s" % outside in r.stderr), (42, True))


def case_dispatch(R, S):
    sc = Scene()
    for sub in ("integrate", "fix-round", "revert", "cleanup", "summary"):
        r = R(sc.cwd, "wave", sub, env=sc.env)
        S.eq("wave %s: built in U3, no options is a usage error" % sub, (r.returncode, "usage: fwx wave %s" % sub in r.stderr, r.stdout), (2, True, ""))
    for argv in ([], ["bogus"]):
        r = R(sc.cwd, "wave", *argv, env=sc.env)
        S.ok("wave %s: usage, exit 2" % (argv or "(none)"), r.returncode == 2 and "usage: fwx wave" in r.stderr, r.stderr)
    r = R(sc.cwd, "wave", "prepare", env=sc.env)
    S.ok("wave prepare with no options: usage, exit 2", r.returncode == 2 and "usage: fwx wave prepare" in r.stderr, r.stderr)
    h = R(sc.cwd, "help")
    S.ok("`fwx help` lists wave", "wave" in h.stdout, h.stdout)


CASES = [case_base, case_models, case_clash, case_red_base, case_ignored, case_default_branch, case_plan, case_base_ref,
         case_unattended, case_security, case_done, case_worktree_checks, case_subphase, case_fix_options, case_check_base,
         case_dispatch]

# ---------------------------------------------------------------------------------------------------- the controls
# (case, file, old line, new line, the FAIL text it must produce); each `old` is in the file exactly once, and a control
# whose `old` has gone is an error, never a silent pass.
P, B = "lib/fwx/execute/prepare.py", "lib/fwx/execute/base.py"
MUTANTS = [
    ("clash not marked", case_clash, P, 'serial = any(c["wave"] == n for c in clashes)', "serial = False", "wave 1 serial=False, want True"),
    ("red base not run", case_red_base, P, "results = [verify.run_check(c, top) for c in recipe]", "results = []",
     "prepare exit 0 on a red base"),
    ("ignored file allowed", case_ignored, P, "ignored = _ignored(top, tasks)", "ignored = []", "prepare exit 0 with ignored config/forge.json"),
    ("default branch allowed", case_default_branch, P, "if branch in _defaults(top, cfg):", "if False:", "the refusal names the default branch"),
    ("baseRef not read", case_base_ref, P, "value = _base_ref(top, main, environ)", 'value = "head"', "prepare exit 0 with baseRef absent"),
    ("baseRef only from local", case_base_ref, P, 'os.path.join(conf, "settings.json"),', 'os.path.join(conf, "none.json"),', "baseRef from the user's settings: exit"),
    ("unattended never set", case_unattended, P, '"unattended": plane == "factory" or unattended,', '"unattended": False,',
     "factory args.unattended False, want True"),
    ("done from every branch", case_done, P, '"log", "refs/heads/" + branch,', '"log", "--all",', "a trailer on another branch is not done"),
    ("checks from the checkout", case_worktree_checks, P, "return config.load(top)",
     'return dict(config.DEFAULTS, project=dict(config.DEFAULTS["project"], checks=[]))', "from a worktree: exit: got (2,"),
    ("subphase as a phase", case_subphase, P, "if _is_subphase(part) else part", "if False else part", "subphase: context.md is the parent's"),
    ("check-base by merge-base", case_check_base, B, "if not head.startswith(sha):",
     'if git(top, "merge-base", "--is-ancestor", sha, "HEAD").returncode:', "an ancestor of HEAD is another base"),
    ("check-base in the main checkout", case_check_base, B, "if not linked(top):", "if False:", "the main checkout: exit 0, want 42"),
]


def mutant_tree(path, old, new):
    dest = helpers.mkdtemp("fwx-wave-mutant-")
    for d in ("bin", "lib", "data", "templates"):
        if os.path.isdir(os.path.join(ROOT, d)):
            shutil.copytree(os.path.join(ROOT, d), os.path.join(dest, d), ignore=shutil.ignore_patterns("__pycache__"))
    p = os.path.join(dest, path)
    text = open(p, encoding="utf-8").read()
    assert text.count(old) == 1, "control: %r is in %s %d times, want 1" % (old, path, text.count(old))
    open(p, "w", encoding="utf-8").write(text.replace(old, new))
    return dest


if __name__ == "__main__":
    real = runner(ROOT)
    for case in CASES:
        case(real, s)
    for name, case, path, old, new, needle in MUTANTS:
        m = helpers.Suite()
        try:
            tree = mutant_tree(path, old, new)
        except (AssertionError, OSError) as e:
            s.ok("control %s: built" % name, False, str(e))
            continue
        case(runner(tree), m)
        s.ok("control %s: the case fails" % name, bool(m.fails), "the mutant passed all %d checks" % m.checks)
        s.ok("control %s: fails with %r" % (name, needle), any(needle in f for f in m.fails),
             "FAILs: %s" % "; ".join(f[:140] for f in m.fails[:3]))
    s.done()
