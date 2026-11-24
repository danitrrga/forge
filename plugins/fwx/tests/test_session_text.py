#!/usr/bin/env python3
"""The session skill's text where code reads it or the owner set the rule: the commands it names exist, the fields it reads are fields the code
has, the commit line of rule 4 does what it says in a toy repo, a rejection is asked before it is reverted, a phase worktree is removed only
once its PR is merged, nothing launches a `decisions` agent or tells the session to ask without a recommendation.

Plain Python, no network: it reads skills/session/ of the checkout it sits in (`python3 tests/test_session_text.py [ROOT]` reads another
tree) and runs that tree's `bin/fwx --help` for the command list. Commands that only exist on another branch (`walk` on the UI-walk
branch) are SKIPped with their reason printed, never silently; the rest must exist.

09.3 T33 kept the checks that a code path reads (a command, a field, a stage the table allows, the line rule 4 runs) or that guard a rule the
owner set (DTC-34 on worktrees, D9 on recommendations, D11 on the end of fwx's work at the pull request, D17 on recording decisions), and
removed the checks that pinned wording (the steps' sentences, the sub-steps of step 8, rule 9, the words of ui-review.md, the critique
skills' "another model", the shared marker `Noticed:`) together with their red logs.

Seen red on copies of the real texts (a copy of plugins/fwx with the pinned words changed; the first FAIL line printed):
  references/part-report.md, "fwx report lint" -> "fwx report check":  FAIL: part-report.md saves the returned report with Write, then checks it -> no 'report-<n>.md' ... 'Write' ... 'fwx report lint' in that order after the `state` launch
  references/ui-review.md, "details.unverified" -> "details.unverfied":  FAIL: references/ui-review.md cites only fields the workflow returns -> not returned: ['unverfied']
  references/ui-review.md, "`support` `approved`" -> "`support` `approvd`":  FAIL: ui-review.md names the support of `not_defect` and `redo`, each a value `fwx decision new` accepts -> ui-review.md {'not_defect': 'approvd', 'redo': 'chosen'}, SUPPORT ('chosen', 'approved', 'unexamined', 'agent-assumption')
  references/ui-review.md, "revert it?" -> "proceed?":  FAIL: ui-review.md asks before the revert -> no 'revert it?' before the first '--revert'
  SKILL.md, "-name '*.tsv'" -> "-name '*.tsvx'" (the line of rule 4 is run in a toy repo):  FAIL: rule 4's commit line adds the documents and the demo pages -> rc 0, tracked ['.fwx/PROJECT.md', ..., '.fwx/milestones/v1/phases/01-a/research/r.md'] (no audit.tsv)
  SKILL.md, "--state merged" -> "--state open" (DTC-34):  FAIL: SKILL.md step 0 clears merged worktrees: merged PR, clean, no force -> missing: ['--state merged']
  SKILL.md, "fwx session --json" -> "fwx session --jsn":  FAIL: SKILL.md step 0 clears worktrees before the retake and the resume -> order is not sweep, retake, resume
  references/factory-return.md, "fwx decision new" -> "the `decisions` agent" (D17):  FAIL: no text launches or names the `decisions` agent, and its file is gone -> references/factory-return.md:9
  SKILL.md, "Recommended:" -> "Suggested:" (D9):  FAIL: every question to the owner carries a `Recommended:` line -> no `Recommended:` in ['SKILL.md rule 6', 'SKILL.md step 4', 'SKILL.md step 8']
Each kept check also has a control on a toy text (the "control:" checks).
"""
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.realpath(sys.argv[1]) if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
SESSION = os.path.join(ROOT, "skills", "session")
fails, skips, looked = [], [], [0]

# Commands that only exist on a branch this one does not contain yet; each is SKIPped with its reason.
ELSEWHERE = {
    "walk": "the UI-walk branch (feat/3.5-ui-walk)",
}


def check(name, ok, detail=""):
    looked[0] += 1
    if not ok:
        fails.append("FAIL: %s -> %s" % (name, detail))


def read(rel):
    with open(os.path.join(SESSION, rel), encoding="utf-8") as f:
        return f.read()


def returned_fields(js):
    """(top, details): the keys at the first level of the object a workflow script returns (its last top-level `return {`), and the keys at the
    first level of its `details` object, found by the braces (comment lines left out, nested objects not counted)."""
    body = "\n".join(ln for ln in js[js.rindex("\nreturn {"):].splitlines() if not ln.strip().startswith("//"))
    keys, depth, i = {0: set(), 1: set()}, 0, 0
    inside = None  # the depth at which the `details` object's keys sit
    while i < len(body):
        c = body[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if inside is not None and depth < inside:
                inside = None
        else:
            m = re.match(r"([a-z][a-z_]*):", body[i:]) if (c.isalpha() and not body[i - 1].isalnum() and body[i - 1] != "_") else None
            if m:
                if depth == 1:
                    keys[0].add(m.group(1))
                    if m.group(1) == "details":
                        inside = 2
                elif inside is not None and depth == inside:
                    keys[1].add(m.group(1))
                i += len(m.group(1))
        i += 1
    return keys[0], keys[1]


def cited_missing(text, returned):
    """The `details.<field>` words of a text that the returned object's `details` has no key for (a top-level field such as `reason` is not
    one: `details.reason` is a field nobody returns)."""
    return [k for k in re.findall(r"details\.([a-z][a-z_]*)", text) if k not in returned[1]]


def supports(text):
    """{answer: the support the text says the decisions agent records for it}, for `not_defect` and `redo`: "`x` with support `y`" or "`x`: `support` `y`"."""
    return {w: m.group(1) for w in ("not_defect", "redo") for m in [re.search(r"`%s`(?::| with) (?:`support`|support) `(\w+)`" % w, text)] if m}


def asks_before_revert(text):
    ask, flag = text.find("revert it?"), text.find("--revert")
    return ask != -1 and (flag == -1 or ask < flag)


def step(text, n):
    """The text of numbered step `n` of SKILL.md, after its `## Steps` heading (the fixed rules above it are numbered too), up to the
    next numbered step or the end."""
    text = text[text.find("## Steps"):] if "## Steps" in text else text
    m = re.search(r"^%d\. \*\*.*?(?=^\d+\. \*\*|\Z)" % n, text, re.S | re.M)
    return m.group(0) if m else ""


def commit_effect(line, stale=False, demo=True, twice=False):
    """Run rule 4's commit line in a toy repo holding the documents of a phase beside what the UI walk leaves, and say what it did:
    (exit code, tracked files under .fwx/, untracked ones, files of the last commit, exit code of a second run or None). `<main_checkout>` is
    the toy, `<message>` is `m`. `stale`: an older session tracked a walk's `demo-state.json` (not a document) and it has changed since;
    `demo` False: the phase has no demo page; `twice`: the line runs a second time with nothing new."""
    with tempfile.TemporaryDirectory(prefix="fwx-rule4-") as toy:
        return _commit_effect(line, toy, stale, demo, twice)


def _commit_effect(line, toy, stale, demo, twice):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.test", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.test", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_CONFIG_NOSYSTEM="1")
    env = {k: v for k, v in env.items() if k not in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE")}
    phase = ".fwx/milestones/v1/phases/01-a"
    old_state = phase + "/ui-walk/0-0/demo-state.json"
    run = lambda cmd: subprocess.run(cmd, shell=True, cwd=toy, env=env, capture_output=True, text=True)
    run("git init -q -b master && echo x > README && git add -A && git commit -q -m toy")
    if stale:
        os.makedirs(os.path.dirname(os.path.join(toy, old_state)))
        with open(os.path.join(toy, old_state), "w") as f:
            f.write("old\n")
        run("git add -A && git commit -q -m older-session")
        with open(os.path.join(toy, old_state), "w") as f:
            f.write("changed\n")
    for rel in (".fwx/PROJECT.md", ".fwx/milestones/v1/MILESTONE.md", phase + "/context.md", phase + "/audit.tsv", phase + "/research/r.md", phase + "/demo/page.html",
                phase + "/demo/shot.png", phase + "/ui-walk/1-1/demo-state.json", phase + "/ui-walk/1-1/up.log", phase + "/ui-walk/1-1/shot.png"):
        if not demo and "/demo/page.html" in rel:
            continue
        os.makedirs(os.path.dirname(os.path.join(toy, rel)), exist_ok=True)
        with open(os.path.join(toy, rel), "w") as f:
            f.write("x\n")
    cmd = line.replace("<main_checkout>", toy).replace("<message>", "m")
    r = run(cmd)
    again = run(cmd).returncode if twice else None
    tracked = run("git ls-tree -r --name-only HEAD").stdout.split()
    untracked = run("git status --porcelain -uall").stdout.split("\n")
    last = run("git show --name-only --format= HEAD").stdout.split()
    return r.returncode, [f for f in tracked if f.startswith(".fwx/")], [u[3:] for u in untracked if u.startswith("?? ")], last, again


def rule6_of(text):
    return next((ln for ln in text.split("## Steps")[0].splitlines() if ln.startswith("6. **")), "")


def in_order(text, *words):
    """True when every word is in `text` and each comes after the one before it."""
    pos = -1
    for w in words:
        i = text.find(w, pos + 1)
        if i == -1:
            return False
        pos = i
    return True


def fwx_commands(text):
    """Top-level `fwx <name>` words; `fwx:execute` (a workflow) has a colon and is not one."""
    return set(re.findall(r"\bfwx ([a-z][a-z-]*)\b", text))


def main():
    texts = {rel: read(rel) for rel in ("SKILL.md", os.path.join("references", "ui-review.md"), os.path.join("references", "part-report.md"),
                                        os.path.join("references", "closing.md"), os.path.join("references", "factory-return.md"))}
    skill, review, closing = texts["SKILL.md"], texts[os.path.join("references", "ui-review.md")], texts[os.path.join("references", "closing.md")]
    rep_ref = texts[os.path.join("references", "part-report.md")]
    s8 = step(skill, 8)
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    from fwx import plan, state  # noqa: E402
    from fwx.core import stages  # noqa: E402

    # Every command the texts name exists, or is skipped with its reason.
    out = subprocess.run([sys.executable, os.path.join(ROOT, "bin", "fwx"), "--help"], capture_output=True, text=True)
    check("fwx --help ran", out.returncode == 0, out.stderr.strip())
    known = {m.group(1) for m in re.finditer(r"^  fwx ([a-z][a-z-]*)\s", out.stdout, re.M)}
    check("fwx --help lists commands", len(known) > 5, "listed %d" % len(known))
    named = set()
    for text in texts.values():
        named |= fwx_commands(text)
    check("the files name some fwx commands", len(named) > 5, "named %d" % len(named))
    for cmd in sorted(named):
        if cmd in known:
            check("fwx %s exists" % cmd, True)
        elif cmd in ELSEWHERE:
            skips.append("SKIP: fwx %s not checked: it lives on %s" % (cmd, ELSEWHERE[cmd]))
        else:
            check("fwx %s exists" % cmd, False, "not in `fwx --help`")

    # Every `references/<file>.md` the session skill cites exists, and every file in references/ is cited.
    cited = set(re.findall(r"references/([a-z-]+\.md)", skill))
    present = set(os.listdir(os.path.join(SESSION, "references")))
    check("every references/ file SKILL.md cites exists", not (cited - present), "missing %s" % sorted(cited - present))
    check("every file in references/ is cited by SKILL.md", not (present - cited), "uncited %s" % sorted(present - cited))

    # The `state` agent returns the report and the session saves it with `Write` (the harness refuses a subagent's Write of a report), then checks it.
    check("part-report.md saves the returned report with Write, then checks it", in_order(rep_ref, "`state`", "report-<n>.md", "`Write`", "fwx report lint"),
          "no 'report-<n>.md' ... 'Write' ... 'fwx report lint' in that order after the `state` launch")

    # 09.4 D13: the budget nag is gone, so no session text tells an agent to run `fwx budget` or to read its fields, and no check reads the
    # deleted lib/fwx/commands/budget.py. Seen red before the texts changed (rule 7, step 2 and step 5 still named it):
    #   FAIL: no session text names `fwx budget` or its fields -> SKILL.md: ['fwx budget', 'used_percentage', 'week_tight']
    nagging = {n: [w for w in ("fwx budget", "used_percentage", "week_tight") if w in tx] for n, tx in texts.items()}
    nagging = {n: ws for n, ws in nagging.items() if ws}
    check("no session text names `fwx budget` or its fields", not nagging, ", ".join("%s: %s" % kv for kv in sorted(nagging.items())))
    check("control: a text that names `fwx budget` is caught", any(w in "7. **Budget.** Run `fwx budget --json`" for w in ("fwx budget", "used_percentage")))
    check("step 8 reads `review: blocking` and the plan accepts that value", "`review: blocking`" in s8 and "blocking" in plan.REVIEWS,
          "step 8 names it: %s; plan.REVIEWS: %s" % ("`review: blocking`" in s8, plan.REVIEWS))
    check("steps 5 and 8 read `ui: true` and plan.py has a task key `ui`", "`ui: true`" in skill and '"ui"' in open(os.path.join(ROOT, "lib", "fwx", "plan.py"), encoding="utf-8").read(),
          "the text or the task keys lack it")
    check("the stage table allows phase-review -> ui-walk and phase-review -> planning (step 8 sends the session there)",
          stages.allowed("session", "phase-review", "ui-walk") and stages.allowed("session", "phase-review", "planning"), "refused")
    from fwx import plan_step  # noqa: E402
    check("step 8 gives the decision the source the briefs look for",
          "`source` `review of part <N>`" in s8 and bool(plan_step._REVIEWED.match("review of part 1")), "the skill and plan_step._REVIEWED disagree")

    # What a rejected fix records: `fwx decision new --support` takes a value of state.SUPPORT.
    named_supports = supports(review)
    check("ui-review.md names the support of `not_defect` and `redo`, each a value `fwx decision new` accepts",
          set(named_supports) == {"not_defect", "redo"} and all(v in state.SUPPORT for v in named_supports.values()), "ui-review.md %s, SUPPORT %s" % (named_supports, state.SUPPORT))
    check("control: a support the code does not know is caught", "approvd" not in state.SUPPORT and supports("`not_defect` with support `approvd`") == {"not_defect": "approvd"})
    check("ui-review.md asks before the revert", asks_before_revert(review), "no 'revert it?' before the first '--revert'")

    # A walk that did not finish is not "no findings": the session texts name the fields the workflow returns (`status`, `reason`, `details.unverified`,
    # `details.gaps`: copied from the object `workflows/ui-walk.js` returns, which tests/test_ui_walk_workflow.py pins key by key), so a renamed field
    # breaks this check. Top-level fields and `details` fields are kept apart (review of PR 125).
    with open(os.path.join(ROOT, "workflows", "ui-walk.js"), encoding="utf-8") as f:
        js = f.read()
    returned = returned_fields(js)
    top, det = returned
    check("the workflow returns the top-level fields the session texts cite", {"status", "reason", "phase_dir", "details"} <= top, "top-level %s" % sorted(top))
    check("the workflow returns the details fields the session texts cite", {"gaps", "unverified", "fix_file", "lost_slots"} <= det, "details %s" % sorted(det))
    for name, text in (("SKILL.md step 6", step(skill, 6)), ("references/ui-review.md", review)):
        check("%s cites only fields the workflow returns" % name, not cited_missing(text, returned), "not returned: %s" % cited_missing(text, returned))
    # a walk with no `fix_file` has no `fix.json`, so `fwx review new` would stop: ui-review.md says to skip the command then (review of PR 125).
    check("references/ui-review.md says what to do when `details.fix_file` is null", "`details.fix_file` null" in review and "do not run the command" in review, "missing")
    check("control: `details.reason` is flagged, `reason` is a top-level field only", cited_missing("read `details.reason`", returned) == ["reason"], "got %s" % cited_missing("read `details.reason`", returned))
    check("control: a details field is read as a details field", cited_missing("read `details.gaps` and `details.fix_file`", returned) == [])
    check("control: a cited field the workflow does not return is caught", cited_missing("read `details.unverfied`", returned) == ["unverfied"])
    # the runner has its own model role (haiku in the seed): step 6 reads it from `fwx model runner small`, not from the executor's.
    # Seen red on d348f8d: FAIL: SKILL.md step 6 reads models.runner from `fwx model runner small` -> missing
    s6 = step(texts["SKILL.md"], 6)
    check("SKILL.md step 6 reads models.runner from `fwx model runner small`", "`models.runner` from `fwx model runner small`" in s6 and "models.runner` from `fwx model executor" not in s6, "missing")

    # Rule 4: the documents are committed in the main checkout, only the documents: `.md` and `.tsv` files and the `demo/` pages, so the walk's
    # `demo-state.json` (demo session cookies), logs and screenshots stay untracked. The command line is run here as written, in a toy repo. A
    # `:(glob)` pathspec per pattern was tried first: `git add` fails outright when one pattern matches nothing, so the list comes from `find`.
    rule4 = next((ln for ln in skill.splitlines() if ln.startswith("4. **Commits of `.fwx/`**")), "")
    lines = re.findall(r"`(cd <main_checkout> && find [^`]*)`", rule4)
    check("rule 4 has one commit line built on `find`", len(lines) == 1, "found %d" % len(lines))
    if len(lines) == 1:
        rc, tracked, untracked, _, _ = commit_effect(lines[0])
        phase = ".fwx/milestones/v1/phases/01-a"
        check("rule 4's commit line adds the documents and the demo pages", rc == 0 and all(f in tracked for f in (
            ".fwx/PROJECT.md", ".fwx/milestones/v1/MILESTONE.md", phase + "/context.md", phase + "/audit.tsv", phase + "/research/r.md", phase + "/demo/page.html")),
              "rc %s, tracked %s" % (rc, tracked))
        check("rule 4's commit line leaves demo-state.json, a log and a screenshot untracked", all(any(u.endswith(n) for u in untracked) for n in (
            "demo-state.json", "up.log", "ui-walk/1-1/shot.png", "demo/shot.png")) and not [f for f in tracked if f.endswith(("demo-state.json", ".log", ".png"))],
              "untracked %s, tracked %s" % (untracked, tracked))
        # Review of PR 130: a `commit -- .fwx` records the working-tree contents of every tracked file under it, so a `demo-state.json` tracked by an
        # older session and changed since went into the commit although `find` left it out of `git add`.
        rc, _, _, last, _ = commit_effect(lines[0], stale=True)
        check("rule 4's commit line leaves a changed, previously tracked walk file out of the commit", rc == 0 and bool(last) and not [f for f in last if f.endswith("demo-state.json")],
              "rc %s, the commit holds %s" % (rc, last))
        rc, tracked, _, last, _ = commit_effect(lines[0], demo=False)
        check("rule 4's commit line works in a phase with no demo page", rc == 0 and ".fwx/milestones/v1/phases/01-a/context.md" in last and not [f for f in tracked if "/demo/" in f],
              "rc %s, the commit holds %s" % (rc, last))
        rc, _, _, _, again = commit_effect(lines[0], twice=True)
        check("rule 4's commit line run again with nothing new exits 1 (git: nothing to commit) and makes no empty commit", rc == 0 and again == 1, "rc %s, second rc %s" % (rc, again))
    old = commit_effect("git -C <main_checkout> add .fwx && git -C <main_checkout> commit -m \"<message>\" -- .fwx")
    check("control: the old line `git add .fwx` tracks the walk's session file", any(f.endswith("demo-state.json") for f in old[1]), "tracked %s" % old[1])
    check("control: `commit -- .fwx` after the find-built add commits a previously tracked walk file", any(f.endswith("demo-state.json") for f in commit_effect(
        "cd <main_checkout> && find .fwx -type f ! -name '.*' \\( -name '*.md' -o -name '*.tsv' -o -path '*/demo/*.html' \\) -print0 | git add --pathspec-from-file=- --pathspec-file-nul && git commit -m \"<message>\" -- .fwx",
        stale=True)[3]), "the control line did not commit it")

    # DTC-34, the owner's rule: the worktree of a phase is removed by the next session, once its PR is merged and it is clean, never at the close.
    cleanup = next((ln for ln in closing.splitlines() if re.match(r"\d+\. \*\*Cleanup\.\*\*", ln)), "")
    check("closing.md the cleanup step found", "fwx walk stop --orphans" in cleanup, "not found")
    check("closing.md the cleanup step does not remove the phase worktree", "git worktree remove" not in cleanup, "`git worktree remove` is in it")
    s0 = step(skill, 0)
    need = ["--state merged", "status --porcelain", ".claude/worktrees/", "no force", "git branch -d"]
    check("SKILL.md step 0 clears merged worktrees: merged PR, clean, no force", all(w in s0 for w in need), "missing: %s" % [w for w in need if w not in s0])
    check("SKILL.md step 0 never uses `git branch -D`", "branch -D" not in s0, "`git branch -D` is in it")
    check("SKILL.md step 0 clears worktrees before the retake and the resume", in_order(s0, "--state merged", "retake", "fwx session --json"), "order is not sweep, retake, resume")
    check("control: the old closing step 4 is caught", "git worktree remove" in "4. **Cleanup.** Remove it with `git worktree remove <path>` and no force.")
    check("control: a step 0 without the rule is caught", not all(w in "0. **Where you are.** Run `fwx session --json`." for w in need))
    check("control: a step 0 with `git branch -D` is caught", "branch -D" in "then `git branch -D <branch>`")
    check("control: step 0 is cut by step()", step("## Steps\n0. **A.** x\n1. **B.** y\n", 0).startswith("0. **A.**") and "y" not in step("## Steps\n0. **A.** x\n1. **B.** y\n", 0))

    # D11: before `closed` the orchestrator promotes the phase's decisions to the durable record (`fwx decision new --adr`), and fwx's work ends at the
    # pull request: nothing that merges, babysits or watches follows `gh pr create`.
    promote = "fwx decision new --adr"
    check("closing.md promotes passing decisions with `fwx decision new --adr` before step 3's `fwx stage <phase folder> closed`",
          in_order(closing, promote, "fwx stage <phase folder> closed"), "'%s' is not before 'fwx stage <phase folder> closed'" % promote)
    after_pr = closing[closing.find("gh pr create"):] if "gh pr create" in closing else ""
    after_pr_steps = [ln.split("**")[1] for ln in after_pr.splitlines() if re.match(r"\d+\. \*\*", ln)]
    after_pr_bans = ("babysit", "watch", "gh pr merge", "gh pr checks", "wait for CI", "poll")
    check("closing.md has a step after `gh pr create`", bool(after_pr_steps), "no numbered step after it")
    check("closing.md adds no merge, babysit or watch to the steps after the pull request",
          not [w for w in after_pr_bans if w in after_pr.replace("fwx walk", "")] and "merge it" not in after_pr, "found: %s" % [w for w in after_pr_bans if w in after_pr])
    check("control: a closing text that promotes after `closed` fails", not in_order("fwx stage <phase folder> closed then fwx decision new --adr", promote, "fwx stage <phase folder> closed"))
    check("control: a step that babysits the pull request is caught", "babysit" in "6. **Babysit.** After `gh pr create`, babysit the PR until CI is green.".split("gh pr create")[1])

    # The owner leaving changes nothing: the session passes no `--unattended` (the factory's flag).
    leave_re = re.compile(r"\b(add|pass)\w*\s+`--unattended`")
    bad = [(n, ln.strip()[:90]) for n, ln in enumerate(skill.splitlines(), 1) if leave_re.search(ln)]
    check("no line of SKILL.md tells the session to pass --unattended", not bad, ("line %d: %r" % bad[0]) if bad else "")
    check("control: 'add `--unattended` when the owner says he is leaving' is caught", leave_re.search("(add `--unattended` when the owner says he is leaving)") is not None)
    check("control: 'you pass no `--unattended`' is not caught", leave_re.search("you pass no `--unattended` (only the factory does)") is None)

    # D9, D17: the session records decisions itself with `fwx decision new` (no `decisions` agent) and every question to the owner carries a
    # recommendation. The texts are the session skill, its references and the three critique skills.
    skill_files = {"SKILL.md": os.path.join(SESSION, "SKILL.md")}
    for ref in ("ui-review.md", "factory-return.md", "closing.md", "part-report.md"):
        skill_files["references/" + ref] = os.path.join(SESSION, "references", ref)
    for name in ("plan", "pre-mortem", "post-mortem"):
        skill_files["skills/%s/SKILL.md" % name] = os.path.join(ROOT, "skills", name, "SKILL.md")
    scanned = {}
    for name, path in skill_files.items():
        with open(path, encoding="utf-8") as f:
            scanned[name] = f.read()
    check("the texts scanned for the decisions agent and the recommendation rule are looked at", len(scanned) == 8 and all(scanned.values()), "scanned %d" % len(scanned))
    decisions_hits = ["%s:%d" % (n, i) for n, t in scanned.items() for i, ln in enumerate(t.splitlines(), 1) if re.search(r"`(fwx:)?decisions`|decisions agent", ln)]
    if os.path.exists(os.path.join(ROOT, "agents", "decisions.md")):
        decisions_hits.append("agents/decisions.md exists")
    check("no text launches or names the `decisions` agent, and its file is gone", not decisions_hits, ", ".join(decisions_hits))
    recorders = [n for n in ("SKILL.md", "references/ui-review.md", "references/factory-return.md") if "fwx decision new" not in scanned[n]]
    check("the session, the UI review and the factory return record decisions with `fwx decision new`", not recorders, "missing in %s" % recorders)
    silent = ["%s:%d" % (n, i) for n, t in scanned.items() for i, ln in enumerate(t.splitlines(), 1)
              if re.search(r"never recommend|no recommendation|without a recommendation|unasked", ln, re.I)]
    check("no text tells the session to ask without a recommendation", not silent, ", ".join(silent))
    asking = [n for n, t in (("SKILL.md rule 6", rule6_of(skill)), ("SKILL.md step 4", step(skill, 4)), ("SKILL.md step 8", s8),
                             ("references/ui-review.md", review), ("references/factory-return.md", scanned["references/factory-return.md"])) if "Recommended:" not in t]
    check("every question to the owner carries a `Recommended:` line", not asking, "no `Recommended:` in %s" % asking)
    check("control: a decisions-agent line is caught", re.search(r"`(fwx:)?decisions`|decisions agent", "record it by the `decisions` agent") is not None)
    check("control: `decisions.tsv` is not a decisions-agent line", re.search(r"`(fwx:)?decisions`|decisions agent", "read `decisions.tsv`") is None)
    check("control: 'no recommendation unasked' is caught", re.search(r"no recommendation|unasked", "it carries no recommendation unasked", re.I) is not None)

    # controls of the checks above.
    check("control: a cited reference that is not there is caught", set(re.findall(r"references/([a-z-]+\.md)", "see references/gone.md and references/here.md")) - {"here.md"} == {"gone.md"})
    check("control: a step 8 that checks before it saves fails", not in_order("`state` returns; run fwx report lint on report-<n>.md, then `Write` it", "`state`", "report-<n>.md", "`Write`", "fwx report lint"))
    check("control: a step 8 that saves then checks passes", in_order("`state` returns; save it to report-<n>.md with `Write`, then run fwx report lint", "`state`", "report-<n>.md", "`Write`", "fwx report lint"))
    check("control: step() cuts one numbered step", step("1. **A.** x\n2. **B.** y\n3. **C.** z\n", 2).startswith("2. **B.**") and "z" not in step("1. **A.** x\n2. **B.** y\n3. **C.** z\n", 2))
    check("control: revert before the question fails", not asks_before_revert("run wave new --revert 1, then ask: revert it?"))
    check("control: question before the revert passes", asks_before_revert("ask: revert it? Then wave new --revert 1"))
    check("control: a command that does not exist is not known", "frobnicate" not in known and "frobnicate" in fwx_commands("run fwx frobnicate now"))


main()
for line in skips:
    print(line)
for line in fails:
    print(line)
print("%d checks looked at, %d failed, %d skipped" % (looked[0], len(fails), len(skips)))
sys.exit(1 if fails else 0)
